"""登記の表罫線・見出しに基づく後処理。PDF固有の座標・正解値は持たない。"""
import copy
import re
from fractions import Fraction
from extract_registry import API_SCHEMA, SCHEMA, normalize


def blank(schema):
    if schema.get('type') == 'object': return {k: blank(v) for k,v in schema['properties'].items()}
    if schema.get('type') == 'array': return []
    return None


def f(value=None, page=1, text='', review=False):
    return {'value': value, 'sources': [{'page':page,'text':text}] if value is not None else [], 'needs_review':review}


def rows_from_pages(pages):
    section='title'; rows=[]
    for page in pages:
        text=page['text']
        text=re.sub(r'(┃[^┃│]*附属建物[^┃│]*┃)',r'┠─┨\1┠─┨',text)
        blocks=re.split(r'[┠├][─┬┴┼]+┨|[┏┗][━┯┷┳]+[┓┛]',text)
        for block in blocks:
            compact=normalize(block)
            if '権利部(甲区)' in compact: section='A'
            elif '権利部(乙区)' in compact: section='B'
            elif '┃共同担保目録┃' in compact: section='collateral'
            cells=[]
            for row in block.split('┃'):
                if '│' not in row or any(x in row for x in '┠┗┏┼'): continue
                parts=row.split('│')
                while len(cells)<len(parts):cells.append([])
                for i,p in enumerate(parts):
                    p=p.strip()
                    if p: cells[i].append(p)
            if not cells and '附属建物' in compact:cells=[[compact.strip('┃')]]
            if cells:
                row={'page':page['page'],'section':section,'columns':[''.join(p) for p in cells], 'fragments':cells,
                     'fragment_pages':[[page['page']]*len(p) for p in cells]}
                if len(cells)==4 and not any(normalize(x) for x in row['columns'][:3]) and rows and rows[-1]['section']==section and len(rows[-1]['columns'])==4:
                    for i in range(4):
                        rows[-1]['columns'][i]+=row['columns'][i];rows[-1]['fragments'][i]+=cells[i];rows[-1]['fragment_pages'][i]+=row['fragment_pages'][i]
                else:rows.append(row)
    return rows


def rf(value,row,col,review=False):
    return {'value':value,'sources':[{'page':p,'text':s} for p,s in zip(row['fragment_pages'][col],row['fragments'][col])] if value is not None else [],'needs_review':review}


def fraction(value):
    text=normalize(str(value)).replace(',','')
    # "32万7285" is 327285: a 万/億 multiplies its own digits and the digits after it are added.
    text=re.sub(r'(?:(\d+)億)?(?:(\d+)万)?(\d*)',lambda m:str(int(m[1] or 0)*10**8+int(m[2] or 0)*10**4+int(m[3] or 0)) if '万' in m[0] or '億' in m[0] else m[0],text)
    m=re.fullmatch(r'(\d+)分の(\d+)',text)
    if m and 0<int(m[2])<=int(m[1]):return int(m[2]),int(m[1])
    m=re.fullmatch(r'(\d+)/(\d+)',text)
    if m and 0<int(m[1])<=int(m[2]):return int(m[1]),int(m[2])
    return None


def fields(node,path=''):
    if isinstance(node,dict) and 'value' in node:yield path,node
    elif isinstance(node,dict):
        for k,v in node.items():
            if k not in ('history','metadata','corrections'):yield from fields(v,(path+'.'+k).strip('.'))
    elif isinstance(node,list):
        for i,v in enumerate(node):yield from fields(v,path+'.'+str(i))


def schema_projection(data,schema=SCHEMA):
    """レビュー対象を除外して既存writerのスキーマへ射影する。"""
    if schema.get('type')=='object':
        data=data if isinstance(data,dict) else {}
        if data.get('needs_review') and 'value' not in data:
            return blank(schema)
        if 'value' in data and data.get('needs_review'):
            data={**data,'value':None,'sources':[]}
        return {k:schema_projection(data.get(k),s) for k,s in schema['properties'].items()}
    if schema.get('type')=='array':return [schema_projection(x,schema['items']) for x in data or []]
    return data


