"""Mixed uploads stage additional documents until explicit case registration."""
import hashlib
import json
from pathlib import Path
from web_data import StoreError


def queue_path(w,source_id):
    return w.output/'pending_documents'/(hashlib.sha256(source_id.encode()).hexdigest()+'.json')


def save_queue(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8');tmp.replace(path)


def pending(w,cid):
    records=[]
    for path in (w.output/'pending_documents').glob('*.json'):
        record=json.loads(path.read_text(encoding='utf8'))
        if record.get('case_id')==cid or record.get('source_id')==cid:records.append((path,record))
    return records


def pending_names(w,cid):
    return [{'filename':f['name'],'kind':f['kind']} for _,r in pending(w,cid) for f in r['files'] if not f.get('saved')]


def flush(w,source_id,cid):
    warning=None
    for path,r in pending(w,source_id):
        r['case_id']=cid;save_queue(path,r)
        for f in r['files']:
            if f.get('saved'):continue
            try:
                pdf=Path(f['path']);content=pdf.read_bytes()
                if hashlib.sha256(content).hexdigest()!=f['hash']:raise StoreError('保存済みPDFが変更されています。再選択してください。')
                if f['kind']=='rules':from web_rules import upload
                else:from web_report import upload
                upload(w,cid,[(f['name'],content)]);f['saved']=True;save_queue(path,r)
            except (StoreError,OSError,ValueError) as e:
                warning='案件登録は完了していますが、追加資料は未保存です。資料を確認して保存を再実行してください。 '+(str(e) if isinstance(e,StoreError) else '')
                break
    return warning


def upload(w,cid,files):
    if not 1<=len(files)<=12 or any(k not in ('registry','report','rules') for k,_,_ in files):raise StoreError('各PDFの資料種類を選択してください。')
    if len({hashlib.sha256(v).hexdigest() for _,_,v in files})!=len(files):raise StoreError('同じPDFが複数選択されています。1件にしてください。')
    for _,name,content in files:
        if not name.lower().endswith('.pdf') or not content.startswith(b'%PDF-'):raise StoreError('PDFを選択してください。')
    registry=[(n,v) for k,n,v in files if k=='registry']
    if registry:
        from web_registry import upload as registry_upload
        result=registry_upload(w,registry);cid=result['case_id']
    elif cid:w.case(cid)
    else:raise StoreError('新規案件には建物・土地謄本を選択してください。')
    path=queue_path(w,cid);record=json.loads(path.read_text(encoding='utf8')) if path.exists() else {'source_id':cid,'case_id':None,'files':[]}
    # A fresh upload of the same registry set must be confirmed again before attaching documents.
    if registry:record['case_id']=None
    for kind,name,content in files:
        if kind=='registry':continue
        name=name.replace('\\','/').rsplit('/',1)[-1];digest=hashlib.sha256(content).hexdigest()
        folder=w.output/('rules_cache' if kind=='rules' else 'report_cache')/digest;folder.mkdir(parents=True,exist_ok=True)
        pdf=folder/'source.pdf';pdf.write_bytes(content)
        if not any(f['hash']==digest for f in record['files']):record['files'].append({'kind':kind,'name':name,'path':str(pdf.resolve()),'hash':digest,'saved':False})
    save_queue(path,record)
    warning=None
    # Reading is delayed until after registration, so ambiguous/unsupported cases consume no additional AI credits.
    if not w.remote or (not cid.startswith(('upload-','unit-')) and w.case(cid).get('unit_id')):warning=flush(w,cid,cid)
    return {'state':w.public(),'case_id':cid,'warning':warning}
