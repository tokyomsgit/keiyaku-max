"""Server-owned registration previews for normalized registry imports."""
import copy
import datetime as dt
import hashlib
import json
import secrets
import re
import unicodedata
from pathlib import Path

from web_data import StoreError, canonical, LABELS

PATHS = {
 'building_name':'building.name','registry_location':'building.location','building_structure':'building.structure',
 'floor_areas':'building.floor_areas','house_number':'unit.house_number','unit_name':'unit.name',
 'unit_type':'unit.type','unit_structure':'unit.structure','unit_floor':'unit.floor',
 'registered_area':'unit.registered_area','built_date':'unit.built_date','current_owner_name':'owner.name',
 'current_owner_address':'owner.address','has_land_right':'land_right.exists','land_right_type':'land_right.type',
 'land_lots':'lands','active_mortgages':'mortgages'}
BUILDING={'building_name','registry_location','building_structure','floor_areas','land_lots'}


def iso_date(v):
    if not isinstance(v,str):return None
    v=unicodedata.normalize('NFKC',v).replace(' ','').removesuffix('新築')
    try:return dt.date.fromisoformat(v).isoformat()
    except ValueError:pass
    eras={'明治':(1868,9,8),'大正':(1912,7,30),'昭和':(1926,12,25),'平成':(1989,1,8),'令和':(2019,5,1)}
    m=re.fullmatch(r'(明治|大正|昭和|平成|令和)(元|\d+)年(\d+)月(\d+)日',v)
    if not m:return None
    year=1 if m[2]=='元' else int(m[2]);start=dt.date(*eras[m[1]])
    try:actual=dt.date(start.year+year-1,int(m[3]),int(m[4]))
    except ValueError:return None
    next_start=next((dt.date(*s) for s in eras.values() if dt.date(*s)>start),None)
    return actual.isoformat() if year>0 and actual>=start and (next_start is None or actual<next_start) else None


def node_at(data,path):
    for part in path.split('.'):
        data=data.get(part,{}) if isinstance(data,dict) else {}
    return data


def value(node):
    if isinstance(node,dict):
        if 'value' in node:return copy.deepcopy(node['value'])
        return {k:value(v) for k,v in node.items() if k not in ('sources','needs_review','metadata')}
    if isinstance(node,list):return [value(v) for v in node]
    return node


def sources(node):
    if isinstance(node,list):return [s for x in node for s in sources(x)]
    if isinstance(node,dict):
        return copy.deepcopy(node.get('sources',[]))+[s for k,x in node.items() if k not in ('sources','metadata') for s in sources(x)]
    return []


def uncertain(node):
    if isinstance(node,list):return any(uncertain(v) for v in node)
    if isinstance(node,dict):
        if node.get('needs_review'):return True
        if node.get('confidence') is not None and node['confidence']<.85:return True
        return any(uncertain(v) for k,v in node.items() if k not in ('sources','metadata'))
    return False


