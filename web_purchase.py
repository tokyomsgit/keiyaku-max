from web_reading import read_existing
"""Purchase baseline adapters; Excel consumes case-selected evidence only."""
import copy
import hashlib
import json
from pathlib import Path
from web_data import ROOT, StoreError, field_view, env
from web_registration import PATHS, BUILDING
from purchase_explanation_reader import read_purchase, LABELS

TYPE='purchase_important_explanation'


def integrated(data, fields=None):
    fields=data['fields'] if fields is None else fields
    src=data.get('source',{})
    def node(item,v=None,explicit=False):
        return {'value':copy.deepcopy(v if explicit else item.get('value')),
          'confidence':item.get('confidence'),'needs_review':item.get('needs_review',False),
          'sources':[{'page':item.get('page_no'),'text':item.get('source_text') or '',
             'source_pdf':src.get('original_filename'),'file_hash':src.get('file_hash')}] if item.get('page_no') and item.get('source_text') else []}
    result={'property_type':{'value':data['property_type'],'sources':[]},'lands':[],'mortgages':[],
       'building':{},'unit':{},'owner':{},'land_right':{},'group_review':[]}
    for code,path in PATHS.items():
        if '.' not in path:continue
        section,key=path.split('.');result[section][key]=node(fields.get(code,{}))
    result['building']['floor_areas']=[]
    built=result['unit'].get('built_date',{})
    if built.get('value'):
        from datetime import date
        try:
            actual=date.fromisoformat(built['value'])
            for era,start in [('令和',(2019,5,1)),('平成',(1989,1,8)),('昭和',(1926,12,25)),('大正',(1912,7,30)),('明治',(1868,9,8))]:
                if actual>=date(*start):built['value']=f'{era}{actual.year-start[0]+1}年{actual.month}月{actual.day}日';break
        except ValueError:pass
    for land in fields.get('land_lots',{}).get('value') or []:
        parent=fields['land_lots'];n=land.get('numerator');d=land.get('denominator')
        share=f'{d}分の{n}' if n is not None and d else None
        result['lands'].append({k:node(parent,land.get(v),True) for k,v in
          [('location','location'),('lot_number','lot_number'),('category','land_category'),('area','area'),('right_type','right_type')]}
          |{'right_share':node(parent,share,True),'share_numerator':node(parent,n,True),'share_denominator':node(parent,d,True)})
    if result['lands']:
        # Building lot is only derived when its own registry location contains this exact lot.
        location=fields.get('registry_location',{}).get('value') or ''
        lots=[x['lot_number']['value'] for x in result['lands']]
        location=location.replace('番地','番')
        matched=[lot for lot in lots if lot and lot.replace('番地','番') in location]
        if len(matched)==1:
            result['building']['lot_number']=node(fields['registry_location'],matched[0],True)
            result['building']['location']=node(fields['registry_location'],location.replace(matched[0],'').strip(),True)
    for x in fields.get('active_mortgages',{}).get('value') or []:
        result['mortgages'].append({k:node(fields['active_mortgages'],x.get(v) if k=='active' or x.get(v) is None else str(x[v]),True) for k,v in
          [('rank','rank'),('kind','type'),('amount','amount'),('debtor','debtor'),('creditor','mortgagee'),('active','active')]})
    n=fields.get('land_right_numerator',{}).get('value');d=fields.get('land_right_denominator',{}).get('value')
    if n is not None and d:
        share=node(fields['land_right_numerator'],f'{d}分の{n}',True)
        result['land_right']['share']=share
        for land in result['lands']:
            land['right_share']=copy.deepcopy(share)
            land['right_type']=node(fields.get('land_right_type',{}))
    return result


def payload(data):
    kind=data.get('property_type')
    if kind not in ('condominium_land_right','condominium_no_land_right','leasehold_condominium'):
        raise StoreError('戸建て・物件種別不明の資料は登録できません。')
    if data.get('source',{}).get('page_count',0)>data.get('source',{}).get('text_pages',0) and not data.get('property_type_verified'):
        raise StoreError('スキャン原本で物件種別・登録項目を確認してください。')
    fields=[];b={'property_type':kind};u={}
    for code,item in data['fields'].items():
        f={**copy.deepcopy(item),'field_code':code,'provenance':{'needs_review':item.get('needs_review',True),'historical':True,'verified_against_original':item.get('verified_against_original',False),'ai_confidence':item.get('ai_confidence'),'verified_at':item.get('verified_at')}}
        fields.append(f)
        if not item.get('needs_review') and item.get('value') is not None:
            (b if code in BUILDING else u)[code]=copy.deepcopy(item['value'])
    if b.get('land_lots'):
        b['land_lots']=[{k:x.get(k) for k in ('location','lot_number','land_category','area')} for x in b['land_lots']]
    s=data['source'];doc={**s,'values':fields}
    return {'building':b,'unit':u,'fields':fields,'documents':[doc],
       'raw_json':{'format':'normalized_purchase_v1','purchase':copy.deepcopy(data),'integrated':integrated(data)},
       'file_set_hash':s['file_hash']}


