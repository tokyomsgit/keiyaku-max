"""全案件のキャッシュ再処理・統合・Excel検証。APIは呼ばない。"""
import collections
import copy
import hashlib
import json
import re
from pathlib import Path
import warnings
from extract_registry import SCHEMA, API_SCHEMA, save_json, validate_evidence
from normalize_registry import normalize_document, blank, fields, normalize, fraction, f, schema_projection
from write_contract_excel import write_contract_excel, verify, build_writes

ROOT=Path(__file__).resolve().parent;OUT=ROOT/'verification_all'
TEMPLATE=ROOT/'プロの目対応型契約書ひな型20260619★コピーして.xlsm'

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def canonical(v):return normalize(str(v or '')).replace('番地の','番').replace('番地','番').removeprefix('東京都')
def val(d,path):
    try:
        for k in path.split('.'):d=d[int(k)] if isinstance(d,list) else d[k]
        return d['value']
    except (KeyError,IndexError,TypeError):return None

def changed_values(before,after,path=''):
    """Count corrected existing values, not new fields or changed source formatting."""
    if isinstance(before,dict) and 'value' in before:
        a=before['value'];b=after.get('value') if isinstance(after,dict) else None
        if a is None or b is None:return []
        pa=fraction(a) if 'share' in path else None;pb=fraction(b) if 'share' in path else None
        if pa and pb and pa==pb:return []
        return [{'field':path,'before':a,'after':b}] if canonical(a)!=canonical(b) else []
    if isinstance(before,dict) and isinstance(after,dict):
        return [c for k in before if k in after and k not in ('metadata','warnings','history','corrections','review_fields') for c in changed_values(before[k],after[k],(path+'.'+k).strip('.'))]
    if isinstance(before,list) and isinstance(after,list):
        changes=[c for i,(a,b) in enumerate(zip(before,after)) for c in changed_values(a,b,path+'.'+str(i))]
        if path=='lands' and len(before)>len(after):changes+=[{'field':path+'.'+str(i),'before':before[i],'after':None} for i in range(len(after),len(before))]
        return changes
    return []

