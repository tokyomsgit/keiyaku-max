"""Building-scoped payload; no implicit property matching or master overwrite."""
import re
import uuid
from management_rules_schema import normalize
from supabase_store import StoreError


def make_payload(data,building_id,case_id):
    checked=normalize(data);source=checked.pop('source',{})
    if not re.fullmatch('[a-f0-9]{64}',source.get('file_hash','')):raise StoreError('原本情報を確認してください。')
    return {'building_id':str(uuid.UUID(building_id)),'case_id':str(uuid.UUID(case_id)),
        'source':{k:source.get(k) for k in ('file_hash','original_filename','storage_path')},
        'raw_json':checked,'source_type':'seller_provided','status':'provisional'}
