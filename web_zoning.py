"""Zoning/city-planning reference PDFs. Building-level, append-only reference data:
no diff/versioning yet (unlike registry/report/rules), stored as a single JSON value
so a future version can add proper per-zone review without a schema change."""
import copy
import hashlib
import json
from pathlib import Path
from web_data import StoreError, env, ROOT
from web_reading import read_existing
from zoning_reader import ZONE_FIELDS


def cached(digest, output):
    roots = [output / 'zoning_cache']
    if env('ZONING_CACHE_DIR'):roots.insert(0, Path(env('ZONING_CACHE_DIR')))
    for root in roots:
        path = root / digest / 'extracted_normalized.json'
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding='utf8'))
                # A "needs_ai" result is only the cost-estimate pass's preview, not a final
                # read (web_ai_cost.prepare() writes it before AI consent exists), so it must
                # not short-circuit the later real read once consent is given.
                if data.get('source', {}).get('file_hash') == digest and data.get('status') != 'needs_ai':return data
            except (OSError, ValueError):continue
    return None


def prepare(workspace, filename, content):
    """Local-first: the text-layer reader is free and, on the sample formats it
    recognizes, already confident (needs_review=False per field). Only a page with
    no usable text layer costs an AI call, and only for that one document."""
    from zoning_reader import read_zoning, read_zoning_ai
    digest = hashlib.sha256(content).hexdigest()
    data = cached(digest, workspace.output)
    folder = workspace.output / 'zoning_cache' / digest
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / 'source.pdf'
    pdf.write_bytes(content)
    reused = data is not None
    if data is None:
        local = read_existing(read_zoning, pdf)
        if local['status'] == 'needs_ai':
            if workspace.demo:raise StoreError('未解析の用途地域資料です。デモモードではAI解析せず停止します。')
            from web_ai_cost import permit
            permit(workspace, 'zoning', pdf)
            workspace.ai_calls += 1
            data = read_existing(read_zoning_ai, pdf)
        else:
            data = local
            data.setdefault('source', {})['file_hash'] = digest
    data = copy.deepcopy(data)
    data['source'] = {**data.get('source', {}), 'original_filename': filename, 'storage_path': str(pdf.resolve()), 'file_hash': digest}
    (folder / 'extracted_normalized.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf8')
    return data, reused


def zone_view(data):
    """A flat, display-ready zones list: each zone's fields as plain value/page/text/needs_review."""
    from zoning_reader import LABELS
    zones = data.get('zones') or ([data['fields']] if data.get('fields') else [])
    return [{'zone_label': z.get('zone_label'), 'needs_review': z.get('needs_review', True),
        'fields': [{'code': c, 'label': LABELS.get(c, c), **v} for c, v in z.items() if c not in ('zone_label', 'needs_review') and isinstance(v, dict)]}
        for z in zones]


# 用途地域が3つ・稀に4つに跨る実例があるため、対応レターもここまで。契約書側の建ぺい率・容積率・
# 高度地区など一部項目はシートの枠(3件/2件)を超えると自動反映できず、手入力の案内に切り替わる
# （netlify/functions/generate.mjs の overflowNote 参照）。
ZONE_LETTERS = ('A', 'B', 'C', 'D')


def _latest_version(workspace, document_id):
    versions = workspace.rest(f'document_versions?document_id=eq.{document_id}&select=document_version_id,version_no,as_of_date,original_filename&order=version_no.desc&limit=1')
    if not versions:return None
    values = workspace.rest(f"extracted_values?document_version_id=eq.{versions[0]['document_version_id']}&field_code=eq.zoning_info&select=value")
    versions[0]['zones'] = (values[0]['value'] if values else []) or []
    return versions[0]


def seed_from_purchase(workspace, building_id, fields, source_label):
    """A 重要事項説明書 must legally state 法令上の制限 (用途地域 etc.), so the purchase-
    disclosure reader can often capture it even with no dedicated 用途地域資料 uploaded yet.
    Called once, right after a purchase-disclosure registers a building. Only ever creates
    a FIRST zoning document — if one already exists (a real dedicated PDF, or an earlier
    seed), this is a no-op, since a purpose-built reading should never be replaced by a
    weaker one extracted incidentally from a different document. Always needs_review=True
    per field, matching read_zoning_ai()'s AI-vision convention: this is a general-purpose
    document being asked about a specific section, not a dedicated certificate reader."""
    if not building_id or not fields:return
    zone = {code: {'value': item['value'], 'page_no': item.get('page_no'), 'source_text': item.get('source_text'), 'needs_review': True}
        for code, item in fields.items() if code in ZONE_FIELDS and item.get('value') not in (None, '')}
    if not zone:return
    try:
        if workspace.rest(f'documents?document_type=eq.zoning&building_id=eq.{building_id}&unit_id=is.null&select=document_id'):return
        created = workspace.rest('documents', {'document_type': 'zoning', 'building_id': building_id, 'title': '用途地域資料'}, 'POST', write=True)
        version = workspace.rest('document_versions', {'document_id': created[0]['document_id'], 'version_no': 1,
            'source_type': 'historical_purchase_document', 'status': 'provisional', 'original_filename': source_label}, 'POST', write=True)
        zones = [{**zone, 'zone_label': None, 'needs_review': True, 'source_filename': source_label}]
        workspace.rest('extracted_values', {'document_version_id': version[0]['document_version_id'], 'field_code': 'zoning_info',
            'value': zones, 'confidence': None, 'page_no': 1, 'source_text': source_label,
            'reviewed': False, 'approved': False}, 'POST', write=True)
    except StoreError:pass


