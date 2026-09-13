"""重調専用の標準形式。謄本の日本語JSONとは独立させる。"""
import copy
import datetime as dt
import json
import math
from pathlib import Path
import re
import unicodedata

MAPPING = json.loads(Path(__file__).with_name('important_report_mapping.json').read_text(encoding='utf8'))
FIELDS = tuple(MAPPING)
META = ('source_label', 'source_section', 'source_text', 'page_no', 'value_as_of_date', 'confidence')


def obj(properties):
    return {'type':'object', 'properties':properties, 'required':list(properties), 'additionalProperties':False}


def nullable(kind):
    return {'type':[kind, 'null']}


ITEM = obj({'value':nullable('string'), 'source_label':nullable('string'),
    'source_section':nullable('string'), 'source_text':nullable('string'),
    'page_no':nullable('integer'), 'value_as_of_date':nullable('string'),
    'confidence':nullable('number')})
API_SCHEMA = obj({'is_important_report':{'type':'boolean'}, 'house_number':nullable('string'),
    'issuer_name':nullable('string'), 'fields':obj({k:{**copy.deepcopy(ITEM), 'description':v['label']} for k,v in MAPPING.items()})})


def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value)))


def normalize(raw, pages=None):
    """金額・根拠を検査。日付は項目別。発行日からの補完はしない。"""
    if not isinstance(raw,dict) or raw.get('is_important_report') is not True:
        raise ValueError('重要事項調査報告書と確認できませんでした。')
    result = copy.deepcopy(raw)
    result['schema_version'] = 1
    result['fields'] = {}
    for code, spec in MAPPING.items():
        item = copy.deepcopy(raw.get('fields',{}).get(code) or {})
        item = {k:item.get(k) for k in ('value',)+META}
        reasons = []
        value = item['value']
        if isinstance(value,str): value = unicodedata.normalize('NFKC',value).strip() or None
        if value is not None and spec['data_type'] == 'number':
            token = re.sub(r'[,，\s]', '', str(value))
            token = re.sub(r'(円(?:/月|／月)?|戸)$', '',token)
            if re.fullmatch(r'\d+(?:\.\d+)?',token): value = float(token) if '.' in token else int(token)
            else: reasons.append('数値・月額の確認が必要')
        if value is not None and spec['data_type'] == 'date':
            try: value = dt.date.fromisoformat(value).isoformat()
            except (ValueError,TypeError): value=None; reasons.append('年月日の確認が必要')
        if item['value_as_of_date']:
            try: dt.date.fromisoformat(item['value_as_of_date'])
            except (ValueError,TypeError):
                partial=item['value_as_of_date']
                item['value_as_of_date'] = None
                if not isinstance(partial,str) or not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',partial): reasons.append('基準日の確認が必要')
        conf = item['confidence']
        if conf is not None and (isinstance(conf,bool) or not isinstance(conf,(int,float)) or not math.isfinite(conf) or not 0 <= conf <= 1):
            item['confidence'] = None
        if value is not None:
            if item['confidence'] is None or item['confidence'] < .85: reasons.append('読取内容の確認が必要')
            page = item['page_no']
            if not isinstance(page,int) or isinstance(page,bool) or page < 1 or (pages and page > len(pages)):
                item['page_no'] = None; reasons.append('根拠ページ不明')
            if not item['source_text']: reasons.append('根拠テキスト不明')
            elif pages and item['page_no']:
                text = pages[page-1]['text']
                if pages[page-1]['mode']=='scan': reasons.append('画像の原文確認が必要')
                if pages[page-1]['mode'] == 'text' and compact(item['source_text']) not in compact(text):
                    matching=[p['page_no'] for p in pages if p['mode']=='text' and compact(item['source_text']) in compact(p['text'])]
                    if len(matching)==1: item['page_no']=matching[0]
                    else: reasons.append('原文との照合が必要')
            if spec['data_type']=='number' and isinstance(value,(int,float)) and item['source_text']:
                numbers=re.findall(r'(?<![\d.])\d+(?:\.\d+)?',compact(item['source_text']).replace(',',''))
                if not any(float(n)==value for n in numbers): reasons.append('数値と原文の照合が必要')
        item.update(value=value, needs_review=bool(reasons), review_reasons=reasons)
        result['fields'][code] = item
    return result
