"""Explicit local review choices; fingerprints invalidate choices after source changes."""
import hashlib,json
from web_data import StoreError,canonical

def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def path(w,cid):return w.output/'review_choices'/(fingerprint(cid)+'.json')
def read(w,cid):
    p=path(w,cid)
    return json.loads(p.read_text(encoding='utf8')) if p.exists() else {}
def save(w,cid,data):
    p=path(w,cid);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(canonical(data),encoding='utf8');tmp.replace(p)
def decorate(w,c):
    choices=read(w,c['id'])
    for x in c['source_conflicts']:
        x['choice_id']=fingerprint(x)
        if x['choice_id'] in choices:x['chosen_source']=choices[x['choice_id']]['source']
    for d in c['diffs']:
        key=fingerprint({'id':d['id'],'old':d['old_value'],'new':d['new_value']})
        if key in choices:d['user_choice']='old'
def choose(w,cid,kind,key,source):
    c=next(c for c in w.public()['cases'] if c['id']==cid);choices=read(w,cid)
    if kind=='diff' and source=='old':
        d=next((d for d in c['diffs'] if d['id']==key),None)
        if not d or d['review_status'] in ('applied','ignored'):raise StoreError('差分を再確認してください。')
        w.decide(cid,key,'hold') # Keep the confirmed master, using the existing DB route.
        key=fingerprint({'id':d['id'],'old':d['old_value'],'new':d['new_value']})
        choices[key]={'source':'old'}
    elif kind=='conflict' and source in ('report','rules'):
        x=next((x for x in c['source_conflicts'] if x['choice_id']==key),None)
        if not x:raise StoreError('資料が変わりました。再確認してください。')
        # These restrictions are currently display-only; do not pretend to update Excel/master.
        choices[key]={'source':source,'value':x[source+'_value'],'evidence':x}
    else:raise StoreError('選択内容を確認してください。')
    save(w,cid,choices);return w.public()
