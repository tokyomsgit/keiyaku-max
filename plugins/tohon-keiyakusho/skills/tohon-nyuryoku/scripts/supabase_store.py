"""Claudeの日本語JSONを変更せず、保存時のみDB形式へ変換する。"""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
import urllib.request
import urllib.error


class StoreError(Exception):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def dig(data, path):
    for part in path.split('.'):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def number(value):
    text = unicodedata.normalize('NFKC', str(value)).replace(':', '.')
    if not re.fullmatch(r'\d+(?:\.\d+)?', text):
        raise StoreError('数値を確認してください。DB保存を停止しました。')
    return float(text) if '.' in text else int(text)


def date(value):
    if not all(value.get(k) is not None for k in ('元号', '年', '月', '日')):
        return None
    starts = {'明治':1867,'大正':1911,'昭和':1925,'平成':1988,'令和':2018,'西暦':0}
    era = value['元号']
    if era not in starts:
        raise StoreError('建築時期の元号を確認してください。')
    y = 1 if str(value['年']) == '元' else int(value['年'])
    return dt.date(starts[era] + y, int(value['月']), int(value['日'])).isoformat()


def convert(data, *, house_number, building_name=None, active_mortgages=None, evidence=None):
    """完全な家屋番号は呼出側で原文確認した値を渡す。末尾から推測しない。"""
    house_number = unicodedata.normalize('NFKC', house_number or '').strip()
    suffix = dig(data, '専有部分.家屋番号_枝番')
    if not house_number or suffix is None or not house_number.endswith('の' + str(suffix)):
        raise StoreError('完全な家屋番号と中間JSONの枝番を確認してください。')
    b, u, values, warnings = {}, {'house_number':house_number}, [], []
    evidence = evidence or {}
    def add(table, column, value, path):
        if value is None or value == '':
            return
        (b if table == 'buildings' else u)[column] = copy.deepcopy(value)
        item = {'field_code':column, 'value':copy.deepcopy(value)}
        for key in ('confidence','source_text','page_no','value_as_of_date'):
            if evidence.get(path, {}).get(key) is not None:
                item[key] = evidence[path][key]
        values.append(item)
    add('units', 'house_number', house_number, 'house_number')
    mapping = json.loads(Path(__file__).with_name('db_mapping.json').read_text(encoding='utf8'))
    for path, spec in mapping.items():
        val = dig(data, path)
        if val is None or val == '':
            continue
        kind = spec.get('transform')
        if kind == 'location':
            main, branch = dig(data,'一棟の建物.所在_番'), dig(data,'一棟の建物.所在_枝番')
            if main is None or main == '':
                continue
            val = str(val) + str(main) + '番地' + str(branch or '') + str(dig(data,'一棟の建物.所在_追加') or '')
        elif kind == 'number': val = number(val)
        elif kind == 'date': val = date(val)
        elif kind == 'floor': val = str(val) if '階' in str(val) else str(val) + '階部分'
        elif kind == 'floors':
            val = [{'floor':str(x['階']), 'area':number(x['面積'])} for x in val if x.get('階') is not None and x.get('面積') is not None]
        elif kind == 'lands':
            val = [{out:x.get(key) for key,out in [('所在','location'),('地番','lot_number'),('地目','land_category'),('地積','area')]} for x in val]
            for x in val:
                if x['area'] is not None: x['area'] = number(x['area'])
            # Claude deliberately leaves the formula-fed first parcel's address blank.
            if val:
                val[0]['location'] = val[0]['location'] or dig(data,'一棟の建物.所在_市区町村町名')
                main, branch = dig(data,'一棟の建物.所在_番'), dig(data,'一棟の建物.所在_枝番')
                if not val[0]['lot_number'] and main is not None:
                    val[0]['lot_number'] = str(main)+'番'+str(branch or '')
        add(spec['table'], spec['column'], val, path)
    add('buildings','building_name',building_name,'building_name')
    # Absence of structured mortgage data must never mean 'no active mortgages'.
    if active_mortgages is not None:
        if not isinstance(active_mortgages,list): raise StoreError('抵当権情報の形式を確認してください。')
        add('units','active_mortgages',active_mortgages,'active_mortgages')
    else: warnings.append('抵当権は既存JSONに構造化項目がないため比較対象外です。')
    if data.get('敷地権') is True and data.get('土地'):
        for src,col in [('権利の種類','land_right_type'),('持分_分子','land_right_numerator'),('持分_分母','land_right_denominator')]:
            found = [x.get(src) for x in data['土地']]
            if all(x is not None and x != '' for x in found) and all(x == found[0] for x in found):
                add('units',col,number(found[0]) if col != 'land_right_type' else found[0],'土地.'+src)
            else: warnings.append('土地ごとの'+src+'が未確定または異なります。単一値には変換しません。')
    return {'building':b,'unit':u,'values':values,'warnings':warnings}


def make_payload(data, *, house_number, source_path=None, original_filename=None, file_hash=None,
                 source_type='seller_provided', status='provisional', as_of_date=None, **context):
    converted = convert(data, house_number=house_number, **context)
    if source_path:
        path = Path(source_path)
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        original_filename = path.name
    if not file_hash or not re.fullmatch('[0-9a-fA-F]{64}',file_hash):
        raise StoreError('原本ファイルまたはSHA-256ハッシュを指定してください。')
    if not original_filename: raise StoreError('原本ファイル名を指定してください。')
    if status not in ('provisional','confirmed','archived'): raise StoreError('資料の状態を確認してください。')
    if as_of_date: dt.date.fromisoformat(as_of_date)
    payload = {**converted,'raw_json':copy.deepcopy(data),'document':{
        'source_type':source_type or 'seller_provided','status':status,
        'as_of_date':as_of_date,'original_filename':Path(original_filename).name,'file_hash':file_hash.lower()}}
    payload['content_hash'] = hashlib.sha256(canonical(payload).encode('utf8')).hexdigest()
    return payload


def env(name):
    val = os.environ.get(name)
    if not val and os.name == 'nt':
        import winreg
        for hive,path in [(winreg.HKEY_CURRENT_USER,'Environment'),(winreg.HKEY_LOCAL_MACHINE,r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')]:
            try:
                with winreg.OpenKey(hive,path) as key: val = winreg.QueryValueEx(key,name)[0]
            except OSError: continue
            if val: break
    return val


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def rpc(payload):
    url, key = env('SUPABASE_URL'), env('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        raise StoreError('Supabaseの初期設定が完了していません。管理者へ連絡してください。')
    if not re.fullmatch(r'https://[a-z0-9]+\.supabase\.co/?',url):
        raise StoreError('Supabase接続先を確認してください。')
    request = urllib.request.Request(url.rstrip('/')+'/rest/v1/rpc/save_registry_import',
        data=canonical({'p':payload}).encode('utf8'),
        headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=60) as response:
            result = json.load(response)
        if not isinstance(result,dict) or not result.get('document_version_id'):
            raise ValueError()
        return result
    except (OSError,ValueError):
        raise StoreError('Supabaseに保存できませんでした。契約書の作成を停止しました。') from None


def save_to_supabase(data, **kwargs):
    payload = make_payload(data, **kwargs)
    result = rpc(payload)
    result['warnings'] = payload['warnings']
    return result
