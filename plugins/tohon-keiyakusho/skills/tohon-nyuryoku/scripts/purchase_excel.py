"""Purchase values use named inputs; unknown historical values never retain template data."""
import json
from datetime import date
from pathlib import Path
from important_report_store import write_named_excel

MAPPING=json.loads(Path(__file__).with_name('purchase_mapping.json').read_text(encoding='utf8'))

def append_purchase_fields(path,fields):
    path=Path(path)
    values={}
    for code,spec in MAPPING.items():
        if not spec['excel_named_range']:continue
        item=fields.get(code,{})
        safe=(item.get('value') is not None and not item.get('needs_review') and
              item.get('confidence') is not None and .85<=item['confidence']<=1 and
              item.get('page_no') and item.get('source_text'))
        if safe:values[code]=dict(item,approved=True)
        else:
            # Clear the named input, without creating a claim that the value was extracted.
            values[code]={'value':'','approved':True,'needs_review':False,'confidence':1,
                          'page_no':1,'source_text':'未取得入力欄の初期化'}
    mapping=dict(MAPPING)
    handover=values.pop('handover_date')
    parts=['','','','']
    if handover['value']:
        actual=date.fromisoformat(handover['value'])
        parts=['西暦',actual.year,actual.month,actual.day]
        for era,start in [('令和',date(2019,5,1)),('平成',date(1989,1,8)),('昭和',date(1926,12,25))]:
            if actual>=start:parts=[era,actual.year-start.year+1,actual.month,actual.day];break
    for suffix,value in zip(('era','year','month','day'),parts):
        code='handover_date_'+suffix
        values[code]=dict(handover,value=value)
        mapping[code]={'excel_named_range':'購入時_'+code}
    output=path.with_name('purchase_values.xlsm')
    result=write_named_excel(path,output,values,mapping)
    if result['output']:output.replace(path)
    result['cleared']=[x for x in result['written'] if x['value']=='']
    result['written']=[x for x in result['written'] if x['value']!='']
    return result