def payload_from(data):
    kind=value(node_at(data,'property_type'))
    if kind not in ('condominium_land_right','condominium_no_land_right','leasehold_condominium') or data.get('group_review'):
        raise StoreError('戸建て・物件種別不明・資料間不一致は登録できません。資料を確認してください。')
    documents=copy.deepcopy(data.get('registration_documents',[]))
    if not documents:raise StoreError('原本情報がありません。PDFを再選択してください。解析済みデータは再利用します。')
    b={'property_type':kind};u={};fields=[]
    for code,path in PATHS.items():
        node=node_at(data,path);v=value(node);src=sources(node);review=uncertain(node)
        if code=='land_lots':
            v=[{'location':value(x.get('location')), 'lot_number':value(x.get('lot_number')),
                'land_category':value(x.get('category')), 'area':value(x.get('area'))} for x in data.get('lands',[])]
            review=any(uncertain(x.get(k,{})) for x in data.get('lands',[]) for k in ('location','lot_number','category','area'))
        if code=='active_mortgages':
            # Preserve all history in raw JSON, and only active rights in the master.
            v=[value(x) for x in data.get('mortgages',[]) if value(x.get('active')) is True]
            if any(value(x.get('active')) is None for x in data.get('mortgages',[])):review=True
        if code=='built_date' and v:
            v=iso_date(v)
            if v is None:review=True
        if v=={}:v=None
        item={'field_code':code,'value':v,'confidence':node.get('confidence') if isinstance(node,dict) else None,
            'source_text':'\n'.join(dict.fromkeys(s.get('text','') for s in src)),
            'page_no':src[0].get('page') if src else None,'needs_review':review,
            'provenance':{'path':path,'sources':src,'needs_review':review}}
        fields.append(item)
        if v is not None and not review:
            (b if code in BUILDING else u)[code]=v
    # DB stores a single share only when all parcels have the same confirmed share.
    shares=[]
    for land in data.get('lands',[]):
        n,d=land.get('share_numerator'),land.get('share_denominator')
        if value(n) is None or value(d) is None or uncertain(n) or uncertain(d):shares=[];break
        shares.append((value(n),value(d)))
    if shares and len(set(shares))==1:
        for code,v in zip(('land_right_numerator','land_right_denominator'),shares[0]):
            u[code]=v;src=sources(node_at(data,'land_right.share')) or sources(data['lands'][0].get('right_share'))
            fields.append({'field_code':code,'value':v,'confidence':None,'source_text':'\n'.join(s.get('text','') for s in src),
                'page_no':src[0].get('page') if src else None,'needs_review':False,
                'provenance':{'path':'land_right.share','sources':src,'needs_review':False}})
    hashes={d['file_hash'] for d in documents}
    for doc in documents:
        doc['values']=[]
        for f in fields:
            origins=f['provenance']['sources']
            relevant=[s for s in origins if s.get('file_hash')==doc['file_hash']]
            if relevant or (not origins and doc is documents[0]):
                item=copy.deepcopy(f)
                item['source_text']='\n'.join(dict.fromkeys(s.get('text','') for s in relevant))
                item['page_no']=relevant[0].get('page') if relevant else None
                doc['values'].append(item)
        doc.pop('raw',None)
    for f in fields:
        if any(s.get('file_hash') not in hashes for s in f['provenance']['sources']):
            raise StoreError('根拠資料とPDFの対応を確認してください。')
    raw=copy.deepcopy(data)
    return {'building':b,'unit':u,'fields':fields,'documents':documents,
        'raw_json':{'format':'normalized_registry_v1','integrated':raw},
        'file_set_hash':hashlib.sha256('|'.join(sorted(hashes)).encode()).hexdigest()}


def preview(workspace,cid):
    workspace.case(cid);data=workspace.raw[cid].get('uploaded') or workspace.raw[cid].get('purchase')
    if not data:raise StoreError('登録対象の取込案件を選択してください。')
    if data.get('is_purchase_explanation'):
        from web_purchase import payload as purchase_payload
        payload=purchase_payload(data)
    else:payload=payload_from(data)
    if not workspace.remote:
        return {'demo':True,'summary':summary(payload),'match':{'status':'demo','candidates':[],'cases':[]},
            'message':'デモモードではDB照合・登録を行いません。'}
    match=workspace.rpc('rpc/web_registry_match',payload)
    token=secrets.token_urlsafe(32)
    workspace.registration_pending=getattr(workspace,'registration_pending',{})
    workspace.registration_pending[token]={'cid':cid,'payload':payload,'match':match}
    return {'token':token,'summary':summary(payload),'match':match}


def summary(p):
    return {k:p['building'].get(k,p['unit'].get(k)) for k in ('building_name','unit_name','house_number','registry_location','current_owner_name')}


def register(workspace,token,case_mode,resume_case_id=None):
    if not workspace.remote:raise StoreError('デモモードではDB登録できません。')
    pending=getattr(workspace,'registration_pending',{}).get(token)
    if not pending:raise StoreError('登録前の照合をやり直してください。')
    if case_mode not in ('new','resume'):raise StoreError('新規案件か既存案件再開を選択してください。')
    if pending['match'].get('status') not in ('new','existing'):raise StoreError('候補を確定できません。要確認です。')
    if case_mode=='resume' and resume_case_id not in [x['case_id'] for x in pending['match'].get('cases',[])]:
        raise StoreError('再開する案件を確認してください。')
    p=copy.deepcopy(pending['payload'])
    p.update(expected_match=pending['match'],case_mode=case_mode,resume_case_id=resume_case_id,
        request_key=hashlib.sha256(token.encode()).hexdigest())
    result=workspace.rpc('rpc/web_register_registry_case',p,write=True)
    if not result.get('case_id'):raise StoreError('照合結果が変わりました。登録前の確認をやり直してください。')
    workspace.refresh()
    # Keep the receipt across restarts without modifying the extracted JSON.
    folder=workspace.output/'imports'/pending['cid']
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'registration.json').write_text(canonical(result),encoding='utf8')
    workspace.cases=[c for c in workspace.cases if c['id']!=pending['cid']]
    workspace.raw.pop(pending['cid'],None)
    from web_documents import flush
    warning=flush(workspace,pending['cid'],result['case_id'])
    return {'state':workspace.public(),'case_id':result['case_id'],'registration':result,'warning':warning}
