"""登記情報提供サービスの全部事項PDFを、AIを使わず罫線表から読む。

extract_registry.call_ai と同じ形（API_SCHEMA）の読み取り結果を作り、その後の根拠照合・
normalize_document・integrate はAIの場合と同じ処理を通す。下線（抹消・変更された事項）の
文字は現在の値に使わない。
"""
import re
from fractions import Fraction

from normalize_registry import fraction
from registry_text import GAIJI, compact, read_pages, records

ERA = r'(?:明治|大正|昭和|平成|令和)(?:元|\d+)年\d+月\d+日'
AREA = re.compile(r'((?:地下)?\d+階)(?:部分)?([\d,]+):(\d{2})')
CATEGORIES = ('宅地', '田', '畑', '山林', '雑種地', '公衆用道路', '原野', '境内地', '墓地', '池沼', '水道用地',
              '用悪水路', '保安林', '学校用地', '鉄道用地', '井溝', '堤', '牧場', '塩田', '鉱泉地', 'ため池', 'ダム', '公園')


def node(value=None, sources=()):
    return {'value': value, 'sources': list(sources) if value is not None else []}


def blank_field():
    return node()


def area_of(text):
    """"199:00" -> 199.0; "61:" (a 公衆用道路 or 山林 area with no decimals) -> 61.0."""
    m = re.search(r'([\d,]+):(\d{2})?', text)
    return float(m[1].replace(',', '') + '.' + (m[2] or '0')) if m else None


def split_place(text):
    """"港区架空一丁目12番3" -> ("港区架空一丁目", "12番3"); keeps 番地 as written."""
    m = re.search(r'\d+番', text)
    return (text[:m.start()], text[m.start():]) if m else (text, None)


def body(rec, section, width=None):
    """Records of a section that are data rows (not the section heading or the column captions)."""
    out = []
    for r in rec:
        if r['section'] != section or r['heading']:
            continue
        if width and r['width'] != width:
            continue
        first = r['cells'][0].text
        if re.match(r'^[1①]?(順位番号|土地の符号|種類|構造|地番)', first) or first.startswith(('1構造', '1種類', '1土地の符号', '1地番')):
            continue
        out.append(r)
    return out


def labelled(rec, section, label):
    """The last value in effect for a "label | value" row (所在, 建物の名称, 家屋番号…).

    A change is printed as a following row with an empty label column, e.g.
    "所在|~港区架空一丁目12番地3|" then "|港区架空一丁目12番地3|平成24年5月7日変更".
    """
    found, current_label = None, None
    for r in rec:
        if r['section'] != section or r['heading'] or len(r['cells']) < 2:
            current_label = None
            continue
        first = r['cells'][0].text
        if first:
            current_label = first
        if current_label == label and r['cells'][1].current:
            found = r['cells'][1]
    return found


def spaced_name(raw):
    """Registry prints a person's name with a space between every character (e.g. "山　田　太　郎")."""
    s = raw.strip('　 ')
    return len(s) >= 3 and bool(re.fullmatch(r'\S(?:[　 ]\S)+', s))


CORPORATE = ('株式会社', '有限会社', '合同会社', '合資会社', '合名会社', '法人', '組合', '銀行', '信用金庫', '公社', '財団', '社団')


ADDRESS = re.compile(r'^(?:東京都|北海道|京都府|大阪府|.{2,3}県|[^\s\d]{1,5}[市区郡])')