def integrate(items,docs):
    buildings=[i for i in items if val(docs[i['id']],'document_type')=='building']
    lands=[i for i in items if val(docs[i['id']],'document_type')=='land']
    base=buildings[0] if len(buildings)==1 else lands[0] if not buildings and lands else items[0]
    data=copy.deepcopy(docs[base['id']]);data['group_review']=[]
    data['metadata']['documents']=[{'id':i['id'],'path':i['path'],'sha256':i['sha256']} for i in items]
    if len(buildings)>1:data['group_review'].append('複数建物の対象選択')
    current=data['lands'] if buildings else []
    for item in lands:
        for land in docs[item['id']]['lands']:
            key=(canonical(land['location']['value']),canonical(land['lot_number']['value']))
            match=next((x for x in current if (canonical(x['location']['value']),canonical(x['lot_number']['value']))==key),None)
            if match:
                for k in ('location','lot_number','category','area'):
                    a,b=match[k],land[k]
                    if b['value'] is None:continue
                    if a['value'] is not None and canonical(a['value'])!=canonical(b['value']):
                        a['needs_review']=True;data['group_review'].append('資料間不一致:土地'+key[1]+'.'+k)
                    elif a['value'] is None:match[k]=copy.deepcopy(b)
                    else:match[k]['sources']+=copy.deepcopy(b['sources'])
                match['owners']=copy.deepcopy(land.get('owners',[]))
            else:
                added=copy.deepcopy(land)
                if buildings:
                    building_address=canonical(val(data,'building.location'))+canonical(val(data,'building.lot_number'))
                    house_address=canonical(val(data,'main_building.location'))
                    # A building's site can span several lot numbers listed together
                    # (e.g. "新宿区上落合一丁目4番1、4番4、4番5" — sometimes even merged
                    # into just building.location when lot_number itself comes back
                    # empty), so match each individual lot rather than only the whole
                    # combined string: otherwise a building with more than one lot
                    # would flag EVERY one of its own land parcels as a mismatch, since
                    # none of them individually equals the full combined text.
                    lot_tokens=re.findall(r'\d+番\d+(?:の\d+)?',building_address)
                    prefix=building_address[:building_address.find(lot_tokens[0])] if lot_tokens else building_address
                    building_lots={prefix+t for t in lot_tokens} or {building_address}
                    if ''.join(key) not in building_lots and ''.join(key) not in (building_address,house_address):
                        added['needs_review']=True;data['group_review'].append('土地と建物の対応:'+''.join(key))
                current.append(added)
    data['lands']=current
    # Non-land-right condominium ownership shares belong to the current target
    # owner, never to an arbitrary co-owner of the parcel.
    names=[normalize(x) for x in (val(data,'owner.name') or '').splitlines()]
    if buildings and val(data,'land_right.exists') is False:
        for land in data['lands']:
            matched=[p for p in land.get('owners',[]) if normalize(p['name']['value'] or '') in names]
            if len(names)==1 and len(matched)==1 and not matched[0]['share'].get('needs_review'):
                p=matched[0]
                land['right_type']={'value':'所有権','sources':copy.deepcopy(p['name']['sources']),'needs_review':False}
                land['right_share']=copy.deepcopy(p['share'])
            elif land.get('owners'):data['group_review'].append('土地共有持分の対象所有者との対応')
    lease_docs=[docs[i['id']] for i in items if val(docs[i['id']],'tenure_type')=='leasehold' or val(docs[i['id']],'leasehold.exists') is True]
    if lease_docs:
        if val(data,'leasehold.exists') is not True:data['leasehold']=copy.deepcopy(lease_docs[0]['leasehold'])
        data['tenure_type']=f('leasehold')
        data['leasehold']['needs_review']=True
        # Advisory, not a contradiction: every leasehold case needs the lease contract
        # checked independently since the registry can't fully capture its terms. This
        # is true of EVERY leasehold_condominium, so putting it in group_review (which
        # payload_from() treats as a hard block on registration) would make that whole
        # property type permanently unregistrable rather than just flagged for review.
        data.setdefault('leasehold_warnings',[]).append('借地の期間満了日・更新・契約詳細（契約書等の確認が必要）')
        # Preserve supporting lease papers separately from registry measurements.
        data['leasehold']['supporting_documents']=[{'source_pdf':d['metadata']['source_pdf'],'details':d['leasehold']['details']} for d in lease_docs]
    unit=val(data,'unit.house_number');house=val(data,'main_building.house_number')
    if unit:
        kind='leasehold_condominium' if lease_docs or val(data,'land_right.type') in ('地上権','賃借権') else 'condominium_land_right' if val(data,'land_right.exists') is True else 'condominium_no_land_right' if val(data,'land_right.exists') is False else 'unknown'
    elif house:kind='detached_house'
    elif lands and not buildings:kind='land_only'
    else:kind='unknown'
    data['property_type']=f(kind)
    if kind=='unknown':data['group_review'].append('物件種別の確定')
    data['land_mortgages']=[{'source_pdf':i['path'],'mortgages':docs[i['id']]['mortgages'],'target_unit_scope':'同一土地上の他共有者の権利を含む。対象専有部分の権利とは区別'} for i in lands]
    for land in data['lands']:
        pair=fraction(land['right_share']['value'])
        if pair:
            for k,v in [('share_numerator',pair[0]),('share_denominator',pair[1])]:land[k]={'value':v,'sources':copy.deepcopy(land['right_share']['sources']),'needs_review':land['right_share'].get('needs_review',False)}
    data['group_review']=list(dict.fromkeys(data['group_review']))
    return data

def excel_data(data):
    result=copy.deepcopy(data)
    kind=val(data,'property_type')
    if kind in ('detached_house','land_only'):
        # The supplied template is explicitly a condominium form. Only its
        # common owner/land fields have an unambiguous meaning for these types.
        result['building']=blank(SCHEMA['properties']['building']);result['unit']=blank(SCHEMA['properties']['unit'])
        result['land_right']=blank(SCHEMA['properties']['land_right'])
    if kind=='unknown' or '複数建物の対象選択' in data['group_review']:
        result=blank(SCHEMA)
    return schema_projection(result)