def attach_snapshot(workspace, case, building_id):
    """web_workspace_snapshot's RPC doesn't cover document_type='zoning' (a small,
    unversioned RPC I can't redeploy here), so this fetches it directly."""
    if not building_id:return
    try:
        rows = workspace.rest(f'documents?document_type=eq.zoning&building_id=eq.{building_id}&select=document_id')
        if not rows:return
        versions = workspace.rest(f"document_versions?document_id=eq.{rows[0]['document_id']}&select=document_version_id,original_filename,as_of_date&order=version_no.desc&limit=1")
        if not versions:return
        values = workspace.rest(f"extracted_values?document_version_id=eq.{versions[0]['document_version_id']}&field_code=eq.zoning_info&select=value,confidence,reviewed")
        if not values:return
        case['zoning'] = {'filename': versions[0]['original_filename'], 'as_of_date': versions[0]['as_of_date'],
            'reviewed': bool(values[0]['reviewed']), 'zones': values[0]['value'] or []}
    except StoreError:pass


def upload(workspace, cid, files):
    """A multi-zone property (用途境あり) normally arrives as separate single-zone PDF
    certificates rather than one document describing both zones, so each file here is
    read on its own and the results are merged (by file hash, so a retry/re-upload of
    the same PDF is a no-op) into the building's one zoning document. Order is upload
    order by default and only matters for which letter (A)/(B)/(C) a zone gets in the
    Excel — see generate.mjs's array-position-based lettering — so the case screen lets
    the user fix it afterwards via zoning.mjs's reorder action rather than guessing."""
    case = workspace.case(cid)
    building_id = case.get('building_id')
    if not building_id:raise StoreError('この案件は建物と紐付いていません。先に案件登録を完了してください。')
    if not 1 <= len(files) <= len(ZONE_LETTERS):raise StoreError(f'用途地域資料は1〜{len(ZONE_LETTERS)}件選択してください。')
    parsed = []
    for filename, content in files:
        filename = filename.replace('\\', '/').rsplit('/', 1)[-1]
        if not filename.lower().endswith('.pdf') or not content.startswith(b'%PDF-'):raise StoreError('PDFを選択してください。')
        data, reused = prepare(workspace, filename, content)
        parsed.append((filename, data, reused))
    if not workspace.remote:
        return {'state': workspace.public(), 'case_id': cid, 'reused': all(reused for _, _, reused in parsed)}
    documents = workspace.rest(f'documents?document_type=eq.zoning&building_id=eq.{building_id}&unit_id=is.null&select=document_id')
    if documents:
        document_id = documents[0]['document_id']
        latest = _latest_version(workspace, document_id)
    else:
        created = workspace.rest('documents', {'document_type': 'zoning', 'building_id': building_id, 'title': '用途地域資料'}, 'POST', write=True)
        document_id = created[0]['document_id']
        latest = None
    existing_zones = latest['zones'] if latest else []
    existing_hashes = {z.get('file_hash') for z in existing_zones if z.get('file_hash')}
    new_zones, new_filenames = [], []
    for filename, data, _ in parsed:
        digest = data['source']['file_hash']
        if digest in existing_hashes:continue
        for zone in zone_view(data):new_zones.append({**zone, 'file_hash': digest, 'source_filename': filename})
        new_filenames.append(filename)
    if not new_zones:
        return {'state': workspace.public(), 'case_id': cid, 'reused': True}
    zones = existing_zones + new_zones
    if len(zones) > len(ZONE_LETTERS):raise StoreError(f'用途地域資料は建物ごとに最大{len(ZONE_LETTERS)}件までです。')
    used_letters = {z.get('zone_label') for z in existing_zones if z.get('zone_label') in ZONE_LETTERS}
    for zone in new_zones:
        if zone.get('zone_label') not in ZONE_LETTERS:
            letter = next(l for l in ZONE_LETTERS if l not in used_letters)
            zone['zone_label'] = letter;used_letters.add(letter)
    version_no = (latest['version_no'] + 1) if latest else 1
    filenames = [z.get('source_filename') for z in zones if z.get('source_filename')]
    combined_filename = '／'.join(filenames) if filenames else (latest or {}).get('original_filename') or new_filenames[0]
    version_payload = {'document_id': document_id, 'version_no': version_no, 'source_type': 'seller_provided',
        'status': 'provisional', 'original_filename': combined_filename,
        'file_hash': hashlib.sha256('|'.join(sorted(z['file_hash'] for z in zones if z.get('file_hash'))).encode()).hexdigest()}
    as_of_dates = sorted(d for _, data, _ in parsed if (d := data.get('fields', {}).get('reference_date', {}).get('value')))
    if as_of_dates:version_payload['as_of_date'] = as_of_dates[-1]
    elif latest and latest.get('as_of_date'):version_payload['as_of_date'] = latest['as_of_date']
    version = workspace.rest('document_versions', version_payload, 'POST', write=True)
    version_id = version[0]['document_version_id']
    confident = bool(zones) and not any(z.get('needs_review', True) for z in zones)
    summary = '／'.join(f"({z.get('zone_label') or chr(65 + i)})" for i, z in enumerate(zones)) if len(zones) > 1 else combined_filename
    workspace.rest('extracted_values', {'document_version_id': version_id, 'field_code': 'zoning_info',
        'value': zones, 'confidence': 1.0 if confident else None, 'page_no': 1,
        'source_text': f'{summary}（{len(zones)}区域）' if len(zones) > 1 else summary,
        'reviewed': confident, 'approved': confident}, 'POST', write=True)
    workspace.refresh()
    return {'state': workspace.public(), 'case_id': cid, 'reused': False}