def parse_people(cell):
    """Persons named in a 甲区 entry's 権利者その他の事項, using only characters still in effect."""
    people, person, ended = [], None, False
    for page, text, raw in cell.lines(current=True):
        if ended:
            break
        if text.startswith('原因'):
            continue
        if text.startswith(('順位', '付記')) or '移記' in text or text.startswith(('信託目録', '共同担保')):
            ended = True
            continue
        marker = re.match(r'^(所有者|共有者|受託者|権利者)', text)
        if marker:
            person = {'name': [], 'address': [], 'share': None, 'corporate': [], 'page': page}
            people.append(person)
            rest = text[marker.end():]
            if rest:
                person['address'].append((page, rest, raw))
            continue
        if person is None:
            continue
        if text.startswith('持分') or re.fullmatch(r'[\d,万億]+分の[\d,万億]+', text):
            if person['name']:
                # Co-owners at the same address are listed as "持分 / name" pairs under one address.
                person = {'name': [], 'address': list(person['address']), 'share': None, 'corporate': [], 'page': page}
                people.append(person)
            # Only the first co-owner's share carries the word 持分; the rest are bare fractions.
            person['share'] = (page, text.removeprefix('持分'), raw)
            continue
        if text.startswith('会社法人等番号'):
            person['corporate'].append((page, text[len('会社法人等番号'):], raw))
            continue
        if person['corporate'] and re.fullmatch(r'\d+', text):
            person['corporate'].append((page, text, raw))
            continue
        named = spaced_name(raw) or any(w in text for w in CORPORATE)
        if person['name'] and not named and ADDRESS.match(text):
            # 共有者 lists repeat "address / 持分 / name" under a single marker.
            person = {'name': [], 'address': [(page, text, raw)], 'share': None, 'corporate': [], 'page': page}
            people.append(person)
            continue
        # Once a name has started, later lines up to the next marker continue it (a wrapped corporate name).
        if person['name'] or named or person['share']:
            person['name'].append((page, text, raw))
            continue
        person['address'].append((page, text, raw))
    out = []
    for p in people:
        if not p['name'] and len(p['address']) > 1:
            p['name'] = [p['address'].pop()]
        if not p['name']:
            continue
        name = ''.join(t for _, t, _ in p['name'])
        address = ''.join(t for _, t, _ in p['address'])
        out.append({
            'name': node(name, [{'page': pg, 'text': raw} for pg, _, raw in p['name']]),
            'address': node(address or None, [{'page': pg, 'text': raw} for pg, _, raw in p['address']]),
            'share': node(p['share'][1], [{'page': p['share'][0], 'text': p['share'][2]}]) if p['share'] else blank_field(),
            'corporate_number': node(''.join(t for _, t, _ in p['corporate']) or None,
                                     [{'page': pg, 'text': raw} for pg, _, raw in p['corporate']]),
        })
    return out


def apply_change(detail, holders):
    """Apply a 登記名義人住所・氏名変更 to the holders it names. False when it names nobody we hold."""
    lines = [(pg, t, raw) for pg, t, raw in detail.lines() if not t.startswith('原因') and not re.fullmatch(ERA + '(付記|.*(変更|移転|実施|更正|取得))', t)]
    joined = ''.join(t for _, t, _ in lines)
    applied = False
    # 共有者 form: "共有者Xの住所…" (one clause per co-owner)
    for h in holders:
        n = compact(h['name']['value'])
        m = re.search(r'(?:共有者)?' + re.escape(n) + r'の(住所|本店)(氏名|商号)?(.+?)(?=(?:共有者)?[^\d\s]{1,20}?の(?:住所|本店)|$)', joined)
        if m and not m[2]:
            h['address'] = node(m[3], detail.sources())
            applied = True
    if applied or len(holders) != 1:
        return applied or not re.search(r'の(住所|本店)', joined)
    # Single holder form: "住所…", "本店…", "氏名…", "住所氏名<address><spaced name>"
    start = next((i for i, (_, t, _) in enumerate(lines) if re.match(r'^(住所|本店|氏名|商号)', t)), None)
    if start is None:
        return False
    head = re.match(r'^((?:住所|本店|氏名|商号)+)', lines[start][1])[1]
    rest = [(pg, t[len(head):] if i == 0 else t, raw) for i, (pg, t, raw) in enumerate(lines[start:])]
    rest = [x for x in rest if x[1]]
    names = [x for x in rest if spaced_name(x[2]) or any(w in x[1] for w in CORPORATE)] if re.search('氏名|商号', head) else []
    if re.search('住所|本店', head) and names:
        address = [x for x in rest if x not in names]
    elif re.search('住所|本店', head):
        address, names = rest, []
    else:
        address, names = [], rest
    h = holders[0]
    if address:
        h['address'] = node(''.join(t for _, t, _ in address), [{'page': pg, 'text': raw} for pg, _, raw in address])
    if names:
        h['name'] = node(''.join(t for _, t, _ in names), [{'page': pg, 'text': raw} for pg, _, raw in names])
    return bool(address or names)


