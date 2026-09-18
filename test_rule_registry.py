"""Rule-based 謄本 reading (reader/rule_registry.py) on fictional pages in the 登記情報提供サービス layout.

No PDF and no AI: pages are built the way registry_text.read_pages rebuilds them, with "~" marking
underlined (抹消・変更された) characters. All names and places are made up.
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

READER = Path(__file__).resolve().parent / 'reader'
if str(READER) not in sys.path:
    sys.path.insert(0, str(READER))

from extract_registry import API_SCHEMA, validate_evidence
from normalize_registry import blank, f, fraction, normalize_document
from registry_text import GAIJI, arabic, is_service_pdf, old_numerals
from rule_registry import from_pages
from verify_all import integrate


def page(text, number=1):
    """A page from lines where ~…~ marks underlined characters."""
    lines = []
    for raw in text.strip('\n').splitlines():
        chars, flags, under = [], [], False
        for ch in raw.strip():
            if ch == '~':
                under = not under
                continue
            chars.append(ch)
            flags.append(under)
        lines.append((''.join(chars), flags))
    return {'page': number, 'mode': 'text', 'text': '\n'.join(t for t, _ in lines), 'lines': lines}


CONDO = '''
┏━━━━━━━━━━━━━━━━━━━━━━┓
┃　表　　題　　部　　（一棟の建物の表示）　│調製│　│所在図番号│　┃
┠──────────────────────┨
┃所　　　在│港区架空一丁目　１２番地３、１２番地４　│　┃
┠──────────────────────┨
┃建物の名称│テストマンション　│　┃
┠──────────────────────┨
┃　①　構　造　│　②　床　面　積　㎡　│原因及びその日付〔登記の日付〕┃
┠──────────────────────┨
┃鉄筋コンクリート造陸屋根５階建│　１階　　１００：５０│〔平成１０年１月２０日〕┃
┃　│　２階　　　９８：２５│　┃
┠──────────────────────┨
┃　表　　題　　部　　（敷地権の目的である土地の表示）　┃
┠──────────────────────┨
┃①土地の符号│②　所　在　及　び　地　番│③地　目│④　地　積　㎡│登　記　の　日　付┃
┠──────────────────────┨
┃１│港区架空一丁目１２番３│宅地│　３００：００│平成１０年１月２０日┃
┠──────────────────────┨
┃２│港区架空一丁目１２番４│宅地│　　５０：１５│平成１０年１月２０日┃
┗━━━━━━━━━━━━━━━━━━━━━━┛
┏━━━━━━━━━━━━━━━━━━━━━━┓
┃　表　　題　　部　　（専有部分の建物の表示）　│不動産番号│０１２３┃
┠──────────────────────┨
┃家屋番号│架空一丁目　１２番３の３０１　│　┃
┠──────────────────────┨
┃建物の名称│３０１　│　┃
┠──────────────────────┨
┃①　種　類│②　構　造│③　床　面　積　㎡│原因及びその日付〔登記の日付〕┃
┠──────────────────────┨
┃居宅│鉄筋コンクリート造１階建│　３階部分　　６０：１２│平成１０年１月１０日新築┃
┠──────────────────────┨
┃　表　　題　　部　　（敷地権の表示）　┃
┠──────────────────────┨
┃①土地の符号│②敷地権の種類│③　敷　地　権　の　割　合│原因及びその日付〔登記の日付〕┃
┠──────────────────────┨
┃１・２│所有権│　１０万分の５０００│平成１０年１月１５日敷地権┃
┗━━━━━━━━━━━━━━━━━━━━━━┛
┏━━━━━━━━━━━━━━━━━━━━━━┓
┃　権　　利　　部　（　甲　区　）　　（所　有　権　に　関　す　る　事　項）┃
┠──────────────────────┨
┃順位番号│登　記　の　目　的│受付年月日・受付番号│権　利　者　そ　の　他　の　事　項┃
┠──────────────────────┨
┃１│所有権保存│平成１０年２月１日│原因　平成１０年２月１日売買┃
┃　│　│第１号│所有者　~港区架空二丁目１番１号~┃
┃　│　│　│　山　田　太　郎┃
┃　├──────┼──────┼──────┨
┃付記１号│１番登記名義人住所変更│平成２０年１月８日│原因　平成１９年１２月１日住所移転┃
┃　│　│第２号│住所　港区架空三丁目２番２号┃
┗━━━━━━━━━━━━━━━━━━━━━━┛
┏━━━━━━━━━━━━━━━━━━━━━━┓
┃　権　　利　　部　（　乙　区　）　　（所　有　権　以　外　の　権　利　に　関　す　る　事　項）┃
┠──────────────────────┨
┃順位番号│登　記　の　目　的│受付年月日・受付番号│権　利　者　そ　の　他　の　事　項┃
┠──────────────────────┨
┃~１~│~抵当権設定~│~平成１０年２月１日~│~債権額　金１，０００万円~┃
┃　│　│　│~抵当権者　港区架空四丁目１番１号　架空銀行株式会社~┃
┠──────────────────────┨
┃２│１番抵当権抹消│平成１５年１月１日│原因　平成１５年１月１日解除┃
┠──────────────────────┨
┃３│抵当権設定│平成２０年３月１日│原因　平成２０年３月１日金銭消費貸借同日設定┃
┃　│　│第３号│債権額　金２，０００万円┃
┃　│　│　│抵当権者　港区架空五丁目１番１号　架空信用金庫┃
┗━━━━━━━━━━━━━━━━━━━━━━┛
'''

LAND = '''
┏━━━━━━━━━━━━━━━━━━━━━━┓
┃　表　　題　　部　　（土地の表示）　│調製│　│不動産番号│０９９┃
┠──────────────────────┨
┃所　　在│港区架空一丁目　│　┃
┠──────────────────────┨
┃　①　地　番　│②地　目│　③　地　積　㎡　│原因及びその日付〔登記の日付〕┃
┠──────────────────────┨
┃~１２番３~│宅地│　~３１０：００~│　┃
┠──────────────────────┨
┃１２番３│　│　３００：００│③錯誤〔平成５年１月１日〕┃
┗━━━━━━━━━━━━━━━━━━━━━━┛
┏━━━━━━━━━━━━━━━━━━━━━━┓
┃　権　　利　　部　（　甲　区　）　　（所　有　権　に　関　す　る　事　項）┃
┠──────────────────────┨
┃順位番号│登　記　の　目　的│受付年月日・受付番号│権　利　者　そ　の　他　の　事　項┃
┠──────────────────────┨
┃１│所有権保存│昭和５０年１月１日│所有者　港区架空一丁目１番１号┃
┃　│　│第１号│　架空建設株式会社┃
┠──────────────────────┨
┃２│架空建設株式会社持分一部移転│昭和５０年２月１日│原因　昭和５０年２月１日売買┃
┃　│　│第２号│共有者　港区架空二丁目１番１号┃
┃　│　│　│　持分１万分の２５７┃
┃　│　│　│　甲　野　一　郎┃
┃　│　│　│　港区架空二丁目１番２号┃
┃　│　│　│　１万分の３００┃
┃　│　│　│　乙　野　花　子┃
┠──────────────────────┨
┃３│甲野一郎持分全部移転│平成１０年１月１日│原因　平成１０年１月１日売買┃
┃　│　│第３号│共有者　港区架空三丁目１番１号┃
┃　│　│　│　持分１万分の２５７┃
┃　│　│　│　株式会社テスト不動産┃
┠──────────────────────┨
┃４│乙野花子持分一部（順位２番で登記した持分）移転│平成２０年１月１日│原因　平成２０年１月１日売買┃
┃　│　│第４号│共有者　港区架空四丁目１番１号┃
┃　│　│　│　持分１万分の１００┃
┃　│　│　│　丙　野　次　郎┃
┗━━━━━━━━━━━━━━━━━━━━━━┛
'''


def v(node, path):
    for key in path.split('.'):
        node = node[int(key)] if isinstance(node, list) else node[key]
    return node['value']


def finish(raw, pages):
    """The rest of extract_registry.extract_by_rules: evidence check and normalization."""
    data = validate_evidence(copy.deepcopy(raw), pages)
    data = normalize_document(data, pages, 'fictional.pdf', table_read=True)
    data['metadata'] = {'source_pdf': 'fictional.pdf'}
    return data


class CondominiumTest(unittest.TestCase):
    def setUp(self):
        self.pages = [page(CONDO)]
        self.raw, _ = from_pages(copy.deepcopy(self.pages))

    def test_title_parts(self):
        raw = self.raw
        self.assertEqual(v(raw, 'building.location'), '港区架空一丁目')
        self.assertEqual(v(raw, 'building.lot_number'), '12番地3、12番地4')
        self.assertEqual(v(raw, 'building.name'), 'テストマンション')
        self.assertEqual(v(raw, 'building.structure'), '鉄筋コンクリート造陸屋根5階建')
        self.assertEqual([(v(x, 'floor'), v(x, 'area')) for x in raw['building']['floor_areas']], [('1階', 100.5), ('2階', 98.25)])
        self.assertEqual(v(raw, 'unit.house_number'), '架空一丁目12番3の301')
        self.assertEqual(v(raw, 'unit.name'), '301')
        self.assertEqual(v(raw, 'unit.type'), '居宅')
        self.assertEqual((v(raw, 'unit.floor'), v(raw, 'unit.registered_area')), ('3階', 60.12))
        self.assertEqual(v(raw, 'unit.built_date'), '平成10年1月10日')

    def test_land_right_maps_to_each_site_parcel(self):
        raw = self.raw
        self.assertIs(v(raw, 'land_right.exists'), True)
        self.assertEqual(v(raw, 'land_right.type'), '所有権')
        self.assertEqual([(v(x, 'lot_number'), v(x, 'area'), v(x, 'right_share')) for x in raw['lands']],
                         [('12番3', 300.0, '10万分の5000'), ('12番4', 50.15, '10万分の5000')])

    def test_underlined_address_is_replaced_by_its_change_and_cancelled_mortgage_is_inactive(self):
        raw = self.raw
        self.assertEqual(v(raw, 'owner.name'), '山田太郎')
        self.assertEqual(v(raw, 'owner.address'), '港区架空三丁目2番2号')
        self.assertEqual([(v(m, 'rank'), v(m, 'active')) for m in raw['mortgages']], [('1', False), ('3', True)])
        self.assertEqual(v(raw['mortgages'][1], 'amount'), '金2,000万円')

    def test_every_value_survives_the_evidence_check(self):
        data = finish(self.raw, self.pages)
        self.assertEqual(v(data, 'property_type'), 'condominium_land_right')
        self.assertEqual(v(data, 'owner.address'), '港区架空三丁目2番2号')
        self.assertEqual(v(data, 'unit.registered_area'), 60.12)
        self.assertEqual((v(data, 'lands.0.share_numerator'), v(data, 'lands.0.share_denominator')), (5000, 100000))
        self.assertFalse([w for w in data['history']['extraction_warnings'] if '根拠不備' in w])


class LandLedgerTest(unittest.TestCase):
    def setUp(self):
        self.pages = [page(LAND)]
        self.raw, _ = from_pages(copy.deepcopy(self.pages))

    def test_current_title_values_skip_underlined_ones(self):
        land = self.raw['lands'][0]
        self.assertEqual((v(land, 'location'), v(land, 'lot_number'), v(land, 'category'), v(land, 'area')),
                         ('港区架空一丁目', '12番3', '宅地', 300.0))

    def test_ledger_replays_partial_and_rank_scoped_transfers(self):
        owners = {v(o, 'name'): v(o, 'share') for o in self.raw['owners']}
        self.assertEqual(owners, {'架空建設株式会社': '10000分の9443', '乙野花子': '10000分の200',
                                  '株式会社テスト不動産': '1万分の257', '丙野次郎': '1万分の100'})
        # Printed shares are trusted; the ones the ledger computed are sent to review.
        names = [v(o, 'name') for o in self.raw['owners']]
        review = set(self.raw['review_fields'])
        self.assertNotIn(f"owners.{names.index('株式会社テスト不動産')}.share", review)
        self.assertIn(f"owners.{names.index('架空建設株式会社')}.share", review)
        self.assertNotIn('owners', review)  # shares add up to exactly 1

    def test_seller_share_goes_to_the_contract_land_row(self):
        building = blank(API_SCHEMA)
        building.update(document_type=f('building'), metadata={'source_pdf': 'b.pdf'})
        building['building'].update(location=f('港区架空一丁目'), lot_number=f('12番地3'))
        building['unit']['house_number'] = f('架空一丁目12番3の5')
        building['land_right']['exists'] = f(False)
        building['owner']['name'] = f('株式会社テスト不動産')
        land = finish(self.raw, self.pages)
        data = integrate([{'id': 'b', 'path': 'b.pdf', 'sha256': ''}, {'id': 'l', 'path': 'l.pdf', 'sha256': ''}], {'b': building, 'l': land})
        self.assertEqual(data['group_review'], [])
        self.assertEqual((v(data, 'lands.0.right_type'), v(data, 'lands.0.share_numerator'), v(data, 'lands.0.share_denominator')), ('所有権', 257, 10000))


class PrivateRoadTest(unittest.TestCase):
    def build(self, road_owner):
        building = blank(API_SCHEMA)
        building.update(document_type=f('building'), metadata={'source_pdf': 'b.pdf'})
        building['building'].update(location=f('港区架空一丁目'), lot_number=f('12番地3'))
        building['unit']['house_number'] = f('架空一丁目12番3の5')
        building['land_right']['exists'] = f(True)
        building['owner']['name'] = f('株式会社テスト不動産')
        building['lands'] = [{**blank(API_SCHEMA['properties']['lands']['items']), 'location': f('港区架空一丁目'), 'lot_number': f('12番3'),
                              'right_type': f('所有権'), 'right_share': f('10万分の5000')}]
        road = blank(API_SCHEMA)
        road.update(document_type=f('land'), metadata={'source_pdf': 'r.pdf'})
        road['lands'] = [{**blank(API_SCHEMA['properties']['lands']['items']), 'location': f('港区架空一丁目'), 'lot_number': f('12番9'), 'category': f('公衆用道路')}]
        road['lands'][0]['owners'] = [{'name': f(road_owner), 'address': f('港区'), 'share': f('10分の1'), 'rank': f('3'), 'corporate_number': f()}]
        return integrate([{'id': 'b', 'path': 'b.pdf', 'sha256': ''}, {'id': 'r', 'path': 'r.pdf', 'sha256': ''}], {'b': building, 'r': road})

    def test_road_outside_the_site_is_included_when_the_seller_owns_part_of_it(self):
        data = self.build('株式会社テスト不動産')
        self.assertEqual(data['group_review'], [])
        self.assertEqual(v(data, 'lands.1.right_share'), '10分の1')
        self.assertTrue(data['land_warnings'])

    def test_road_the_seller_does_not_own_still_stops_registration(self):
        data = self.build('近隣の別会社')
        self.assertEqual(data['group_review'], ['土地と建物の対応:港区架空一丁目12番9'])
        from web_registration import blocked_reason
        self.assertIn('売主も所有者に入っていません', blocked_reason('condominium_land_right', data['group_review']))


class TextHelpersTest(unittest.TestCase):
    def test_kanji_multiplier_shares(self):
        self.assertEqual(fraction('32万7285分の5238'), (5238, 327285))
        self.assertEqual(fraction('1万分の257'), (257, 10000))

    def test_old_numerals_convert_numbers_but_not_spaced_names(self):
        line = '┃所　在│港区架空町弐七番地壱九│┃建物の名称│弐〇弐　│┃　山　田　一　郎┃'
        self.assertTrue(old_numerals('昭和五四年弐月弐〇日新築'))
        self.assertFalse(old_numerals('港区架空一丁目１２番３'))
        self.assertEqual(arabic(line), '┃所　在│港区架空町27番地19│┃建物の名称│202　│┃　山　田　一　郎┃')

    def test_gaiji_excludes_blank_and_collateral_marks(self):
        self.assertIsNone(GAIJI.search('\ue042\ue043\ue044\ue192'))
        self.assertIsNotNone(GAIJI.search('架空\uee0b子'))

    def test_gaiji_name_is_sent_to_review(self):
        raw, _ = from_pages([page(CONDO.replace('山　田　太　郎', '山　田　\uee0b　郎'))])
        self.assertIn('owner.name', raw['review_fields'])

    def test_non_service_pdf_goes_to_the_ai_reader(self):
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scan.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.write(path)
            self.assertFalse(is_service_pdf(path))


if __name__ == '__main__':
    unittest.main()
