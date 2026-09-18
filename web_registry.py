from web_reading import read_existing
"""Local upload adapter for the installed registry reader and cached results."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from web_data import ROOT,env,StoreError,field_view,LABELS


def reader_root():
    root=Path(env('REGISTRY_READER_ROOT') or ROOT.parent)
    if not (root/'extract_registry.py').is_file():raise StoreError('既存の謄本読取環境がありません。管理者へ連絡してください。')
    if str(root) not in sys.path:sys.path.insert(0,str(root))
    return root


def cached(digest,root,output):
    for stamp in (root/'verification_all/documents').glob('*/cache.json'):
        try:
            if json.loads(stamp.read_text(encoding='utf8')).get('sha256')==digest:
                return json.loads((stamp.parent/'normalized.json').read_text(encoding='utf8'))
        except (OSError,ValueError):continue
    path=output/'registry_cache'/digest/'extracted.json'
    if path.exists():
        data=json.loads(path.read_text(encoding='utf8'))
        if data.get('metadata',{}).get('source_sha256')==digest:return data
    return None


def get(data,path):
    for k in path.split('.'):data=data.get(k,{}) if isinstance(data,dict) else {}
    return data.get('value') if isinstance(data,dict) else None


def case_from(data,cid):
    mapping={'building_name':'building.name','registry_location':'building.location','building_structure':'building.structure',
      'floor_areas':'building.floor_areas','house_number':'unit.house_number','unit_name':'unit.name','unit_type':'unit.type',
      'unit_structure':'unit.structure','unit_floor':'unit.floor','registered_area':'unit.registered_area','built_date':'unit.built_date',
      'current_owner_name':'owner.name','current_owner_address':'owner.address','land_lots':'lands','has_land_right':'land_right.exists',
      'land_right_type':'land_right.type','land_right_share':'land_right.share','mortgages':'mortgages',
      'leasehold_area':'leasehold.area','leasehold_ground_rent_monthly':'leasehold.ground_rent_monthly',
      'leasehold_ground_rent_unit':'leasehold.ground_rent_unit_per_3_3sqm','leasehold_law_type':'leasehold.law_type',
      'leasehold_period_start':'leasehold.period_start','leasehold_period_end':'leasehold.period_end',
      'leasehold_period_years':'leasehold.period_years','leasehold_assignment_consent':'leasehold.assignment_consent_required'}
    values=[]
    for code,path in mapping.items():
        v=data
        for part in path.split('.'):v=v.get(part,{}) if isinstance(v,dict) else {}
        sources=[]
        def collect(node):
            if isinstance(node,dict):
                sources.extend(node.get('sources',[]))
                for k,x in node.items():
                    if k!='sources':collect(x)
            elif isinstance(node,list):
                for x in node:collect(x)
        collect(v)
        f=copy.deepcopy(v) if isinstance(v,dict) and 'value' in v else {'value':copy.deepcopy(v) if isinstance(v,list) else None}
        f.update(source_text='\n'.join(dict.fromkeys(x.get('text','') for x in sources)),page_no=sources[0].get('page') if sources else None)
        values.append(field_view(code,f))
    LABELS.update(mortgages='抵当権',land_right_share='敷地権の割合',leasehold_area='借地対象面積',
      leasehold_ground_rent_monthly='地代（月額）',leasehold_ground_rent_unit='地代（3.3㎡当たり月額）',
      leasehold_law_type='借地権の法区分',leasehold_period_start='借地期間開始',leasehold_period_end='借地期間終了',
      leasehold_period_years='借地期間',leasehold_assignment_consent='譲渡承諾の要否')
    for f in values:f['label']=LABELS.get(f['code'],f['code'])
    kind=get(data,'property_type');blocked=kind not in ('condominium_land_right','condominium_no_land_right','leasehold_condominium')
    warnings=list(data.get('group_review',[]))+list(data.get('leasehold_warnings',[]))+list(data.get('land_warnings',[]))
    if blocked:warnings.insert(0,'戸建ては区分マンション用ひな形の対象外です。' if kind=='detached_house' else '物件タイプを確定できないため、Excel生成を停止しました。')
    return {'id':cid,'unit_id':None,'building_name':get(data,'building.name') or '取込資料（物件名未取得）',
      'unit_name':get(data,'unit.name'),'address':get(data,'building.location'),'owner':get(data,'owner.name'),
      'area':get(data,'unit.registered_area'),'status':'対象外・要確認' if blocked else 'ローカル取込・DB未保存',
      'updated_at':None,'property_type':kind,'generation_blocked':blocked or bool(data.get('group_review')),
      'upload_warnings':warnings,'documents':[{'id':cid,'version_id':cid+'-v1','type':'registry','filename':'統合謄本（'+str(len(data.get('upload_filenames',[])))+'資料）','source_files':data.get('upload_filenames',[]),
      'version':1,'date':None,'fields':values}],'diffs':[]}


def restore(workspace):
    for path in (workspace.output/'imports').glob('*/integrated.json'):
        try:
            if workspace.remote and (path.parent/'registration.json').is_file():continue
            data=json.loads(path.read_text(encoding='utf8'));cid=path.parent.name
            case=case_from(data,cid);case['registration_required']=bool(workspace.remote)
            workspace.cases.append(case);workspace.raw[cid]={'uploaded':data}
        except (OSError,ValueError,KeyError):continue


def upload(workspace,files):
    root=reader_root()
    if not 1<=len(files)<=12:raise StoreError('PDFは1〜12件選択してください。')
    records=[];seen=set()
    for name,content in files:
        name=name.replace('\\','/').rsplit('/',1)[-1]
        if len(name)>200 or not name.lower().endswith('.pdf') or not content.startswith(b'%PDF-'):raise StoreError('PDFファイルを選択してください。')
        digest=hashlib.sha256(content).hexdigest()
        if digest in seen:continue
        seen.add(digest);data=cached(digest,root,workspace.output)
        if data is None and workspace.demo:raise StoreError('未解析のPDFです。デモモードではAI解析せず停止しました。解析済みサンプルを選択してください。')
        records.append([name,content,digest,data])
    from extract_registry import extract_registry
    from verify_all import integrate
    docs={};items=[];manifest=[]
    for i,(name,content,digest,data) in enumerate(records):
        folder=workspace.output/'registry_cache'/digest;folder.mkdir(parents=True,exist_ok=True)
        pdf=folder/'source.pdf';pdf.write_bytes(content)
        if data is None:
            from registry_text import is_service_pdf
            # 登記情報提供サービスのPDFは罫線表から読むので、APIキーも料金確認も要らない。
            if not is_service_pdf(pdf):
                key=env('OPENAI_API_KEY')
                if not key:raise StoreError('API設定不足：管理者がOPENAI_API_KEYを設定してください。')
                os.environ['OPENAI_API_KEY']=key
                from web_ai_cost import permit
                permit(workspace,'registry',pdf)
                workspace.ai_calls+=1
            data=read_existing(extract_registry,pdf,folder)
        docs[str(i)]=copy.deepcopy(data);docs[str(i)].setdefault('metadata',{})
        def tag(node):
            if isinstance(node,dict):
                for source in node.get('sources',[]):source.update(source_pdf=name,file_hash=digest)
                for key,child in node.items():
                    if key not in ('sources','metadata'):tag(child)
            elif isinstance(node,list):
                for child in node:tag(child)
        tag(docs[str(i)])
        manifest.append({'file_hash':digest,'original_filename':name,'storage_path':str(pdf.resolve())})
        items.append({'id':str(i),'path':name,'sha256':digest})
    data=integrate(items,docs);data['upload_filenames']=[r[0] for r in records]
    # Text-layer land registries can supply explicit leasehold terms locally.
    # This never derives a unit's total rent from the per-3.3㎡ registry rate.
    from leasehold_reader import read_land_registry
    for name,content,digest,_ in records:
        if not ('土地' in name or 'land' in name.lower()):continue
        pdf=workspace.output/'registry_cache'/digest/'source.pdf'
        try:local=read_land_registry(pdf)
        except (OSError,ValueError):continue
        lease=local.get('leasehold')
        if not lease:continue
        section=data.setdefault('leasehold',{})
        for key,value in lease.items():
            if key in section or value is None:continue
            section[key]={'value':value,'sources':[{'page':1,'text':'土地謄本の地上権・賃借権設定欄','source_pdf':name,'file_hash':digest}],
                          'needs_review':key in ('ground_rent_unit_per_3_3sqm','assignment_consent_required')}
        data.setdefault('leasehold_warnings',[]).extend(x for x in local.get('warnings',[]) if x not in data.get('leasehold_warnings',[]))
        current=get(data,'property_type');right=get(data,'land_right.type')
        if current in (None,'unknown') and right in ('地上権','賃借権'):
            source={'page':1,'text':'土地謄本の地上権・賃借権設定欄','source_pdf':name,'file_hash':digest}
            data['property_type']={'value':'leasehold_condominium','sources':[source],'needs_review':False}
    data['registration_documents']=manifest
    cid='upload-'+hashlib.sha256('|'.join(sorted(seen)).encode()).hexdigest()[:24]
    folder=workspace.output/'imports'/cid;folder.mkdir(parents=True,exist_ok=True)
    (folder/'integrated.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    workspace.cases=[c for c in workspace.cases if c['id']!=cid]
    case=case_from(data,cid);case['registration_required']=bool(workspace.remote)
    workspace.cases.append(case);workspace.raw[cid]={'uploaded':data}
    return {'state':workspace.public(),'case_id':cid,'reused':sum(r[3] is not None for r in records)}


def generate(workspace,cid):
    c=workspace.case(cid)
    if c.get('registration_required'):raise StoreError('登録前の確認を行い、「この案件で登録」を押してください。')
    if c.get('generation_blocked'):raise StoreError('対象外の物件、または資料間の要確認事項があるため自動生成を停止しました。')
    reader_root()
    from practical_contract import plan,workbook_sheets,patch_input,recache,shared_strings,verify,NS
    import xml.etree.ElementTree as ET
    import zipfile
    import re
    import uuid
    token=uuid.uuid4().hex;folder=workspace.output/token;folder.mkdir(parents=True)
    output=folder/'契約書_謄本入力済.xlsm'
    # Reuse the existing plan and package writer, preserving formulas in the
    # named official template even where the older template had plain inputs.
    raw=workspace.raw[cid];data=copy.deepcopy(raw['uploaded'])
    if raw.get('registered'):
        for code,path in {'current_owner_name':'owner.name','current_owner_address':'owner.address','registered_area':'unit.registered_area',
            'house_number':'unit.house_number','unit_name':'unit.name','unit_type':'unit.type','unit_structure':'unit.structure',
            'unit_floor':'unit.floor','built_date':'unit.built_date','has_land_right':'land_right.exists','land_right_type':'land_right.type'}.items():
            section,key=path.split('.');v=raw['unit'].get(code)
            if code=='built_date' and v:
                from web_registration import iso_date
                if iso_date(data.get(section,{}).get(key,{}).get('value'))==v:continue
                import datetime as dt
                actual=dt.date.fromisoformat(v)
                for era,start in [('令和',(2019,5,1)),('平成',(1989,1,8)),('昭和',(1926,12,25)),('大正',(1912,7,30)),('明治',(1868,9,8))]:
                    if actual>=dt.date(*start):
                        v=f'{era}{actual.year-start[0]+1}年{actual.month}月{actual.day}日';break
            # Use master values, not unapproved values from the incoming PDF.
            if v != data.get(section,{}).get(key,{}).get('value'):
                data.setdefault(section,{})[key]={'value':v,'sources':[],'needs_review':v is None}
        n,d=raw['unit'].get('land_right_numerator'),raw['unit'].get('land_right_denominator')
        if n is not None and d is not None:
            share={'value':f'{d}分の{n}','sources':[],'needs_review':False}
            data.setdefault('land_right',{})['share']=copy.deepcopy(share)
            for land in data.get('lands',[]):land['right_share']=copy.deepcopy(share)
    writes,review=plan(data)
    with zipfile.ZipFile(workspace.template) as src:
        parts={n:src.read(n) for n in src.namelist()};sheets=workbook_sheets(src);part=sheets['基本入力']
        xml=parts[part].decode('utf8');cells={c.get('r'):c for c in ET.fromstring(xml).findall('.//s:sheetData/s:row/s:c',NS)}
        applied=[]
        for w in writes:
            if w['cell'] not in cells:raise StoreError('ひな形の入力欄が一致しません。')
            if cells[w['cell']].find('s:f',NS) is not None:continue
            xml=patch_input(xml,w);applied.append(w)
        parts[part]=xml.encode('utf8');recache(parts,sheets,shared_strings(src))
        parts['xl/workbook.xml']=re.sub(r'<calcPr\b[^>]*/>', '<calcPr calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>',parts['xl/workbook.xml'].decode('utf8')).encode('utf8')
        candidate=folder/'candidate.xlsm'
        with zipfile.ZipFile(candidate,'x') as out:
            for item in src.infolist():out.writestr(item,parts[item.filename])
    checks=verify(workspace.template,candidate,applied)
    candidate.rename(output)
    report_count=0
    if raw.get('registered'):
        from important_report_store import write_named_excel
        report_output=folder/'with_report.xlsm'
        report=write_named_excel(output,report_output,raw.get('report_fields',{}))
        if report['output']:
            report_output.replace(output);report_count=len(report['written'])
    (folder/'verification.json').write_text(json.dumps(checks,ensure_ascii=False,default=str),encoding='utf8')
    workspace.files[token]=output
    return {'download':'/download/'+token,'filename':output.name,'registry_written':len(applied),
      'report_written':report_count,'warnings':review['review_items'],'unsupported':[],
      'message':'生成・再読込確認が完了しました。'}
