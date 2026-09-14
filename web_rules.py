"""Management rules use the selected case's building, never a name lookup."""
import copy
import hashlib
import json
from pathlib import Path
from web_data import ROOT, StoreError, field_view, env
from management_rules_schema import MAPPING, normalize
from important_report_schema import compact


def cached(digest,output):
    roots=[output/'rules_cache',ROOT.parent/'verification_rules/cache']
    if env('MANAGEMENT_RULES_CACHE_DIR'):roots.insert(0,Path(env('MANAGEMENT_RULES_CACHE_DIR')))
    for root in roots:
        path=root/digest/'extracted_normalized.json'
        if path.is_file():
            data=json.loads(path.read_text(encoding='utf8'))
            if data.get('source',{}).get('file_hash')==digest and data.get('is_management_rules') is True:return normalize(data)
    return None


def prepare(workspace,filename,content):
    digest=hashlib.sha256(content).hexdigest();data=cached(digest,workspace.output)
    if data is None and workspace.demo:raise StoreError('未解析の管理規約です。デモモードではAI解析せず停止します。')
    folder=workspace.output/'rules_cache'/digest;folder.mkdir(parents=True,exist_ok=True)
    pdf=folder/'source.pdf';pdf.write_bytes(content)
    reused=data is not None
    if data is None:
        from management_rules_reader import read_rules
        def count():workspace.ai_calls+=1
        data=read_rules(pdf,workspace.output/'rules_cache',on_api=count)
    data=copy.deepcopy(data);data['source'].update(original_filename=filename,storage_path=str(pdf.resolve()))
    (folder/'extracted_normalized.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    return data,reused


def attach(workspace,cid,data):
    case=workspace.case(cid);digest=data['source']['file_hash'];vid='local-rules-'+digest
    if any(d['version_id']==vid for d in case['documents']):return
    fields=[]
    for code,item in data['fields'].items():
        f=field_view(code,item);f.update(label=MAPPING[code]['label'],excel_supported=False,approved=False);fields.append(f)
    case['documents'].append({'id':vid,'version_id':vid,'type':'management_rules','filename':data['source']['original_filename'],
        'version':1,'date':None,'fields':fields})


def upload(workspace,cid,files):
    case=workspace.case(cid)
    if workspace.remote and (not case.get('building_id') or cid.startswith(('unit-','upload-'))):
        raise StoreError('先に案件登録を完了してください。')
    reused=0
    for filename,content in files:
        filename=filename.replace('\\','/').rsplit('/',1)[-1]
        if not filename.lower().endswith('.pdf') or not content.startswith(b'%PDF-'):raise StoreError('PDFを選択してください。')
        data,hit=prepare(workspace,filename,content);reused+=hit
        named=data.get('building_name')
        if named and compact(named)!=compact(case.get('building_name')):
            raise StoreError('規約の建物名が案件と一致しません。別の建物への保存を停止しました。原本と案件を確認してください。')
        if workspace.remote:
            from management_rules_store import make_payload
            workspace.rpc('rpc/save_management_rules',make_payload(data,case['building_id'],cid),write=True)
        else:
            attach(workspace,cid,data)
            folder=workspace.output/'rules_imports'/hashlib.sha256(cid.encode()).hexdigest();folder.mkdir(parents=True,exist_ok=True)
            (folder/(data['source']['file_hash']+'.json')).write_text(json.dumps({'case_id':cid,'data':data},ensure_ascii=False),encoding='utf8')
    if workspace.remote:
        if case.get('purchase_baseline'):workspace.rpc('rpc/web_sync_purchase_diffs',{'case_id':cid},write=True)
        workspace.refresh()
    return {'state':workspace.public(),'case_id':cid,'reused':reused}


def restore(workspace):
    for path in (workspace.output/'rules_imports').glob('*/*.json'):
        try:
            record=json.loads(path.read_text(encoding='utf8'));attach(workspace,record['case_id'],record['data'])
        except (OSError,ValueError,KeyError,StoreError):continue


def conflicts(case):
    """Different wording is a review candidate, never an automatic precedence decision."""
    latest={}
    for d in sorted(case['documents'],key=lambda d:(d.get('date') or '',d.get('version') or 0)):
        if d['type'] not in ('important_report','management_rules'):continue
        for f in d['fields']:latest[d['type'],f['code']]=(d,f)
    pairs={'pet_restrictions':'pet_restrictions','instrument_restrictions':'instrument_restrictions',
        'renovation_restrictions':'renovation_restrictions','parking_rules':'parking_facility_info',
        'office_use_allowed':'business_minpaku_restrictions','leasing_restrictions':'leasing_restrictions'}
    found=[]
    for code,other in pairs.items():
        rules=latest.get(('management_rules',code));report=latest.get(('important_report',other))
        if not rules or not report:continue
        rd,rf=rules;hd,hf=report
        if rf.get('value') is None or hf.get('value') is None or compact(rf['value'])==compact(hf['value']):continue
        found.append({'code':code,'label':MAPPING[code]['label'],'rules_value':rf['value'],'report_value':hf['value'],
            'rules_document':rd['filename'],'report_document':hd['filename'],'reason':'重調と管理規約の記載が異なります。規約原本を優先して条件・適用日を確認してください。'})
    return found
