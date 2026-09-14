"""Read-only mapping inventory. No customer values or database requests."""
import csv,io,json
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from web_data import SCRIPTS,LABELS

def inventory(template):
    load=lambda n:json.loads((SCRIPTS/n).read_text(encoding='utf8'))
    records=[]
    for filename,source in [('important_report_mapping.json','important_report'),('management_rules_mapping.json','management_rules'),('purchase_mapping.json','purchase_important_explanation')]:
        for code,s in load(filename).items():
            names=[s['excel_named_range']] if s.get('excel_named_range') else []
            if code=='handover_date':names=['購入時_handover_date_'+x for x in ('era','year','month','day')]
            records.append(dict(field_code=code,label=s['label'],entity_level=s.get('entity_level','unit'),primary_source=s.get('primary_source',source),db_supported=True,names=names,notes='資料別の対応。案件の取得値・承認状態とは別です。'))
    db=load('db_mapping.json');m=load('mapping.json')
    for path,s in db.items():
        code=s['column'];names=[v for k,v in m['single'].items() if k==path or k.startswith(path+'.')]
        if code=='land_lots':names=list(m['land']['head'].values())
        if code=='floor_areas':names=[m['floors']['floor_head'],m['floors']['area_head']]
        if code=='has_land_right':names=[m['shikichiken']['yes'],m['shikichiken']['no']]
        records.append(dict(field_code=code,label=LABELS.get(code,path),entity_level='building' if s['table']=='buildings' else 'unit',primary_source='registry',db_supported=True,names=names,notes='配列は先頭入力欄を表示。' if code in ('land_lots','floor_areas') else '単独で転記できる名前定義の対応。'))
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(template) as z:
        root=ET.fromstring(z.read('xl/workbook.xml'))
        names={x.attrib['name']:x.text or '' for x in root.findall('m:definedNames/m:definedName',ns)}
    for r in records:
        refs=[names[n] for n in r['names'] if n in names]
        r['excel_supported']=bool(r['names']) and len(refs)==len(r['names'])
        r['excel_named_range']=' / '.join(r.pop('names'))
        r['sheet']=' / '.join(dict.fromkeys(v.rsplit('!',1)[0].strip("'") for v in refs if '!' in v))
        r['cell']=' / '.join(v.rsplit('!',1)[-1] for v in refs)
        if r['excel_named_range'] and not r['excel_supported']:r['notes']+=' ひな形に名前定義が不足。'
    return records

def export_csv(rows):
    out=io.StringIO(newline='');keys=['field_code','label','entity_level','primary_source','db_supported','excel_supported','excel_named_range','sheet','cell','notes']
    writer=csv.writer(out);writer.writerow(['field_code','日本語名','entity_level','primary_source','db対応','excel対応','excel_named_range','sheet','cell','notes'])
    for r in rows:
        values=[]
        for k in keys:
            v=r[k];v=('対応済み' if v else '未対応') if isinstance(v,bool) else str(v)
            values.append("'"+v if v[:1] in ('=','+','-','@') else v)
        writer.writerow(values)
    return out.getvalue().encode('utf-8-sig')
