"""Cloud ingestion worker: runs the existing local readers for one queued job.

The job file lives in private storage. Output is intentionally silent because
Actions logs of this repository are public; only the job id and a coarse status
are printed.
"""
import datetime as dt
import hashlib
import io
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
KINDS = ('purchase', 'registry', 'report', 'rules')
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
CACHE_DIRS = ('registry_cache', 'report_cache', 'purchase_cache', 'rules_cache')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def classify(name, content):
    """Explicit document titles only. Unknown or conflicting signals are asked to the user."""
    from pypdf import PdfReader
    pages = []
    try:
        reader = PdfReader(io.BytesIO(content))
        for page in reader.pages[:3]:
            pages.append(re.sub(r'\s+', '', page.extract_text() or ''))
    except Exception:
        pages = []
    text = ''.join(pages)
    first = pages[0][:300] if pages else ''
    by_text = None
    if re.search(r'履歴事項全部証明書|現在事項全部証明書|商号', text):by_text = 'other'
    elif re.search(r'調査報告書|管理に係る.{0,3}重要事項', text):by_text = 'report'
    elif re.search(r'重要事項説明書', text):by_text = 'purchase'
    elif re.search(r'全部事項証明書|表題部|権利部[（(]甲区', text):by_text = 'registry'
    elif re.search(r'管理規約|使用細則', first) and re.search(r'第[1１一]条', text):by_text = 'rules'
    elif re.search(r'用途地域|都市計画', first):by_text = 'other'
    by_name = None
    if re.search(r'会社|商業|法人|委任状|依頼|申込|用途地域|長期修繕|図面|台帳', name):by_name = 'other'
    elif re.search(r'重調|調査報告', name):by_name = 'report'
    elif re.search(r'重説|重要事項説明', name):by_name = 'purchase'
    elif re.search(r'謄本|登記|全部事項', name):by_name = 'registry'
    elif re.search(r'規約|細則', name):by_name = 'rules'
    if by_text and by_name and by_text != by_name:
        return None
    kind = by_text or by_name
    return kind if kind in KINDS else None


def pack_cache(output, digest):
    stream = io.BytesIO()
    count = 0
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for folder in CACHE_DIRS:
            base = output / folder / digest
            if not base.is_dir():continue
            for path in base.rglob('*.json'):
                archive.write(path, path.relative_to(output).as_posix());count += 1
    return stream.getvalue() if count else None


def unpack_cache(output, digest, data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            parts = Path(name).parts
            if len(parts) < 3 or parts[0] not in CACHE_DIRS or parts[1] != digest or '..' in parts or not name.endswith('.json'):
                continue
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))


def batches(kinds, case_id):
    indexes = list(range(len(kinds)))
    if not case_id and 'purchase' in kinds and any(k != 'purchase' for k in kinds):
        return [[i for i in indexes if kinds[i] == 'purchase'], [i for i in indexes if kinds[i] != 'purchase']]
    return [indexes]


def candidate_view(match):
    items = []
    for c in match.get('candidates') or []:
        items.append({'id': c.get('unit_id') or c.get('building_id'), 'building_name': c.get('building_name'),
            'unit_name': c.get('unit_name'), 'house_number': c.get('house_number'),
            'registry_location': c.get('registry_location')})
    return items


def process(job, storage, work):
    os.environ['WEB_OUTPUT_DIR'] = str(work / 'output')
    os.environ.setdefault('REGISTRY_READER_ROOT', str(ROOT / 'reader'))
    from web_data import StoreError, Workspace
    output = work / 'output'
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for item in job['files']:
        digest = item['hash']
        content = storage.get('uploads/' + digest + '.pdf')
        if content is None:
            raise StoreError('アップロードが完了していないPDFがあります。もう一度追加してください。')
        if hashlib.sha256(content).hexdigest() != digest or not content.startswith(b'%PDF-'):
            raise StoreError('アップロードされたPDFの内容が一致しません。もう一度追加してください。')
        cached = storage.get('cache/' + digest + '.zip')
        if cached:unpack_cache(output, digest, cached)
        files.append((item['name'], content, digest))

    try:
        return read_files(job, files, output)
    finally:
        for _, _, digest in files:
            packed = pack_cache(output, digest)
            if packed:storage.put('cache/' + digest + '.zip', packed, 'application/zip')


