"""Local-first preparation and server-owned AI consent. No network calls here."""
import copy,hashlib,json,math,re,secrets,time
from pathlib import Path
from web_data import ROOT,env,StoreError

CACHE={'registry':'registry_cache','report':'report_cache','purchase':'purchase_cache','rules':'rules_cache'}

def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)

def pricing():return json.loads((ROOT/'config/ai_pricing.json').read_text(encoding='utf-8-sig'))

def estimate(pages,model=None,config=None):
    config=config or pricing();model=model or env('OPENAI_MODEL') or 'gpt-4.1';spec=config.get('models',{}).get(model,{})
    rate=config.get('usd_to_jpy');images=sum(p['mode']!='text' for p in pages)
    try:
        if rate is None or (images and spec.get('image_page_estimate_usd') is None):return None
        # UTF-8 byte count is a conservative text-token allowance, not a tokenizer result.
        inputs=sum(len(p['text'].encode('utf8')) for p in pages)+spec['prompt_tokens_estimate']
        usd=(inputs*spec['input_per_1m_tokens_usd']+spec['output_tokens_estimate']*spec['output_per_1m_tokens_usd'])/1e6
        result=(usd+images*(spec.get('image_page_estimate_usd') or 0))*rate
        return math.ceil(result) if math.isfinite(result) and result>=0 and rate>0 else None
    except (KeyError,TypeError,ValueError):return None

def cache_hit(w,kind,digest):
    if kind=='registry':
        from web_registry import cached,reader_root
        root=reader_root()
        if cached(digest,root,w.output) is not None:return True
        folder=w.output/'registry_cache'/digest
        if (folder/'ai_raw.json').exists() and (folder/'source_pages.json').exists():
            from normalize_registry import normalize_document
            data=normalize_document(json.loads((folder/'ai_raw.json').read_text(encoding='utf8')),json.loads((folder/'source_pages.json').read_text(encoding='utf8')),str(folder/'source.pdf'))
            data['metadata']={'source_sha256':digest};save(folder/'extracted.json',data);return True
        return False
    if kind=='report':
        from web_report import cached_report
        if cached_report(digest,w.output) is not None:return True
    if kind=='rules':
        from web_rules import cached
        if cached(digest,w.output) is not None:return True
    # Recover original raw JSON without another AI request after normalization failures.
    bases=[w.output/CACHE[kind],ROOT.parent/({'report':'verification_important','purchase':'verification_purchase','rules':'verification_rules'}[kind])/'cache']
    configured=env({'report':'IMPORTANT_REPORT_CACHE_DIR','purchase':'PURCHASE_CACHE_DIR','rules':'MANAGEMENT_RULES_CACHE_DIR'}[kind])
    if configured:bases.insert(0,Path(configured))
    for base in bases:
        if kind=='purchase':
            normalized=base/digest/'extracted_normalized.json'
            if normalized.exists():
                saved=json.loads(normalized.read_text(encoding='utf8'))
                if saved.get('source',{}).get('file_hash')==digest and saved.get('is_purchase_explanation') is True:
                    target=w.output/CACHE[kind]/digest/'extracted_normalized.json'
                    if not target.exists():save(target,saved)
                    return True
        raw=base/digest/'extracted_raw.json'
        if raw.exists():
            data=json.loads(raw.read_text(encoding='utf8'))
            target=w.output/CACHE[kind]/digest/'extracted_raw.json'
            if not target.exists():save(target,data)
            if kind=='report':
                from important_report_reader import pdf_pages
                from important_report_schema import normalize
                pdf=target.parent/'source.pdf'
                if pdf.exists():
                    pages=pdf_pages(pdf);normalized=normalize(data,pages)
                    normalized['source']={'file_hash':digest,'original_filename':pdf.name,'page_count':len(pages),'text_pages':sum(p['mode']=='text' for p in pages),'cache_reused':True}
                    save(target.parent/'extracted_normalized.json',normalized)
            return True
    return False