def share_of(text):
    pair = fraction(text) if text else None
    return Fraction(*pair) if pair else None


def ownership(rec, warnings, review):
    """Replay 甲区 in order and return the current owners with their shares.

    Entries whose 登記の目的 is underlined were cancelled and are skipped. Anything the ledger
    cannot apply exactly (unknown transferor, 仮登記, shares not totalling 1) is sent to review.
    """
    # One lot per acquisition, so "持分全部(順位N番で登記した持分)移転" can remove just that lot.
    lots = []
    uncertain = False

    def of(name, ranks=()):
        found = [x for x in lots if compact(x['name']['value']) == compact(name)]
        return [x for x in found if x['rank']['value'] in ranks] if ranks else found

    for r in body(rec, 'A', 4):
        rank_cell, purpose_cell, _, detail = r['cells']
        if purpose_cell.struck:
            continue
        purpose, rank = purpose_cell.current, rank_cell.current
        people = parse_people(detail)
        for p in people:
            p['rank'] = node(rank, rank_cell.sources())
            p['fraction'] = share_of(p['share']['value'])
            p['doubt'] = False
        if any(w in purpose for w in ('仮登記', '差押', '仮差押', '仮処分', '買戻', '競売')):
            if '抹消' not in purpose:
                warnings.append(f'甲区{rank}番: {purpose}')
                for x in lots:
                    if compact(x['name']['value']) in purpose:
                        x['doubt'] = True
            continue
        if '抹消' in purpose or '更正' in purpose and '登記名義人' not in purpose:
            if re.match(r'\d+番(所有権|.*持分)', purpose):
                uncertain = True
            continue
        if '登記名義人' in purpose and re.search(r'(変更|更正)$', purpose):
            if not apply_change(detail, lots):
                uncertain = True
            continue
        if purpose in ('所有権保存', '所有権移転', '共有者全員持分全部移転') or purpose.endswith(('所有権移転', '所有権登記')) and '持分' not in purpose:
            # A whole transfer replaces every earlier holder, so earlier doubts no longer matter.
            lots, uncertain = people, not people
            if len(lots) == 1 and lots[0]['fraction'] is None:
                lots[0]['fraction'] = Fraction(1)
            continue
        if purpose == '所有権一部移転' and len({compact(x['name']['value']) for x in lots}) == 1:
            # A sole owner passing part of the whole: the same as that owner's 持分一部移転.
            purpose = lots[0]['name']['value'] + '持分一部移転'
        m = re.fullmatch(r'(.+?)持分(全部|一部)(?:\(([^)]*)\))?移転', purpose)
        if m and not re.search(r'分の', m[1]):
            refs = tuple(re.findall(r'(\d+)番', m[3] or ''))
            names = [x for x in re.split(r'、|及び', re.sub(r'^共有者', '', m[1])) if x]
            given = [x for n in names for x in of(n, refs)]
            if not given or not people:
                uncertain = True
            if m[2] == '全部':
                total = sum(x['fraction'] for x in given) if given and all(x['fraction'] is not None for x in given) else None
                lots = [x for x in lots if x not in given]
                if len(people) == 1 and people[0]['fraction'] is None:
                    people[0]['fraction'] = total
                    people[0]['doubt'] = total is None
            else:
                moved = sum(p['fraction'] for p in people) if all(p['fraction'] is not None for p in people) else None
                if len(given) == 1 and given[0]['fraction'] is not None and moved is not None:
                    given[0]['fraction'] -= moved
                    given[0]['doubt'] = True if given[0]['fraction'] < 0 else given[0]['doubt']
                    given[0]['reduced'] = True
                    if given[0]['fraction'] == 0:
                        lots.remove(given[0])
                else:
                    for x in given:
                        x['doubt'] = True
            lots += people
            continue
        if '信託' in purpose:
            continue
        if '移転' in purpose or '保存' in purpose:
            uncertain = True
            for x in lots:
                if compact(x['name']['value']) in purpose:
                    x['doubt'] = True
            warnings.append(f'甲区{rank}番: 未対応の登記の目的 {purpose}')
    if lots and (any(x['fraction'] is None for x in lots) or sum(x['fraction'] or 0 for x in lots) != 1):
        uncertain = True
    # Merge each person's lots back into one holder.
    holders = []
    for x in lots:
        same = [h for h in holders if compact(h['name']['value']) == compact(x['name']['value'])
                and compact(h['address']['value'] or '') == compact(x['address']['value'] or '')]
        if same:
            h = same[0]
            h['fraction'] = None if h['fraction'] is None or x['fraction'] is None else h['fraction'] + x['fraction']
            h['doubt'] = h['doubt'] or x['doubt']
            h['share'] = node(h['share']['value'], h['share']['sources'] + x['share']['sources'])
            h['reduced'] = True
        else:
            holders.append(x)
    for i, h in enumerate(holders):
        f, doubt, reduced = h.pop('fraction'), h.pop('doubt'), h.pop('reduced', False)
        if len(holders) == 1 and f == 1:
            h['share'] = blank_field()
        elif f is not None and (reduced or f != share_of(h['share']['value'])):
            # A share the ledger had to add up or reduce is not printed anywhere, so it is reviewed.
            # It keeps the printed denominator when it can (10000分の200, not 50分の1).
            printed = fraction(h['share']['value'] or '')
            den = printed[1] if printed and (f * printed[1]).denominator == 1 else f.denominator
            h['share'] = node(f'{den}分の{f * den}', h['share']['sources'])
            doubt = True
        if doubt or f is None:
            review.append(f'owners.{i}.share')
    if uncertain:
        review.append('owners')
    return holders