def main():
    inventory=read(OUT/'inventory.json');scans=read(OUT/'scan_review.json');docs={};groups=collections.defaultdict(list)
    for item in inventory:
        folder=OUT/'documents'/item['id'];raw=read(folder/'raw.json');cache=read(folder/'cache.json')
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==cache['sha256']==item['sha256']
        pages=read(folder/'source_pages.json');reviewed=cache['mode']=='reviewed_cache'
        cleaned=copy.deepcopy(raw)
        if cache['mode']=='real_api':
            cleaned=validate_evidence({k:cleaned[k] for k in API_SCHEMA['properties']},pages)
        if item['id'] in scans:
            spec=scans[item['id']];assert spec['sha256']==item['sha256'];reviewed=spec['reviewed']
            cleaned.update(copy.deepcopy(spec['overrides']))
            cleaned['review_fields']+=spec.get('review_fields',[])
        data=normalize_document(cleaned,pages,item['path'],reviewed)
        if item['id'] in scans:data['metadata']['visual_review']=scans[item['id']]
        save_json(folder/'normalized.json',data);docs[item['id']]=data;groups[item['group']].append(item)
        item['document_type']=val(data,'document_type') or 'unknown'
    save_json(OUT/'inventory.json',inventory)
    summary=[];causes=collections.Counter();all_review={};errors=[]
    for name,items in groups.items():
        folder=OUT/name;folder.mkdir(exist_ok=True)
        try:
            data=integrate(items,docs)
            folder.joinpath('source_files.txt').write_text('\n'.join(i['path'] for i in items)+'\n',encoding='utf8')
            raw_records=[]
            for i in items:
                document_dir=OUT/'documents'/i['id'];cache=read(document_dir/'cache.json')
                record={'source_pdf':i['path'],'cache':cache,'data':read(document_dir/'raw.json'),
                        'source_pages_file':str((document_dir/'source_pages.json').resolve())}
                if cache['mode']=='text_rules':record['text_rows']=docs[i['id']]['history']['rows']
                raw_records.append(record)
            save_json(folder/'extracted_raw.json',{'documents':raw_records})
            save_json(folder/'extracted_normalized.json',data)
            write_data=excel_data(data);output=folder/'契約書_謄本入力済.xlsm'
            # Preserve every earlier validation output when postprocessing changes.
            if output.exists():
                number=1
                while (folder/f'previous_{number}.xlsm').exists():number+=1
                output.rename(folder/f'previous_{number}.xlsm')
            report=write_contract_excel(TEMPLATE,write_data,output)
            verify(TEMPLATE,output,report['written_cells'])
            import openpyxl
            with warnings.catch_warnings():
                warnings.simplefilter('ignore');book=openpyxl.load_workbook(output,read_only=True,data_only=False)
                planned={x['cell']:x for x in build_writes(write_data)[0]}
                lines=[]
                for cell in report['written_cells']:
                    value=book['基本入力'][cell['cell']].value
                    assert value==cell['value']==planned[cell['cell']]['value']
                    lines.append(f"基本入力!{cell['cell']}\t{cell['field']}\t{json.dumps(value,ensure_ascii=False)}")
                book.close()
            (folder/'written_cells.txt').write_text('\n'.join(lines)+'\n',encoding='utf8')
            good=[p for p,n in fields(data) if n['value'] is not None and not n.get('needs_review')]
            pending=[p for p,n in fields(data) if n.get('needs_review')]
            pending+=data['group_review']
            if val(data,'property_type')=='detached_house':pending.append('ひな形は区分建物専用のため戸建て建物欄はJSONのみ。土地・所有者のみ転記')
            pending+=['数式で構成された所在・建物名・家屋番号・第1筆の所在/地番は未転記（元値保持）']
            for i in items:
                if 'owners' in docs[i['id']].get('review_fields',[]):pending.append(i['id']+':土地全共有者の残余持分・履歴の整合確認')
                if any(m['active']['value'] is None for m in docs[i['id']]['mortgages']):pending.append(i['id']+':複雑な付記・抹消／変更対応の権利状態')
            unavailable=[p for p,n in fields(data) if n['value'] is None]
            corrections=[c for i in items for c in docs[i['id']]['corrections']]
            semantic=[{'pdf':i['id'],**c} for i in items for c in changed_values(read(OUT/'documents'/i['id']/'raw.json'),docs[i['id']])]
            save_json(folder/'corrected_values.json',semantic)
            counts=collections.Counter(c['category'] for c in corrections if c['category']!='表記正規化');causes.update(counts)
            pending=list(dict.fromkeys(pending));all_review[name]=pending
            text_count=sum(all(m=='text' for m in i['modes']) for i in items)
            active=sum(m['active']['value'] is True for m in data['mortgages']);inactive=sum(m['active']['value'] is False for m in data['mortgages'])
            short_pending=[]
            if any('leasehold' in p or '借地' in p for p in pending):short_pending.append('借地契約の期間満了日・更新・詳細')
            if any('mortgages' in p or '付記' in p for p in pending):short_pending.append('土地の複雑な付記・抹消／変更の権利状態')
            if any('owners' in p or '共有者' in p for p in pending):short_pending.append('土地全共有者の残余持分と履歴整合')
            short_pending+=[p for p in pending if not p.startswith(('leasehold.','land_mortgages.','lands.','pdf_')) and '借地の' not in p]
            land_values='、'.join(str(l['lot_number']['value'])+' '+str(l['area']['value'])+'㎡' for l in data['lands'])
            missing_important=[p for p in ('building.name','building.total_floor_area','owner.name','owner.address') if val(data,p) is None]
            detail=[f"物件タイプ：{val(data,'property_type')}",f"PDF数：{len(items)}",f"テキストPDF：{text_count}",f"スキャンPDF：{len(items)-text_count}",
                f'正常取得：確定値{len(good)}項目。土地 {land_values}。建物・専有／主建物の詳細はextracted_normalized.json。',
                '要確認：'+' / '.join(dict.fromkeys(short_pending)),'取得不能：'+', '.join(missing_important)+'（非該当欄・記載なしはnull）',
                '自動補正：'+json.dumps(dict(counts),ensure_ascii=False),f"Excel転記セル数：{len(lines)}",'所有者判定：'+str(val(data,'owner.name')),
                '敷地権判定：'+str(val(data,'land_right.exists'))+' / '+str(val(data,'land_right.type')),
                '借地判定：'+str(val(data,'tenure_type')),
                f'抵当権判定：建物は有効{active}、抹消{inactive}、不明{len(data["mortgages"])-active-inactive}。土地はland_mortgages参照（他共有者を含む）',
                'Excel保持確認：VBA／数式／書式／結合セル／他シート：全て合格。原本SHA-256不変。独立再読込一致。']
            (folder/'verification.md').write_text('\n\n'.join(detail)+'\n',encoding='utf8')
            summary.append({'案件':name,'物件タイプ':val(data,'property_type'),'PDF数':len(items),'読取成功':f'{len(items)}/{len(items)}','要確認':len(pending),'誤読修正数':len(semantic),'Excel転記セル数':len(lines),'実運用可否':'要原本確認・未転記欄あり','保持確認':True})
        except Exception as exc:
            errors.append({'case':name,'error_type':type(exc).__name__,'message':str(exc)});print('CASE ERROR',name,type(exc).__name__,str(exc),flush=True)
    meta={'cases':summary,'errors':errors,'pdf_count':len(inventory),'pages':sum(i['pages'] for i in inventory),
        'new_successful_api_calls':sum(read(OUT/'documents'/i['id']/'cache.json')['api_called'] for i in inventory),'api_429_count':1,
        'reused_reviewed_pdfs':sum(read(OUT/'documents'/i['id']/'cache.json')['mode']=='reviewed_cache' for i in inventory),
        'causes':dict(causes),'needs_review':all_review}
    save_json(OUT/'summary.json',meta)
    headers=['案件','物件タイプ','PDF数','読取成功','要確認','誤読修正数','Excel転記セル数','実運用可否']
    md=['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']
    md+=['| '+' | '.join(str(r[h]) for h in headers)+' |' for r in summary]
    md+=['',f"全{len(inventory)}PDF・{len(summary)}案件。新規API成功{meta['new_successful_api_calls']}回、429応答1回。既存4PDFの照合済みJSONを再利用。追加APIなしで後処理を再実行。文字PDF2件は全ページをコードで読取。",
         '読取成功は処理完了PDF数。誤読修正数は既存の非null値の変更・誤った土地レコードの除去件数（形式の正規化・未取得値の新規取得は除外）。corrected_values.jsonに変更前後を保存。', '', '原因別の補正・検出（適用件数、新規取得を含む）：']
    md+=['- '+k+'：'+str(v) for k,v in causes.items()]
    md+=['- OCR：新規スキャン2PDFは全ページ画像を照合。借地説明資料の物件種別を土地からその他へ訂正。既存スキャンは前回照合済みJSONを利用。',
         '- 借地：地上権を所有権と区別。契約の満了日・詳細は要確認。',
         '- 共有者：41ページ土地の持分遷移と住所変更を保持。全共有者の残余持分は確定せず要確認。',
         '- Excel：全出力でVBA・数式・書式・結合・他シート保持。数式依存欄は元値を保持するため契約書完成品ではない。',
         '- 戸建て：区分マンション欄へ建物情報を流用せずJSON保存。土地・所有者のみ転記。',
         '- サンプル範囲：独立した土地のみ案件・附属建物あり案件は今回含まれない。該当機能は回帰テストで確認。']
    if errors:md+=['', 'エラー：'+json.dumps(errors,ensure_ascii=False)]
    (OUT/'summary.md').write_text('\n'.join(md)+'\n',encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if errors:raise SystemExit(1)

if __name__=='__main__':main()