def normalize_document(raw,pages,source_pdf='',reviewed=False,table_read=False):
    """table_read: raw came from rule_registry, which already read these rows, so the AI corrections below are skipped."""
    data=blank(API_SCHEMA); data.update(copy.deepcopy({k:v for k,v in raw.items() if k in API_SCHEMA['properties']}))
    data['corrections']=[]; data['history']={'raw_current_candidates':copy.deepcopy(raw),'rows':rows_from_pages(pages)}
    data['history']['extraction_warnings']=copy.deepcopy(data['warnings']);data['warnings']=[]
    for warning in data['history']['extraction_warnings']:
        if ': 根拠不備' in warning:
            path=re.sub(r'\[(\d+)\]',r'.\1',warning.split(':')[0])
            data['review_fields'].append(path)
    def change(container,key,value,category,reason):
        previous=copy.deepcopy(container.get(key))
        if previous!=value:
            data['corrections'].append({'category':category,'reason':reason,'before':previous,'after':copy.deepcopy(value)})
        container[key]=value
    text='\n'.join(p['text'] for p in pages); compact=normalize(text)
    full_text=all(p['mode']=='text' for p in pages)
    is_unit='専有部分の建物の表示' in compact
    is_house='主である建物の表示' in compact
    is_land='表題部(土地の表示)' in compact and not is_house and not is_unit
    if is_unit: change(data,'document_type',f('building',1,'専有部分の建物の表示'),'物件種別判定','区分建物の見出し')
    elif is_house:change(data,'document_type',f('building',1,'主である建物の表示'),'物件種別判定','主である建物の見出し')
    elif is_land:change(data,'document_type',f('land',1,'土地の表示'),'物件種別判定','土地単独の見出し')
    elif reviewed and data['unit']['house_number']['value']:
        data['document_type']={'value':'building','sources':copy.deepcopy(data['unit']['house_number']['sources']),'needs_review':False}

    for path,node in fields(data):
        node.setdefault('needs_review',False)
        v=node['value']
        if isinstance(v,str):
            import unicodedata
            v=unicodedata.normalize('NFKC',v)
            if any(x in path for x in ('area','registered_area')):
                candidate=re.sub(r'(?<=\d):(?=\d)','.',normalize(v))
                if re.fullmatch(r'\d+(\.\d+)?',candidate):v=float(candidate)
            if 'share' in path and fraction(v):
                n,d=fraction(v); v=f'{d}分の{n}'
            if v!=node['value']:change(node,'value',v,'面積表記' if 'area' in path else '表記正規化',path)
        if path in data.get('review_fields',[]):node['needs_review']=True
        if not full_text and not reviewed:node['needs_review']=node['value'] is not None
    rows=data['history']['rows']
    # One land title is a sequence of modifications, not a list of parcels.
    if not table_read and is_land and full_text and compact.count('表題部(土地の表示)')==1 and '閉鎖' not in compact:
        current=blank(SCHEMA['properties']['lands']['items'])
        for row in rows:
            if row['section']!='title':continue
            c=[normalize(x) for x in row['columns']]
            if len(c)>=2 and c[0]=='所在':current['location']=f(c[1],row['page'],row['columns'][1])
            if len(c)==4:
                if re.fullmatch(r'\d+番(?:\d+)?',c[0]):current['lot_number']=f(c[0],row['page'],row['columns'][0])
                if c[1] in ('宅地','田','畑','山林','雑種地','公衆用道路','原野','境内地','墓地','池沼','水道用地','用悪水路','保安林'):
                    current['category']=f(c[1],row['page'],row['columns'][1])
                m=re.fullmatch(r'([\d,]+)[:.](\d{2}):*',c[2])
                if m:current['area']=f(float(m[1].replace(',','')+'.'+m[2]),row['page'],row['columns'][2])
        if all(current[k]['value'] is not None for k in ('location','lot_number','category','area')):
            change(data,'lands',[current],'過去履歴誤採用','表題部各列の最後の変更を現在値に統合')

    if not table_read and full_text and (is_unit or is_house):
        target='main_building' if is_house else 'building'
        for row in rows:
            if row['section']!='title':continue
            c=[normalize(x) for x in row['columns']]; page=row['page']
            if '専有部分の建物の表示' in ''.join(c):target='unit';continue
            if '附属建物' in ''.join(c):target='annex';data['review_fields'].append('annex_buildings');continue
            if target=='annex':
                if len(c)>=5 and '造' in c[2] and not c[0].startswith('符号'):
                    annex=blank(API_SCHEMA['properties']['annex_buildings']['items'])
                    annex['identifier']=rf(c[0],row,0)
                    annex['type']=rf(c[1],row,1);annex['structure']=rf(c[2],row,2)
                    for fragment in row['fragments'][3]:
                        for m in re.finditer(r'((?:地下)?\d+階)([\d,]+)[:.](\d{2})',normalize(fragment)):
                            annex['floor_areas'].append({'floor':f(m[1],page,fragment),'area':f(float(m[2].replace(',','')+'.'+m[3]),page,fragment)})
                    data['annex_buildings'].append(annex)
                continue
            dest=data[target]
            def title_field(key,value,col):
                val={'value':value,'sources':[{'page':page,'text':s} for s in row['fragments'][col]],'needs_review':False}
                change(dest,key,val,'表罫線折返し','見出し内の同じ列を復元: '+key)
            if len(c)>1 and c[0] in ('所在','家屋番号','建物の名称'):
                key={'所在':'location','家屋番号':'house_number','建物の名称':'name'}[c[0]]
                if key in dest:
                    value=c[1]
                    if target=='building' and key=='location':
                        lots=re.findall(r'\d+番地\d+',value)
                        if len(lots)==1:
                            title_field('lot_number',lots[0],1);value=value.replace(lots[0],'')
                    title_field(key,value,1)
            if len(c)==3 and target=='building' and '造' in c[0] and not c[0].startswith('①'):
                title_field('structure',c[0],0)
                areas=[]
                for fragment in row['fragments'][1]:
                    for m in re.finditer(r'((?:地下)?\d+階)\s*([\d,]+)[:.](\d{2})',normalize(fragment)):
                        areas.append({'floor':f(m[1],page,fragment),'area':f(float(m[2].replace(',','')+'.'+m[3]),page,fragment)})
                if areas:change(dest,'floor_areas',areas,'面積表記','各階の面積を同じ列の対応で復元')
            if len(c)==4 and target in ('unit','main_building') and '造' in c[1] and not c[1].startswith('②'):
                title_field('type',c[0],0);title_field('structure',c[1],1)
                if target=='unit':
                    m=re.search(r'((?:地下)?\d+階)(?:部分)?([\d,]+)[:.](\d{2})',c[2])
                    if m:title_field('floor',m[1],2);title_field('registered_area',float(m[2].replace(',','')+'.'+m[3]),2)
                else:
                    areas=[]
                    for fragment in row['fragments'][2]:
                        for m in re.finditer(r'((?:地下)?\d+階)([\d,]+)[:.](\d{2})',normalize(fragment)):
                            areas.append({'floor':f(m[1],page,fragment),'area':f(float(m[2].replace(',','')+'.'+m[3]),page,fragment)})
                    if areas:change(dest,'floor_areas',areas,'面積表記','主である建物の階別面積を取得')
                m=re.search(r'((?:明治|大正|昭和|平成|令和)(?:元|\d+)年\d+月\d+日)新築',c[3])
                if m:title_field('built_date',m[1],3)

    # No land-right section on a complete condominium certificate is a valid absence.
    if is_unit and full_text and '敷地権の表示' not in compact:
        change(data['land_right'],'exists',f(False,1,'専有部分の建物の表示'),'敷地権','全文確認：敷地権の表示なし')
        data['land_right']['type']=f();data['land_right']['share']=f()
    if is_house:
        change(data,'property_type',f('detached_house',1,'主である建物の表示'),'物件種別判定','戸建てを区分建物と区別')
        # Writer must not route a detached house into condominium unit fields.
        data['unit']=blank(SCHEMA['properties']['unit'])
        data['building']=blank(SCHEMA['properties']['building'])
        # Collateral schedules can mention other parcels; they are not title lands.
        if data['lands']:
            change(data,'lands',[],'複数土地','主である建物PDFの共同担保目録を敷地の筆として流用しない')
    if is_land:data['property_type']=f('land_only',1,'土地の表示')

    # Current ownership: exact full transfers are resolvable. Partial transfers
    # remain reviewable instead of silently replacing all co-owners.
    arows=[r for r in rows if r['section']=='A' and len(r['columns'])==4]
    transfers=[(i,r) for i,r in enumerate(arows) if normalize(r['columns'][1]) in ('所有権移転','所有権保存')]
    if not table_read and full_text and transfers:
        i,last=transfers[-1]
        later=arows[i+1:]
        if not any('移転' in normalize(r['columns'][1]) and '住所' not in normalize(r['columns'][1]) for r in later):
            persons=parse_owners(last)
            if persons:
                for r in later:
                    purpose=normalize(r['columns'][1]); target=re.match(r'(\d+)番登記名義人住所変更',purpose)
                    if target and target[1]==normalize(last['columns'][0]):
                        tail=normalize(r['columns'][3]); address=re.search(r'(?:住所|住所氏名)(.+?)(?:順位|$)',tail)
                        if address and len(persons)==1:persons[0]['address']=f(address[1],r['page'],r['columns'][3])
                change(data,'owners',persons,'所有者判定','甲区の最後の所有権全体移転を採用、対応順位の住所変更を反映')
                for k in ('name','address'):
                    value='\n'.join(p[k]['value'] for p in persons if p[k]['value'])
                    data['owner'][k]={'value':value or None,'sources':[s for p in persons for s in p[k]['sources']], 'needs_review':any(p[k].get('needs_review') for p in persons)}
    if not table_read and full_text and is_land and len(arows)>30:
        people,uncertain=ownership_ledger(arows)
        change(data,'owners',people,'所有者判定','共有者の全部持分移転・住所変更を順次適用。未確定な残余持分は要確認')
        data['owner']={'name':f(None,review=True),'address':f(None,review=True)}
        if uncertain:data.setdefault('review_fields',[]).append('owners')

    b_rows=[r for r in rows if r['section']=='B' and len(r['columns'])==4]
    if not table_read and full_text:
        mortgages=parse_mortgages(b_rows)
        if mortgages:change(data,'mortgages',mortgages,'抵当権判定','乙区の設定順位と明示的抹消対象を照合。複雑な付記は要確認')
    lease_rows=[r for r in b_rows if '地上権設定' in normalize(r['columns'][1]) or '賃借権設定' in normalize(r['columns'][1])]
    if not table_read and lease_rows:
        r=lease_rows[0]; kind='地上権' if '地上権' in r['columns'][1] else '賃借権'
        rank=normalize(r['columns'][0]); cancelled=any(re.search(re.escape(rank)+r'番'+kind+'抹消',normalize(x['columns'][1])) for x in b_rows)
        if not cancelled:
            change(data,'tenure_type',f('leasehold',r['page'],r['columns'][1]),'借地','乙区の借地系権利を検出')
            data['leasehold']={'exists':f(True,r['page'],r['columns'][1]),'type':f(kind,r['page'],r['columns'][1]),'details':f(None,review=True),'needs_review':True}
    for land in data['lands']:
        loc=land['location']['value']; lot=land['lot_number']['value']
        if loc and lot and normalize(loc).endswith(normalize(lot)):
            change(land['location'],'value',normalize(loc)[:-len(normalize(lot))],'地番','所在地から重複地番を分離')
        pair=fraction(land['right_share']['value'])
        land['share_numerator']=f(pair[0],land['right_share']['sources'][0]['page'],land['right_share']['sources'][0]['text']) if pair else f()
        land['share_denominator']=f(pair[1],land['right_share']['sources'][0]['page'],land['right_share']['sources'][0]['text']) if pair else f()
        land['owners']=copy.deepcopy(data['owners']) if is_land else []
    loc=data['building']['location']['value'];lot=data['building']['lot_number']['value']
    if loc and lot and '\n' in lot and '\n' not in loc:
        remaining=normalize(loc);places=[];numbers=[normalize(x) for x in lot.splitlines()]
        for number in numbers:
            place,sep,remaining=remaining.partition(number)
            if not sep or not place:break
            places.append(place)
        if len(places)==len(numbers) and not remaining:
            change(data['building']['location'],'value','\n'.join(places),'地番','複数所在地と対応地番の明示文字列を分離')
    if loc and lot and '\n' not in lot and normalize(loc).endswith(normalize(lot)):
        change(data['building']['location'],'value',normalize(loc)[:-len(normalize(lot))],'地番','一棟の所在から地番を分離')
    if data['unit']['house_number']['value']:
        data['main_building']=blank(API_SCHEMA['properties']['main_building'])
        exists=data['land_right']['exists']['value'];kind=data['land_right']['type']['value']
        pt='leasehold_condominium' if kind in ('地上権','賃借権') else 'condominium_land_right' if exists is True else 'condominium_no_land_right' if exists is False else 'unknown'
        data['property_type']={'value':pt,'sources':copy.deepcopy(data['unit']['house_number']['sources']),'needs_review':pt=='unknown'}
        if kind in ('地上権','賃借権'):
            data['tenure_type']={'value':'leasehold','sources':copy.deepcopy(data['land_right']['type']['sources']),'needs_review':False}
    if not data['owners'] and data['owner']['name']['value']:
        names=data['owner']['name']['value'].splitlines();addresses=(data['owner']['address']['value'] or '').splitlines()
        if len(names)==len(addresses):
            data['owners']=[{'name':{**data['owner']['name'],'value':n},'address':{**data['owner']['address'],'value':a},'share':f(),'corporate_number':f(),'rank':f()} for n,a in zip(names,addresses)]
    data['metadata']={'source_pdf':source_pdf,'reviewed_input':reviewed,'full_text':full_text}
    for _,node in fields(data):
        node.setdefault('needs_review',False)
    for path,node in fields(data):
        if 'share' in path and isinstance(node['value'],str) and fraction(node['value']):
            n,d=fraction(node['value']);node['value']=f'{d}分の{n}'
        for s in node['sources']:s['source_pdf']=source_pdf
    return data