def local_result(w,kind,pdf,pages,digest):
    """Only explicit single-label candidates; current state still requires review."""
    text='\n'.join(p['text'] for p in pages)
    folder=w.output/CACHE[kind]/digest
    if kind=='registry':
        from web_registry import reader_root
        reader_root()
        from normalize_registry import normalize_document
        legacy=[dict(p,page=p['page_no']) for p in pages]
        data=normalize_document({},legacy,str(pdf))
        data['metadata']={'source_sha256':digest,'source_pdf':str(pdf),'pages':legacy,'local_processing':True}
        def mark(node):
            if isinstance(node,dict):
                if 'value' in node:node['needs_review']=True
                for value in node.values():mark(value)
            elif isinstance(node,list):
                for value in node:mark(value)
        mark(data)
        data['warnings'].append('テキストの既存ルール処理です。未取得・現在有効性は原本確認が必要です。')
        save(folder/'extracted.json',data);return
    if kind=='rules':
        from management_rules_reader import local_candidates
        raw=local_candidates(pages)
        for f in raw['fields'].values():
            f['source_section']='ローカル抽出の条文候補';f['review_reasons']=['現在有効な条文・例外条件は原本確認が必要']
    else:
        raw={'fields':{},'local_candidates':True}
        if kind=='report':raw.update(is_important_report=True,house_number=None)
        else:raw.update(is_purchase_explanation=True,property_type='unknown')
        labels={'management_fee':r'(?:月額管理費|管理費月額|管理費)',
                'repair_reserve_fee':r'(?:月額修繕積立金|修繕積立金月額|修繕積立金)',
                'building_name':r'(?:マンション名|建物名称|建物名)',
                'unit_name':r'(?:部屋番号|号室)', 'management_company':r'(?:管理会社名|管理会社)'}
        for code,label in labels.items():
            hits=[]
            for page in pages:
                for line in page['text'].splitlines():
                    match=re.fullmatch(r'\s*'+label+r'\s*[:：]\s*(.+?)\s*',line)
                    if match:hits.append((page['page_no'],line,match.group(1)))
            if len(hits)!=1:continue
            page,line,value=hits[0]
            if code.endswith('_fee'):
                match=re.fullmatch(r'([0-9,]+)\s*円(?:\s*[/／]\s*月)?',value)
                if not match:continue
                value=match.group(1)
            raw['fields'][code]={'value':value,'page_no':page,'source_text':line,'source_label':line.split('：')[0].split(':')[0],
                'source_section':'ローカル抽出候補','confidence':None,'value_as_of_date':None,'needs_review':True}
    raw['local_candidates']=True
    save(folder/'extracted_raw.json',raw)
    if kind=='rules':
        from management_rules_schema import normalize
    elif kind=='report':
        from important_report_schema import normalize
    else:
        from purchase_explanation_reader import normalize
    data=normalize(raw,pages)
    data['source']={'file_hash':digest,'original_filename':pdf.name,'page_count':len(pages),'text_pages':len(pages),'local_processing':True}
    save(folder/'extracted_normalized.json',data)


def prepare(w,files,cid=None):
    from important_report_reader import pdf_pages
    items=[];seen=set()
    if not 1<=len(files)<=12:raise StoreError('PDFは1〜12件選択してください。')
    for kind,name,content in files:
        if kind not in CACHE:raise StoreError('資料種類を選択してください。')
        if not name.lower().endswith('.pdf') or not content.startswith(b'%PDF-'):raise StoreError('対応していないPDFです。')
        digest=hashlib.sha256(content).hexdigest();key=(kind,digest)
        if key in seen:raise StoreError('同じPDFは追加済みです。')
        seen.add(key);folder=w.output/CACHE[kind]/digest;folder.mkdir(parents=True,exist_ok=True);(folder/'source.pdf').write_bytes(content);mode='cache';cost=0;note='キャッシュあり';count=None
        if not cache_hit(w,kind,digest):
            folder=w.output/CACHE[kind]/digest;folder.mkdir(parents=True,exist_ok=True);pdf=folder/'source.pdf';pdf.write_bytes(content)
            try:pages=pdf_pages(pdf)
            except Exception:raise StoreError('対応していないPDF：破損・パスワードを確認してください。') from None
            if not pages:raise StoreError('ページがないPDFです。')
            count=len(pages);text='\n'.join(p['text'] for p in pages)
            recognizable=bool(re.search({'registry':'表題部|専有部分|権利部','report':'重要事項調査|管理費|修繕積立金','purchase':'重要事項説明','rules':'管理規約|使用細則'}[kind],text))
            if all(p['mode']=='text' for p in pages) and recognizable:
                local_result(w,kind,pdf,pages,digest);mode='local';note='テキスト抽出・ローカル処理（要確認）'
            elif all(p['mode']=='text' for p in pages):
                raise StoreError('資料種類を確認できません。種類とPDF内容を確認してください。')
            else:mode='ai';note='AI解析が必要';cost=estimate(pages)
        items.append({'kind':kind,'hash':digest,'name':name.replace('\\','/').rsplit('/',1)[-1],'mode':mode,'status':note,'api_required':mode=='ai','estimate_jpy':cost,'pages':count})
    ai=[i for i in items if i['api_required']];total=None if any(i['estimate_jpy'] is None for i in ai) else sum(i['estimate_jpy'] for i in ai)
    rules_scan=any(i['kind']=='rules' for i in ai)
    blocked=bool((w.demo and ai) or rules_scan);warning='デモモードではAI解析できません。' if blocked else None
    if rules_scan:warning='画像の管理規約は条文候補を絞れません。必要条文を確認できる資料を用意してください。全文をAIには送信しません。'
    limit=env('AI_COST_LIMIT_JPY')
    if limit and ai:
        try:
            cap=float(limit)
            if not math.isfinite(cap) or cap<0:raise ValueError()
        except ValueError:raise StoreError('AI料金上限の設定を確認してください。') from None
        if total is None or total>cap:blocked=True;warning='設定された上限を超える可能性があります。概算不能の場合も自動実行しません。'
    token=secrets.token_urlsafe(24);plan={'token':token,'files':items,'ai_files':len(ai),'estimate_jpy':total,'blocked':blocked,'warning':warning}
    plans=getattr(w,'cost_plans',{});plans={k:v for k,v in plans.items() if time.time()-v['at']<1800}
    plans[token]={'at':time.time(),'plan':copy.deepcopy(plan),'pricing':pricing(),'limit':limit,'model':env('OPENAI_MODEL') or 'gpt-4.1'};w.cost_plans=plans
    return plan


