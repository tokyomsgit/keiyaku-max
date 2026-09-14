"""Contract-relevant rules only; preserve quotations and uncertainty."""
import copy
import json
import math
from pathlib import Path
from important_report_schema import obj, nullable, compact

MAPPING=json.loads(Path(__file__).with_name('management_rules_mapping.json').read_text(encoding='utf8'))
META=('source_article','source_section','source_text','page_no','confidence')
ITEM=obj({'value':nullable('string'),**{k:nullable('integer' if k=='page_no' else 'number' if k=='confidence' else 'string') for k in META}})
API_SCHEMA=obj({'is_management_rules':{'type':'boolean'},'building_name':nullable('string'),
    'fields':obj({k:{**copy.deepcopy(ITEM),'description':v['label']} for k,v in MAPPING.items()})})


def normalize(raw,pages=None):
    if not isinstance(raw,dict) or raw.get('is_management_rules') is not True:
        raise ValueError('管理規約と確認できませんでした。資料種類を確認してください。')
    result={'schema_version':1,'is_management_rules':True,'building_name':raw.get('building_name'),'fields':{}}
    for code in MAPPING:
        old=raw.get('fields',{}).get(code) or {};item={k:old.get(k) for k in ('value',)+META}
        reasons=list(old.get('review_reasons') or [])
        if item['value'] is None:reasons.append('未取得')
        elif not isinstance(item['value'],(str,bool,int,float)):
            item['value']=None;reasons.append('値の形式を確認')
        c=item['confidence'];p=item['page_no']
        if isinstance(c,bool) or not isinstance(c,(int,float)) or not math.isfinite(c) or not 0<=c<=1:item['confidence']=None
        if item['confidence'] is None or item['confidence']<.85:reasons.append('読取内容の確認が必要')
        if isinstance(p,bool) or not isinstance(p,int) or p<1 or (pages and p>len(pages)):
            item['page_no']=None;reasons.append('根拠ページ不明')
        if not isinstance(item['source_text'],str) or not item['source_text'].strip():
            item['source_text']=None;reasons.append('根拠テキスト不明')
        elif pages and item['page_no']:
            page=pages[item['page_no']-1]
            if page['mode']=='scan':reasons.append('画像の原文確認が必要')
            elif compact(item['source_text']) not in compact(page['text']):reasons.append('原文との照合が必要')
        item['review_reasons']=sorted(set(reasons));item['needs_review']=bool(reasons or old.get('needs_review'))
        if old.get('candidates'):item['candidates']=copy.deepcopy(old['candidates'])
        result['fields'][code]=item
    if raw.get('source'):result['source']=copy.deepcopy(raw['source'])
    return result