def ownership_ledger(rows):
    current={};uncertain=False
    for row in rows:
        purpose=normalize(row['columns'][1]);people=parse_owners(row)
        if purpose in ('所有権移転','所有権保存','共有者全員持分全部移転','合併による所有権登記'):
            current={}
        if '持分全部移転' in purpose:
            prefix=purpose.split('持分全部移転')[0]
            for name in list(current):
                if name in prefix:del current[name]
        if '持分一部移転' in purpose:
            prefix=purpose.split('持分一部移転')[0]
            for name in current:
                if name in prefix:current[name]['share']['needs_review']=True;uncertain=True
        if '住所変更' in purpose or '表示変更' in purpose:
            text=normalize(row['columns'][3])
            for name,person in current.items():
                m=re.search(re.escape(name)+r'の住所(.+?)(?:順位|$)',text)
                if m:person['address']=rf(m[1],row,3)
            continue
        if '抹消' in purpose or '更正' in purpose or '仮登記' in purpose:
            uncertain=True;continue
        if '移転' in purpose or '所有権' in purpose:
            for person in people:
                name=person['name']['value']
                if name in current:person['share']['needs_review']=True;uncertain=True
                current[name]=person
    # Full shared-owner completeness cannot be asserted when surviving shares
    # fail to total exactly one, or unreadable transfers were encountered.
    total=Fraction(0)
    for p in current.values():
        pair=fraction(p['share']['value'])
        if not pair:uncertain=True
        else:total+=Fraction(*pair)
    if total!=1:uncertain=True
    if uncertain:
        for p in current.values():p['needs_review']=True
    return list(current.values()),uncertain