def stage(w,data):
    from web_registry import case_from
    cid='upload-purchase-'+data['source']['file_hash'][:24]
    c=case_from(integrated(data),cid);c.update(registration_required=bool(w.remote),purchase_baseline=True,
      status='購入時重説・初期値確認',upload_warnings=['購入時点の過去資料です。最新の謄本・重調で確認してください。'])
    c['documents']=[{'id':cid,'version_id':cid+'-v1','type':TYPE,'filename':data['source']['original_filename'],
       'version':1,'date':None,'fields':[field_view(k,v) for k,v in data['fields'].items()]}]
    w.cases=[x for x in w.cases if x['id']!=cid];w.cases.append(c);w.raw[cid]={'purchase':data}
    folder=w.output/'purchase_imports'/cid;folder.mkdir(parents=True,exist_ok=True)
    (folder/'purchase.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
    return cid


def restore(w):
    for path in (w.output/'purchase_imports').glob('*/purchase.json'):
        if w.remote and (w.output/'imports'/path.parent.name/'registration.json').is_file():continue
        try:stage(w,json.loads(path.read_text(encoding='utf8')))
        except (OSError,ValueError,KeyError):continue


def upload(w,cid,files):
    if len(files)!=1:raise StoreError('初期資料の購入時重説は1件ずつ選択してください。')
    if cid:raise StoreError('購入時重説は新規案件の初期資料として選択してください。既存案件には最新資料を追加してください。')
    name,content=files[0];digest=hashlib.sha256(content).hexdigest()
    folder=w.output/'purchase_cache'/digest;folder.mkdir(parents=True,exist_ok=True);pdf=folder/'source.pdf';pdf.write_bytes(content)
    roots=[ROOT.parent/'verification_purchase/cache']
    if env('PURCHASE_CACHE_DIR'):roots.insert(0,Path(env('PURCHASE_CACHE_DIR')))
    for root in roots:
        raw=root/digest/'extracted_raw.json'
        if raw.exists() and not (folder/'extracted_raw.json').exists():(folder/'extracted_raw.json').write_bytes(raw.read_bytes())
        review=root/digest/'reviewed_fields.json'
        if review.exists():
            target=folder/'reviewed_fields.json'
            incoming=json.loads(review.read_text(encoding='utf8'))
            current=json.loads(target.read_text(encoding='utf8')) if target.exists() else {}
            if incoming.get('file_hash')!=digest:raise StoreError('原本確認データが別のPDFです。')
            merged=dict(current.get('fields',{}))
            for code,item in incoming.get('fields',{}).items():
                if item.get('verified_at','')>merged.get(code,{}).get('verified_at',''):merged[code]=item
            target.write_text(json.dumps({**incoming,**current,'fields':merged},ensure_ascii=False),encoding='utf8')
    normalized=folder/'extracted_normalized.json'
    if normalized.exists() and not (folder/'extracted_raw.json').exists():
        data=json.loads(normalized.read_text(encoding='utf8'))
        if data.get('source',{}).get('file_hash')==digest and data.get('is_purchase_explanation') is True:
            data['source'].update(original_filename=name.replace('\\','/').rsplit('/',1)[-1],storage_path=str(pdf.resolve()))
            return _stage_cached(w,data)
    def count():
        from web_ai_cost import permit
        permit(w,'purchase',pdf)
        w.ai_calls+=1
    data=read_existing(read_purchase,pdf,w.output/'purchase_cache',on_api=count,allow_api=not w.demo)
    data['source'].update(original_filename=name.replace('\\','/').rsplit('/',1)[-1],storage_path=str(pdf.resolve()))
    cid=stage(w,data)
    return {'state':w.public(),'case_id':cid,'reused':int(data['source']['cache_reused'])}


def verify_fields(w,cid,entries,property_type):
    """Explicit original-document review; retains the AI output unchanged."""
    import datetime as dt
    from purchase_explanation_reader import NUMBER,KINDS
    data=copy.deepcopy(w.raw.get(cid,{}).get('purchase'))
    if not data or not cid.startswith('upload-purchase-'):raise StoreError('未登録の購入時重説を選択してください。')
    if property_type not in KINDS or not entries:raise StoreError('原本確認した項目と物件種別を選択してください。')
    changed={}
    for entry in entries:
        code=entry.get('code');v=entry.get('value');page=entry.get('page_no');quote=entry.get('source_text')
        if code not in LABELS or entry.get('verified') is not True:raise StoreError('確認した項目だけ選択してください。')
        if isinstance(page,bool) or not isinstance(page,int) or not 1<=page<=data['source']['page_count'] or not isinstance(quote,str) or not quote.strip():raise StoreError('PDFのページ番号と原文を入力してください。')
        if code in NUMBER and (isinstance(v,bool) or not isinstance(v,(int,float)) or not __import__('math').isfinite(v) or v<0):raise StoreError('数値を確認してください。')
        if code in ('land_lots','active_mortgages') and (not isinstance(v,list) or any(not isinstance(x,dict) for x in v)):raise StoreError('表の項目形式を確認してください。')
        if code=='has_land_right' and not isinstance(v,bool):raise StoreError('敷地権の有無を確認してください。')
        if code not in NUMBER|{'land_lots','active_mortgages','has_land_right'} and v is not None and not isinstance(v,str):raise StoreError('項目の文字列形式を確認してください。')
        if code=='land_lots':
            for land in v:
                for key in ('area','numerator','denominator'):
                    n=land.get(key)
                    if n is not None and (isinstance(n,bool) or not isinstance(n,(int,float)) or not __import__('math').isfinite(n) or n<0):raise StoreError('土地の面積・持分を確認してください。')
        asof=entry.get('value_as_of_date') or None
        try:
            if asof:dt.date.fromisoformat(asof)
            if code in ('built_date','handover_date') and v:dt.date.fromisoformat(v)
        except (TypeError,ValueError):raise StoreError('日付は西暦の年月日で入力してください。') from None
        old=data['fields'].get(code,{})
        changed[code]={**old,'value':v,'page_no':page,'source_text':quote,'confidence':1,
          'ai_confidence':old.get('ai_confidence',old.get('confidence')),'value_as_of_date':asof if 'value_as_of_date' in entry else old.get('value_as_of_date'),'needs_review':False,'review_reasons':[],
          'verified_against_original':True,'verified_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    digest=data['source']['file_hash'];folder=w.output/'purchase_cache'/digest
    target=folder/'reviewed_fields.json';prior=json.loads(target.read_text(encoding='utf8')) if target.exists() else {}
    prior.update(file_hash=digest,property_type=property_type,fields={**prior.get('fields',{}),**changed})
    temp=target.with_suffix('.tmp');temp.write_text(json.dumps(prior,ensure_ascii=False),encoding='utf8');temp.replace(target)
    data['fields'].update(changed);data.update(property_type=property_type,property_type_verified=True)
    # Invalidate any earlier registration preview after a correction.
    w.registration_pending={k:v for k,v in getattr(w,'registration_pending',{}).items() if v['cid']!=cid}
    stage(w,data)
    return {'state':w.public(),'case_id':cid}


def apply_snapshot(w,c,case,s):
    selected=case.get('purchase_values')
    if selected is None:return
    rows={e['extracted_value_id']:e for e in s['values']}
    vals={k:copy.deepcopy(rows[v]) for k,v in selected.items() if v in rows}
    for k,e in vals.items():e.update(needs_review=False,approved=True)
    # Record the source actually selected, never select the last uploaded file.
    kind=w.raw[c['id']]['building'].get('property_type','unknown')
    data={'property_type':kind,'fields':vals,'source':{}}
    c.update(purchase_baseline=True,generation_blocked=kind not in ('condominium_land_right','condominium_no_land_right','leasehold_condominium'),
      owner=vals.get('current_owner_name',{}).get('value'),area=vals.get('registered_area',{}).get('value'))
    w.raw[c['id']]['purchase']=data
    for doc in c['documents']:
        for f in doc['fields']:f['accepted']=selected.get(f['code'])==f.get('extracted_value_id')


def generate(w,cid):
    from web_registry import generate as existing_generate
    data=w.raw[cid]['purchase'];original=w.raw[cid]
    fields={k:v for k,v in data['fields'].items() if not v.get('needs_review') and v.get('value') is not None}
    b={};u={}
    for k,f in fields.items():(b if k in BUILDING else u)[k]=f['value']
    w.raw[cid]={'uploaded':integrated(data,fields),'registered':True,'unit':u,'building':b,
       'report_fields':{k:dict(v,approved=True) for k,v in fields.items()}}
    try:
        result=existing_generate(w,cid)
        from purchase_excel import append_purchase_fields
        extra=append_purchase_fields(w.files[result['download'].split('/')[-1]],fields)
        result['purchase_written']=len(extra['written'])
        result['report_written']+=len(extra['written'])
        result['warnings'].insert(0,'購入時重説を初期資料にしています。現在採用中の値を出力しました。最新資料と照合してください。')
        return result
    finally:w.raw[cid]=original


def _stage_cached(w,data):
    cid=stage(w,data)
    return {"state":w.public(),"case_id":cid,"reused":1}
