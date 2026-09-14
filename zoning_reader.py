"""Local-first reader for municipal zoning/city-planning reference PDFs."""
import datetime as dt
import re
from pathlib import Path

from web_data import StoreError


LABELS={
    'planning_area':'区域区分／都市計画区域','zoning_type':'用途地域','special_use_district':'特別用途地区',
    'building_coverage_ratio':'建ぺい率','floor_area_ratio':'容積率','minimum_lot_area':'敷地面積の最低限度',
    'height_district':'高度地区','fire_zone':'防火規制','shadow_restriction':'日影規制','printed_at':'印刷日',
    'issuer':'発行元',
}


def _clean(value):
    return re.sub(r'\s+',' ',value).strip(' ：:―-')


def _date(text):
    m=re.search(r'印刷日\s*[：:]\s*(?:令和\s*(\d+)年\s*(\d+)月\s*(\d+)日|(\d{4})[/-](\d{1,2})[/-](\d{1,2}))',text)
    if not m:return None
    if m.group(1):y,mo,d=2018+int(m.group(1)),int(m.group(2)),int(m.group(3))
    else:y,mo,d=map(int,m.groups()[3:])
    return dt.date(y,mo,d).isoformat()


def parse_text(text,page_no=1):
    lines=[_clean(x) for x in text.splitlines() if _clean(x)]
    fields={}
    patterns={
      'planning_area':r'^区域区分／都市計画区域\s+(.+)$',
      'zoning_type':r'^用途地域\s+(.+)$',
      'special_use_district':r'^特別用途地区\s+(.+)$',
      'building_coverage_ratio':r'^建ぺい率\s+([0-9０-９]+\s*%)$',
      'floor_area_ratio':r'^容積率\s+([0-9０-９]+\s*%)$',
      'minimum_lot_area':r'^敷地面積の最低限度\s+(.+)$',
      'height_district':r'^高度地区\s+(.+)$',
      'fire_zone':r'^防火規制(?:／新防火区域（都安全条例）)?\s+(.+)$',
      'shadow_restriction':r'^日影規制\s+(.+)$',
    }
    for code,pattern in patterns.items():
        hits=[]
        for line in lines:
            m=re.search(pattern,line)
            if m:hits.append((line,_clean(m.group(1))))
        if len(hits)==1:
            line,value=hits[0];fields[code]={'value':value,'page_no':page_no,'source_text':line,'needs_review':False}
    height=re.search(r'種別\s*[：:]\s*([^\s]+高度地区)',text)
    if height:fields['height_district']={'value':height.group(1),'page_no':page_no,'source_text':_clean(height.group(0)),'needs_review':False}
    issuer=re.search(r'発行元\s*[：:]\s*([^\n]+)',text)
    if issuer:fields['issuer']={'value':_clean(issuer.group(1)),'page_no':page_no,'source_text':_clean(issuer.group(0)),'needs_review':False}
    printed=_date(text)
    if printed:fields['printed_at']={'value':printed,'page_no':page_no,'source_text':'印刷日','needs_review':False}
    return fields


def read_zoning(path):
    from pypdf import PdfReader
    pdf=Path(path);reader=PdfReader(pdf)
    if reader.is_encrypted and not reader.decrypt(''):raise StoreError('パスワード付きPDFは読み取れません。')
    fields={};pages=[]
    for i,page in enumerate(reader.pages,1):
        text=page.extract_text(extraction_mode='layout') or '';pages.append(text)
        for code,item in parse_text(text,i).items():fields.setdefault(code,item)
    required={'zoning_type','building_coverage_ratio','floor_area_ratio'}
    status='parsed' if required<=fields.keys() else 'needs_ai' if not any(p.strip() for p in pages) else 'needs_review'
    warnings=[]
    if status=='needs_ai':warnings.append('画像PDFのため、地点を示す図面と指定内容を画像読取する必要があります。')
    elif status=='needs_review':warnings.append('用途地域・建ぺい率・容積率を一意に特定できません。中心地点または指定内容を確認してください。')
    return {'format':'zoning_reference_v1','status':status,'fields':fields,'warnings':warnings,
      'source':{'original_filename':pdf.name,'page_count':len(reader.pages)}}