def parse_owners(row):
    lines=[normalize(x) for x in row['fragments'][3]];persons=[];address='';share=None;name=''
    for line in lines:
        if line.startswith(('原因','順位','会社法人等番号','持分')):
            if line.startswith('持分'):share=line.removeprefix('持分')
            elif line.startswith('会社法人等番号') and persons:persons[-1]['corporate_number']=f(line.removeprefix('会社法人等番号'),row['page'],line)
            continue
        if line in ('共有者','所有者'):continue
        line=re.sub(r'^(?:所有者|共有者)','',line)
        if fraction(line):share=line;continue
        if re.search(r'(都|道|府|県|市|区|町|村)',line) and not line.startswith(('株式会社','有限会社','合同会社')):
            address=line;continue
        if address and not any(x in line for x in ('相続','売買','移記','第','規定')) and line:
            if re.fullmatch(r'[\d番地号丁目－-]+',line):address+=line;continue
            persons.append({'name':f(line,row['page'],line),'address':f(address,row['page'],address),'share':f(share,row['page'],share or ''),'rank':f(normalize(row['columns'][0]),row['page'],row['columns'][0]),'corporate_number':f()})
            address='';share=None
    for person in persons:
        for key,node in person.items():
            if node['value'] is not None and key!='rank':node['sources']=rf(node['value'],row,3)['sources']
    return persons