def read_files(job, files, output):
    from web_data import Workspace
    chosen = job.get('kinds') or {}
    kinds = []
    unknown = []
    for name, content, digest in files:
        kind = chosen.get(digest) or classify(name, content)
        if kind == 'skip':
            kinds.append(None);continue
        if kind not in KINDS:
            unknown.append({'hash': digest, 'name': name})
        kinds.append(kind)
    if unknown:
        return {'status': 'needs_kind', 'message': '資料の種類を判定できなかったPDFがあります。種類を選んでください。', 'unknown': unknown}
    selected = [(k, n, c) for k, (n, c, _) in zip(kinds, files) if k]
    if not selected:
        return {'status': 'failed', 'message': '読み取る資料がありません。'}

    workspace = Workspace(demo=False)
    case_id = job.get('case_id')
    if case_id:workspace.case(case_id)
    from web_ai_cost import prepare, authorize
    plan = prepare(workspace, selected, case_id)
    if plan['blocked']:
        return {'status': 'failed', 'message': plan['warning'] or '自動読取を停止しました。'}
    if plan['ai_files'] and not job.get('ai_confirmed'):
        return {'status': 'needs_consent', 'estimate_jpy': plan['estimate_jpy'], 'ai_files': plan['ai_files'],
            'message': f"{plan['ai_files']}件のPDFは、正確に読み取るためAI解析が必要です。"}

    from web_documents import upload as upload_documents
    from web_registration import advance, choose_candidate
    warnings = []
    for group in batches([k for k in kinds if k], case_id):
        uploads = [selected[i] for i in group]
        authorize(workspace, plan['token'], uploads, True)
        result = advance(workspace, upload_documents(workspace, case_id, uploads))
        preview = result.get('registration_preview')
        if preview:
            match = preview['match']
            if match.get('status') == 'ambiguous':
                wanted = job.get('candidate_id')
                if not wanted:
                    return {'status': 'needs_candidate', 'message': match.get('reason') or '物件候補が複数あります。',
                        'candidates': candidate_view(match)}
                if wanted not in [c['id'] for c in candidate_view(match)]:
                    return {'status': 'needs_candidate', 'message': '候補が変わりました。もう一度選んでください。',
                        'candidates': candidate_view(match)}
                result = choose_candidate(workspace, preview['token'], wanted)
                if result.get('registration_preview'):
                    return {'status': 'failed', 'message': result.get('warning') or '案件を確定できませんでした。'}
            else:
                return {'status': 'failed', 'message': result.get('warning') or match.get('reason') or '物件を安全に特定できませんでした。'}
        case_id = result['case_id']
        if not re.fullmatch(UUID, case_id or ''):
            return {'status': 'failed', 'message': result.get('warning') or '案件登録を完了できませんでした。資料を確認してください。'}
        if result.get('warning'):warnings.append(result['warning'])
    return {'status': 'done', 'case_id': case_id, 'message': '読み取りが完了しました。', 'warnings': warnings,
        'ai_calls': workspace.ai_calls}


def main(job_id):
    if not re.fullmatch(UUID, job_id or ''):
        print('invalid job');return 2
    sys.path.insert(0, str(ROOT))
    from web_data import StoreError, load_env
    load_env()
    from cloud_storage import Storage
    storage = Storage()
    name = 'jobs/' + job_id + '.json'
    job = storage.get_json(name)
    if not job or job.get('status') not in ('queued',):
        print('job not queued');return 0
    job.update(status='running', message='資料を読み取っています。', updated_at=now())
    for key in ('candidates', 'unknown', 'estimate_jpy', 'ai_files', 'warnings'):job.pop(key, None)
    storage.put_json(name, job)
    with tempfile.TemporaryDirectory() as folder:
        try:
            outcome = process(job, storage, Path(folder))
        except StoreError as exc:
            outcome = {'status': 'failed', 'message': str(exc)}
        except Exception:
            outcome = {'status': 'failed', 'message': '読取処理を完了できませんでした。管理者へ連絡してください。'}
    job.update(outcome, updated_at=now(), runs=int(job.get('runs') or 0) + 1)
    storage.put_json(name, job)
    print('job', job_id, job['status'])
    return 0


if __name__ == '__main__':
    sys.exit(main(os.environ.get('JOB_ID') or (sys.argv[1] if len(sys.argv) > 1 else '')))
