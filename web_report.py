"""Case-scoped report upload. Reuses the existing reader and transactional store."""
import copy
import hashlib
import json
from pathlib import Path

from web_data import ROOT, StoreError, field_view, env


def cached_report(digest, output):
    roots = [output/'report_cache', ROOT.parent/'verification_important/cache']
    configured = env('IMPORTANT_REPORT_CACHE_DIR')
    if configured:
        roots.insert(0, Path(configured))
    for root in roots:
        path = root/digest/'extracted_normalized.json'
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if data.get('source', {}).get('file_hash') == digest and data.get('is_important_report') is True:
                return data
        except (OSError, ValueError, AttributeError):
            continue
    return None


def attach(workspace, cid, data):
    c = workspace.case(cid)
    digest = data['source']['file_hash']
    vid = 'local-report-' + digest
    if any(d['version_id'] == vid or d.get('file_hash') == digest for d in c['documents']):
        return
    # Keep approved baseline values intact. New readings are review candidates only.
    values = []
    previous = {f['code']: f for d in c['documents'] if d['type'] == 'important_report' for f in d['fields']}
    for code, item in data['fields'].items():
        f = field_view(code, item)
        f['approved'] = False
        values.append(f)
        old = previous.get(code)
        if old and old.get('value') != f.get('value') and f.get('value') is not None:
            c['diffs'].append({'id': vid+'-'+code, 'code':code, 'label':f['label'],
                'old_value':copy.deepcopy(old.get('value')), 'new_value':copy.deepcopy(f['value']),
                'review_status':'unreviewed', 'can_adopt':False,
                'source':'ローカル読取候補です。確定値への採用はDB保存後に行ってください。'})
    c['documents'].append({'id':vid, 'version_id':vid, 'type':'important_report',
        'filename':data['source']['original_filename'], 'file_hash':digest, 'version':1, 'date':None, 'fields':values})


def restore(workspace):
    for path in (workspace.output/'report_imports').glob('*/*.json'):
        try:
            record = json.loads(path.read_text(encoding='utf8'))
            attach(workspace, record['case_id'], record['data'])
        except (OSError, ValueError, KeyError, StoreError):
            continue


def upload(workspace, cid, files):
    case = workspace.case(cid)  # Validate the selected case before any AI/DB operation.
    if not 1 <= len(files) <= 12:
        raise StoreError('重調PDFは1〜12件選択してください。')
    if workspace.remote and not case.get('unit_id'):
        raise StoreError('この取込案件はDB未登録です。DB登録済みの案件を選択してください。')
    records = []; seen = set()
    for filename, content in files:
        filename = filename.replace('\\','/').rsplit('/',1)[-1]
        if len(filename)>200 or not filename.lower().endswith('.pdf') or not content.startswith(b'%PDF-'):
            raise StoreError('PDFファイルを選択してください。')
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        data = cached_report(digest, workspace.output)
        if data is None and workspace.demo:
            raise StoreError('未解析の重調PDFです。デモモードではAI解析せず停止しました。')
        records.append((filename, content, digest, data))
    reused = 0
    for filename, content, digest, data in records:
        folder = workspace.output/'report_cache'/digest
        folder.mkdir(parents=True, exist_ok=True)
        pdf = folder/'source.pdf'
        pdf.write_bytes(content)
        if data is None:
            from important_report_reader import read_report
            workspace.ai_calls += 1
            data = read_report(pdf, workspace.output/'report_cache')
        else:
            reused += 1
        data = copy.deepcopy(data)
        data['source'].update(original_filename=filename, storage_path=str(pdf.resolve()))
        (folder/'extracted_normalized.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        if workspace.remote:
            from important_report_store import make_payload
            house=data.get('house_number')
            known=workspace.raw.get(cid,{}).get('unit',{}).get('house_number') if hasattr(workspace,'raw') else None
            if house and known and house!=known:raise StoreError('重調の家屋番号が案件と一致しません。別住戸への保存を停止しました。')
            payload = make_payload(data, unit_id=case['unit_id'])
            result = workspace.rpc('rpc/save_important_report', payload, write=True)
            if not isinstance(result,dict) or not result.get('document_version_id'):
                raise StoreError('重調の保存を確認できませんでした。再読込してください。')
        else:
            # Case ids never become filesystem paths.
            key = hashlib.sha256(cid.encode('utf8')).hexdigest()
            target = workspace.output/'report_imports'/key
            target.mkdir(parents=True, exist_ok=True)
            (target/(digest+'.json')).write_text(json.dumps({'case_id':cid,'data':data},ensure_ascii=False),encoding='utf8')
            attach(workspace, cid, data)
    if workspace.remote:
        if case.get('purchase_baseline'):workspace.rpc('rpc/web_sync_purchase_diffs',{'case_id':cid},write=True)
        workspace.refresh()
    return {'state':workspace.public(), 'case_id':cid, 'reused':reused}
