"""Deterministic extraction of leasehold terms from a text-layer land registry PDF."""
import datetime as dt
import re
import subprocess
import unicodedata
from pathlib import Path


ERA_START={"明治":1868,"大正":1912,"昭和":1926,"平成":1989,"令和":2019}


def _plain(value):
    return unicodedata.normalize("NFKC",value).replace(" ","").replace("・",".").replace("：",".")


def _date(text):
    m=re.search(r"(明治|大正|昭和|平成|令和)(\d+)年(\d+)月(\d+)日",text)
    if not m:return None
    era,year,month,day=m.groups();year=int(year)
    return {"元号":era,"年":year,"月":int(month),"日":int(day),
            "西暦":f"{ERA_START[era]+year-1:04d}-{int(month):02d}-{int(day):02d}"}


def _end(start,years):
    if not start or not years:return None
    value=dt.date.fromisoformat(start["西暦"])
    try:end=value.replace(year=value.year+years)-dt.timedelta(days=1)
    except ValueError:end=value.replace(year=value.year+years,day=28)-dt.timedelta(days=1)
    for era,base in reversed(list(ERA_START.items())):
        if end.year>=base:return {"元号":era,"年":end.year-base+1,"月":end.month,"日":end.day,"西暦":end.isoformat()}


def parse_land_registry_text(text):
    """Return only explicit leasehold facts. Never derives a total monthly ground rent."""
    raw=_plain(text)
    right="地上権" if "地上権設定" in raw else "賃借権" if "賃借権設定" in raw else None
    setting=re.search(r"原因((?:明治|大正|昭和|平成|令和)\d+年\d+月\d+日)設定",raw)
    start=_date(setting.group(1)) if setting else None
    years_match=re.search(r"存続期間(\d+)年",raw);years=int(years_match.group(1)) if years_match else None
    rent=re.search(r"地代3\.3(?:㎡|m2)当り1月([\d,]+)円",raw)
    title=raw.split("権利部(甲区)",1)[0]
    area=re.search(r"(?:宅地|田|畑|山林|雑種地).{0,120}?(\d{2,6})[\.:](\d{2})",title,re.S)
    if not right:return {"status":"not_leasehold","leasehold":None,"warnings":[]}
    warnings=[]
    if rent:warnings.append("地代は3.3㎡当たりの単価表記です。住戸の月額総額は地主または借地説明書で確認してください。")
    if not start or not years:warnings.append("借地期間を確定できません。土地謄本の地上権・賃借権設定を確認してください。")
    return {"status":"needs_review" if warnings else "parsed","leasehold":{
      "right_type":right,"area":float(area.group(1)+"."+area.group(2)) if area else None,
      "area_basis":"登記簿" if area else None,"ground_rent_monthly":None,
      "ground_rent_unit_per_3_3sqm":int(rent.group(1).replace(",","")) if rent else None,
      "building_class":"堅固建物" if re.search(r"鉄骨|鉄筋|コンクリート",raw) else None,
      "law_type":"旧法" if start and start["西暦"]<="1992-07-31" else "新法" if start else None,
      "assignment_consent_required":False if right=="地上権" else None,
      "period_start":start,"period_end":_end(start,years),"period_years":years},"warnings":warnings}


def read_land_registry(pdf):
    p=Path(pdf)
    proc=subprocess.run(["pdftotext","-layout",str(p),"-"],capture_output=True,timeout=30)
    if proc.returncode:raise ValueError("土地謄本の文字を抽出できません。")
    text=proc.stdout.decode("utf-8",errors="replace")
    if len(text.strip())<100: return {"status":"needs_ocr","leasehold":None,"warnings":["画像PDFのためOCRまたはAI読取が必要です。"]}
    return parse_land_registry_text(text)