def mortgages(rec):
    """乙区 mortgages: an entry whose 登記の目的 is underlined was cancelled."""
    out = []
    for r in body(rec, 'B', 4):
        rank_cell, purpose_cell, date_cell, detail = r['cells']
        purpose = purpose_cell.text
        if '抵当権設定' not in purpose:
            continue
        text = detail.text
        item = {'rank': node(rank_cell.text, rank_cell.sources(current=False)),
                'kind': node(purpose, purpose_cell.sources(current=False)),
                'active': node(not purpose_cell.struck, purpose_cell.sources(current=False))}
        amount = re.search(r'(?:債権額|極度額)(金[\d,]+(?:億)?(?:[\d,]+)?万?円)', detail.current or text)
        item['amount'] = node(amount[1], detail.sources(current=False)) if amount else blank_field()
        debtor = re.search(r'債務者(.+?)(?=(?:根)?抵当権者|$)', text)
        item['debtor'] = node(debtor[1], detail.sources(current=False)) if debtor else blank_field()
        creditor = re.search(r'(?:(?:根)?抵当権者|権利者)(.+?)(?=共同担保|順位|$)', text)
        item['creditor'] = node(creditor[1], detail.sources(current=False)) if creditor else blank_field()
        item['cancellation'] = blank_field()
        out.append(item)
    return out


def leasehold(rec):
    for r in body(rec, 'B', 4):
        purpose = r['cells'][1]
        if purpose.struck:
            continue
        for kind in ('地上権', '賃借権'):
            if kind + '設定' in purpose.current:
                return {'exists': node(True, purpose.sources()), 'type': node(kind, purpose.sources()), 'details': blank_field()}
    return {'exists': blank_field(), 'type': blank_field(), 'details': blank_field()}


def walk(node, path=''):
    """(path, value) for every field, with paths as normalize_registry.fields writes them."""
    if isinstance(node, dict) and 'value' in node and 'sources' in node:
        yield path, node['value']
    elif isinstance(node, dict):
        for k, v in node.items():
            if k not in ('warnings', 'review_fields'):
                yield from walk(v, (path + '.' + k).strip('.'))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, path + '.' + str(i))


def read(path):
    """(raw, pages): raw in extract_registry.API_SCHEMA, pages as extract_registry.prepare_pdf returns."""
    return from_pages(read_pages(path))


