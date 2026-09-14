"""Build the public demo from explicitly fictional values only. No private inputs."""
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'public-demo-dist'


def fixture():
    def field(code,label,value,review=False):
        return {'code':code,'label':label,'value':value,'confidence':None if review else .99,
          'needs_review':review,'source_text':'公開用の架空データ：'+(label+'の表示例' if isinstance(value,(list,dict)) else str(value)) if value is not None else None,
          'page_no':1,'value_as_of_date':'2026-01-31','excel_supported':True}
    registry=[field(*x) for x in [
      ('building_name','建物名','サンプルマンション'),('unit_name','号室','704'),
      ('registry_location','登記上の所在','デモ県サンプル市架空町一丁目'),
      ('house_number','家屋番号','架空町一丁目999番9の704'),('building_structure','一棟の構造','鉄筋コンクリート造陸屋根10階建'),
      ('floor_areas','各階床面積',[{'階':'1階','面積':200.00},{'階':'2〜10階','各階面積':180.00}]),
      ('unit_type','建物の種類','居宅'),('unit_structure','専有部分の構造','鉄筋コンクリート造1階建'),
      ('unit_floor','所在階','7階'),('registered_area','登記面積',55.55),('built_date','新築年月日','2000-01-01'),
      ('current_owner_name','現在の所有者','サンプル所有者株式会社（架空）'),
      ('current_owner_address','所有者住所','デモ県サンプル市架空町2-2-2'),
      ('land_lots','土地',[{'所在':'デモ県サンプル市架空町','地番':'999番9','地目':'宅地','地積':800.00}]),
      ('has_land_right','敷地権の有無',True),('land_right_type','敷地権の種類','所有権'),
      ('land_right_numerator','敷地権割合（分子）',100),('land_right_denominator','敷地権割合（分母）',10000),
      ('active_mortgages','抵当権',[{'抵当権者':'デモ銀行（架空）','債権額':'公開用ダミー・取引情報なし'}])]]
    report=[field(*x) for x in [
      ('building_name','建物名','サンプルマンション'),('unit_name','号室','704'),
      ('management_fee','月額管理費（円）',12000),('repair_reserve_fee','月額修繕積立金（円）',10000),
      ('management_company','管理会社','サンプル管理株式会社（架空）'),('total_units','総戸数',48),
      ('management_type','管理形態','全部委託'),('management_association','管理組合','サンプル管理組合（架空）'),
      ('unit_arrears','対象住戸の滞納',None,True),('other_monthly_fees','その他月額費用',None,True),
      ('parking_facility_info','駐車場','空き状況は要確認',True),('pet_restrictions','ペット制限','飼育細則の原本確認が必要',True),
      ('major_repair_plan','大規模修繕予定','2027年度実施予定（架空の例）'),
      ('fee_change_plans','費用変更予定','管理費改定のサンプル差分があります')]]
    for f in report:f['excel_supported']=f['code'] in ('building_name','unit_name')
    docs=[{'id':t,'version_id':t+'-v1','type':t,'filename':name,'version':1,'date':'2026-01-31','fields':fields}
      for t,name,fields in [('registry','公開用デモ謄本（架空）',registry),('important_report','公開用デモ重調（架空）',report)]]
    diffs=[{'id':'demo-'+code,'code':code,'label':label,'old_value':old,'new_value':new,
      'review_status':'unreviewed','can_adopt':True,'source':'公開用の架空差分・実取引情報ではありません'}
      for code,label,old,new in [('management_fee','管理費',12000,13500),
        ('current_owner_name','所有者','サンプル所有者株式会社（架空）','デモ所有者株式会社（架空）')]]
    c={'id':'demo-case','unit_id':'public-demo-unit','building_name':'サンプルマンション','unit_name':'704号室',
      'address':'デモ県サンプル市架空町1-1-1','owner':'サンプル所有者株式会社（架空）','area':55.55,
      'status':'公開デモ','updated_at':'2026-01-31','documents':docs,'diffs':diffs,'diff_count':2,
      'review_count':sum(f['needs_review'] for d in docs for f in d['fields']),
      'confirmed_values':{'management_fee':12000,'current_owner_name':'サンプル所有者株式会社（架空）'}}
    return {'public_demo':True,'mode':'demo','db_write_enabled':False,'cases':[c],'unmatched':[],
      'usage':{'ai_calls':0,'db_reads':0,'db_writes':0}}


def build():
    OUT.mkdir(exist_ok=True)
    assets={'index.html':(ROOT/'web/demo-experience.html').read_text(encoding='utf8'),
            'app.js':(ROOT/'web/demo-experience.js').read_text(encoding='utf8')}
    # Publish the same styles as one asset; keep editable source files separate.
    assets['style.css']='\n'.join((ROOT/'web/styles'/f'{name}.css').read_text(encoding='utf8') for name in ('theme','base','layout','components'))
    assets['style.css']+='\n'+(ROOT/'web/demo-experience.css').read_text(encoding='utf8')
    forbidden=r'(?i)(SUPABASE_SERVICE_ROLE_KEY|sk-proj-|sb_secret_|eyJ[a-zA-Z0-9_-]{20}|(?<![a-z])[A-Z]:[\\/]|127\.0\.0\.1|localhost|\.env|NITOH|東京都|文京区|渋谷区|日本管財)'
    for name,content in assets.items():
        if re.search(forbidden,content):raise ValueError('Publish audit failed: '+name)
    # Remove only the obsolete, known generated demo assets.
    for obsolete in ('demo.json','public-demo.js'):
        (OUT/obsolete).unlink(missing_ok=True)
    if any(p.name not in {*assets,'demo-contract.xlsx'} or not p.is_file() for p in OUT.iterdir()):raise ValueError('Unexpected publish artifact')
    import zipfile
    workbook=ROOT/'web/demo-contract.xlsx'
    with zipfile.ZipFile(workbook) as z:
        for name in z.namelist():
            if 'externalLinks' in name or 'vbaProject' in name:raise ValueError('Unsafe demo workbook')
            if name.endswith(('.xml','.rels')) and re.search(forbidden,z.read(name).decode('utf8')):raise ValueError('Workbook privacy audit failed')
    for name,content in assets.items():(OUT/name).write_text(content,encoding='utf8')
    (OUT/'demo-contract.xlsx').write_bytes(workbook.read_bytes())
    print('Public demo build and privacy audit: PASS (4 static files, no API/DB access)')


if __name__=='__main__':build()