def parse_mortgages(rows):
    result=[]
    for r in rows:
        c=[normalize(x) for x in r['columns']]
        if '抵当権設定' not in c[1]:continue
        rank=c[0];simple=bool(re.fullmatch(r'\d+',rank))
        item={k:f() for k in ('rank','kind','amount','debtor','creditor','active','cancellation','registration_date','registration_number')}
        item['rank']=rf(rank,r,0); item['kind']=rf(c[1],r,1)
        amount=re.search(r'(?:債権額|極度額)(金.*?円)',c[3])
        if amount:item['amount']=rf(amount[1],r,3)
        for key,start,end in [('debtor','債務者','(?:根)?抵当権者'),('creditor','(?:根)?抵当権者','共同担保|順位|$')]:
            match=re.search(start+'(.+?)(?='+end+')',c[3])
            if match:item[key]=rf(match[1],r,3)
        for key,pattern in [('registration_date',r'(?:明治|大正|昭和|平成|令和)\d+年\d+月\d+日'),('registration_number',r'第\d+号')]:
            m=re.search(pattern,c[2])
            if m:item[key]=f(m[0],r['page'],r['columns'][2])
        cancels=[]
        if simple:
            for later in rows:
                purpose=normalize(later['columns'][1])
                m=re.fullmatch(r'([\d、・及び番]+)番(?:(?:根)?抵当権|仮登記)抹消',purpose)
                if m and rank in re.findall(r'\d+',m[1]):cancels.append(later)
        ambiguous=not simple or any(re.match(re.escape(rank)+r'番',normalize(later['columns'][1])) and any(w in normalize(later['columns'][1]) for w in ('変更','移転','更正','一部抹消')) for later in rows)
        item['active']=f(False,cancels[-1]['page'],cancels[-1]['columns'][1]) if cancels else rf(True,r,1) if not ambiguous else f(None,review=True)
        if cancels:item['cancellation']=f(normalize(cancels[-1]['columns'][2]),cancels[-1]['page'],cancels[-1]['columns'][2])
        # Apply explicitly addressed amendment amounts even when the overall
        # nested right state still requires review.
        reference=re.sub(r'^(\d+)',r'\1番',rank)
        if not re.search(r'[\ue000-\uf8ff]',reference):
            for later in rows:
                purpose=normalize(later['columns'][1]);body=normalize(later['columns'][3])
                if purpose.startswith(reference) and '変更' in purpose:
                    amount=re.search(r'(?:債権額|極度額)(金.*?円)',body)
                    if amount:item['amount']=rf(amount[1],later,3)
        # No explicit cancellation is insufficient for nested or unreadable ranks.
        item['needs_review']=ambiguous and not bool(cancels)
        result.append(item)
    return result