def authorize(w,token,files,confirmed=False):
    record=getattr(w,'cost_plans',{}).get(token)
    if not record or time.time()-record['at']>1800:raise StoreError('料金確認をやり直してください。')
    plan=record['plan'];keys={(k,hashlib.sha256(b).hexdigest()) for k,_,b in files}
    allowed={(i['kind'],i['hash']) for i in plan['files']}
    if not keys<=allowed or record['pricing']!=pricing() or record['limit']!=env('AI_COST_LIMIT_JPY') or record['model']!=(env('OPENAI_MODEL') or 'gpt-4.1'):raise StoreError('資料・料金設定が変更されました。料金確認をやり直してください。')
    if plan['blocked']:raise StoreError(plan['warning'])
    grants=getattr(w,'ai_grants',{})
    for i in plan['files']:
        key=(i['kind'],i['hash'])
        if key in keys and i['api_required']:
            if key in record.get('used',set()) and not cache_hit(w,i['kind'],i['hash']):raise StoreError('前回のAI実行後です。料金確認からやり直してください。')
            if w.demo or not confirmed:raise StoreError('AI解析前に概算料金を確認してください。')
            grants[key]=record
    w.ai_grants=grants
    return plan


def permit(w,kind,pdf):
    key=(kind,hashlib.sha256(Path(pdf).read_bytes()).hexdigest());record=getattr(w,'ai_grants',{}).pop(key,None)
    if w.demo or not record or time.time()-record['at']>1800:raise StoreError('AI解析前に資料を選択し、料金確認を行ってください。')
    if record['pricing']!=pricing() or record['limit']!=env('AI_COST_LIMIT_JPY') or record['model']!=(env('OPENAI_MODEL') or 'gpt-4.1'):raise StoreError('料金設定が変更されました。再度料金を確認してください。')
    record.setdefault('used',set()).add(key)


def summary(w,plan,files,result,before):
    hashes={hashlib.sha256(b).hexdigest() for _,_,b in files};items=[i for i in plan['files'] if i['hash'] in hashes]
    c=next((c for c in result['state']['cases'] if c['id']==result['case_id']),{})
    pending={f['filename'] for f in c.get('pending_documents',[])}
    done=[i for i in items if i['name'] not in pending];calls=w.ai_calls-before
    ai=[i for i in done if i['api_required']]
    cost=0 if not calls else None if any(i['estimate_jpy'] is None for i in ai) else sum(i['estimate_jpy'] for i in ai)
    if calls and ai:
        actual=[];config=pricing();rate=config.get('usd_to_jpy')
        for item in ai:
            path=w.output/CACHE[item['kind']]/item['hash']/'api_usage.json'
            try:
                usage=json.loads(path.read_text(encoding='utf8'));spec=config['models'][usage['model']];tokens=usage['usage']
                amount=(tokens['input_tokens']*spec['input_per_1m_tokens_usd']+tokens['output_tokens']*spec['output_per_1m_tokens_usd'])/1e6*rate
                actual.append(math.ceil(amount) if math.isfinite(amount) and amount>=0 else None)
            except (OSError,ValueError,KeyError,TypeError):actual.append(None)
        if actual and all(v is not None for v in actual):cost=sum(actual)
    result['analysis_summary']={'cache':sum(i['mode']=='cache' for i in done),'local':sum(i['mode']=='local' for i in done),'ai':len(ai),'pending':len(pending),'api_calls':calls,'estimate_jpy':cost}
    totals=getattr(w,'cost_totals',{});old=totals.get(result['case_id'],{'api_calls':0,'estimate_jpy':0})
    totals[result['case_id']]={'api_calls':old['api_calls']+calls,'estimate_jpy':None if old['estimate_jpy'] is None or cost is None else old['estimate_jpy']+cost};w.cost_totals=totals
    result['analysis_summary']['session_total']=totals[result['case_id']]
    return result