def from_pages(pages):
    """read() for pages already rebuilt by registry_text.read_pages (or built by a test)."""
    rec = records(pages)
    sections = {r['section'] for r in rec}
    warnings, review = [], []
    raw = {
        'building': {'location': blank_field(), 'lot_number': blank_field(), 'name': blank_field(), 'structure': blank_field(),
                     'total_floor_area': blank_field(), 'floor_areas': []},
        'unit': {k: blank_field() for k in ('house_number', 'name', 'type', 'structure', 'floor', 'registered_area', 'built_date')},
        'owner': {'name': blank_field(), 'address': blank_field()},
        'lands': [],
        'land_right': {'exists': blank_field(), 'type': blank_field(), 'share': blank_field()},
        'mortgages': [],
        'warnings': warnings,
        'document_type': blank_field(), 'property_type': blank_field(), 'tenure_type': blank_field(),
        'owners': [],
        'main_building': {**{k: blank_field() for k in ('location', 'house_number', 'type', 'structure', 'built_date')}, 'floor_areas': []},
        'annex_buildings': [],
        'leasehold': {'exists': blank_field(), 'type': blank_field(), 'details': blank_field()},
        'review_fields': review,
    }
    if 'unit' in sections:
        raw['document_type'] = node('building', [{'page': 1, 'text': '専有部分の建物の表示'}])
        cell = labelled(rec, 'building', '所在')
        if cell:
            places = [split_place(p) for p in re.split(r'、', cell.current)]
            # "架空一丁目12番地3、12番地4": later lots of the same place have no place name.
            filled, last = [], ''
            for place, lot in places:
                place = place or last
                last = place
                filled.append((place, lot))
            locs = list(dict.fromkeys(p for p, _ in filled))
            lots = [lot for _, lot in filled if lot]
            if len(locs) == 1:
                raw['building']['location'] = node(locs[0], cell.sources())
                raw['building']['lot_number'] = node('、'.join(lots) or None, cell.sources())
            else:
                raw['building']['location'] = node('\n'.join(p for p, _ in filled), cell.sources())
                raw['building']['lot_number'] = node('\n'.join(l or '' for _, l in filled), cell.sources())
        cell = labelled(rec, 'building', '建物の名称')
        if cell:
            raw['building']['name'] = node(cell.current, cell.sources())
        for r in body(rec, 'building', 3):
            structure, floors, _ = r['cells']
            if '造' in structure.current:
                raw['building']['structure'] = node(structure.current, structure.sources())
            areas = []
            for page, text, raw_text in floors.lines():
                for m in AREA.finditer(text):
                    areas.append({'floor': node(m[1], [{'page': page, 'text': raw_text}]),
                                  'area': node(float(m[2].replace(',', '') + '.' + m[3]), [{'page': page, 'text': raw_text}])})
            if areas:
                raw['building']['floor_areas'] = areas
        cell = labelled(rec, 'unit', '家屋番号')
        if cell:
            raw['unit']['house_number'] = node(cell.current, cell.sources())
        cell = labelled(rec, 'unit', '建物の名称')
        if cell:
            raw['unit']['name'] = node(cell.current, cell.sources())
        for r in body(rec, 'unit', 4):
            kind, structure, area, cause = r['cells']
            if kind.current and not kind.struck:
                raw['unit']['type'] = node(kind.current, kind.sources())
            if '造' in structure.current:
                raw['unit']['structure'] = node(structure.current, structure.sources())
            m = AREA.search(area.current)
            if m:
                raw['unit']['floor'] = node(m[1], area.sources())
                raw['unit']['registered_area'] = node(float(m[2].replace(',', '') + '.' + m[3]), area.sources())
            m = re.search('(' + ERA + ')新築', cause.current)
            if m:
                raw['unit']['built_date'] = node(m[1], cause.sources())
        lands = {}
        for r in body(rec, 'site', 5):
            symbol, place, category, area, _ = r['cells']
            key = symbol.current or symbol.text
            land = lands.setdefault(key, {'identifier': node(key, symbol.sources(current=False)), 'location': blank_field(),
                                          'lot_number': blank_field(), 'category': blank_field(), 'area': blank_field(),
                                          'right_type': blank_field(), 'right_share': blank_field()})
            if place.current:
                loc, lot = split_place(place.current)
                land['location'] = node(loc, place.sources())
                land['lot_number'] = node(lot, place.sources())
            if category.current:
                land['category'] = node(category.current, category.sources())
            if area_of(area.current) is not None:
                land['area'] = node(area_of(area.current), area.sources())
        rights = []
        for r in body(rec, 'land_right', 4):
            symbol, kind, share, _ = r['cells']
            if kind.struck or not kind.current:
                continue
            rights.append((symbol.current, kind, share))
            for key in re.split(r'[・、]', symbol.current):
                if key in lands:
                    lands[key]['right_type'] = node(kind.current, kind.sources())
                    lands[key]['right_share'] = node(share.current, share.sources())
        raw['lands'] = list(lands.values())
        if len(raw['lands']) > 6:
            warnings.append(f'敷地の土地が{len(raw["lands"])}筆あります（契約書は6筆まで）')
        if rights:
            raw['land_right']['exists'] = node(True, rights[0][1].sources())
            if len({k.current for _, k, _ in rights}) == 1:
                raw['land_right']['type'] = node(rights[0][1].current, rights[0][1].sources())
            if len({s.current for _, _, s in rights}) == 1:
                raw['land_right']['share'] = node(rights[0][2].current, rights[0][2].sources())
        elif 'land_right' not in sections:
            raw['land_right']['exists'] = node(False, [{'page': 1, 'text': '専有部分の建物の表示'}])
    elif 'land' in sections:
        raw['document_type'] = node('land', [{'page': 1, 'text': '土地の表示'}])
        raw['property_type'] = node('land_only', [{'page': 1, 'text': '土地の表示'}])
        land = {'identifier': blank_field(), 'location': blank_field(), 'lot_number': blank_field(), 'category': blank_field(),
                'area': blank_field(), 'right_type': blank_field(), 'right_share': blank_field()}
        cell = labelled(rec, 'land', '所在')
        if cell:
            land['location'] = node(cell.current, cell.sources())
        for r in body(rec, 'land', 4):
            lot, category, area, _ = r['cells']
            if re.fullmatch(r'\d+番\d*', lot.current or ''):
                land['lot_number'] = node(lot.current, lot.sources())
            if category.current in CATEGORIES:
                land['category'] = node(category.current, category.sources())
            if area_of(area.current) is not None:
                land['area'] = node(area_of(area.current), area.sources())
        raw['lands'] = [land]
    elif 'house' in sections:
        raw['document_type'] = node('building', [{'page': 1, 'text': '主である建物の表示'}])
        raw['property_type'] = node('detached_house', [{'page': 1, 'text': '主である建物の表示'}])
    else:
        raw['document_type'] = node('unknown', [{'page': 1, 'text': pages[0]['text'][:20] if pages else ''}])
        warnings.append('登記事項証明書の表題部を判定できません')

    owners = ownership(rec, warnings, review)
    raw['owners'] = owners
    if owners and 'owners' not in review:
        raw['owner']['name'] = node('\n'.join(o['name']['value'] for o in owners), [s for o in owners for s in o['name']['sources']])
        addresses = [o['address']['value'] for o in owners]
        if all(addresses):
            raw['owner']['address'] = node('\n'.join(addresses), [s for o in owners for s in o['address']['sources']])
    raw['mortgages'] = mortgages(rec)
    raw['leasehold'] = leasehold(rec)
    if raw['leasehold']['exists']['value'] or raw['land_right']['type']['value'] in ('地上権', '賃借権'):
        raw['tenure_type'] = node('leasehold', raw['leasehold']['type']['sources'] or raw['land_right']['type']['sources'])
    if '閉鎖' in compact(''.join(p['text'] for p in pages[:1])):
        warnings.append('閉鎖登記簿の可能性があります')
        review.append('document_type')
    if any(p.get('old_numerals') for p in pages):
        warnings.append('旧字体の漢数字（壱・弐・参など）を算用数字に置き換えて読みました')
    for path, value in walk(raw):
        if isinstance(value, str) and GAIJI.search(value):
            review.append(path)
            warnings.append(f'{path}: 外字（表示できない文字）を含むため原本で確認してください')
    for page in pages:
        page.pop('lines', None)
    return raw, pages
