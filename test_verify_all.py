"""Regression tests for reader/verify_all.py's multi-document integration, covering two
real production bugs found while investigating why a legitimate leasehold registration
(building on three combined land lots) was rejected as "戸建て・物件種別不明・資料間不一致"."""
import copy
import sys
import unittest
from pathlib import Path

READER = Path(__file__).resolve().parent / 'reader'
if str(READER) not in sys.path:
    sys.path.insert(0, str(READER))

from extract_registry import API_SCHEMA
from normalize_registry import blank, f
from verify_all import integrate


def doc(document_type, name='doc.pdf', **overrides):
    data = blank(API_SCHEMA)
    data['document_type'] = f(document_type)
    data['metadata'] = {'source_pdf': name, 'reviewed_input': False, 'full_text': ''}
    for path, value in overrides.items():
        node = data
        parts = path.split('.')
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return data


class VerifyAllTest(unittest.TestCase):
    def test_building_site_spanning_multiple_lots_matches_each_of_its_own_land_parcels(self):
        # Real case: a building's own 表題部 lists three lot numbers together
        # ("新宿区上落合一丁目4番地1、4番地4、4番地5"), merged into building.location
        # since building.lot_number came back empty. Each of the three separately
        # uploaded 土地 registries for those same lots must NOT be flagged as an
        # unrelated parcel just because none of them equals the whole combined string.
        building = doc('building',
            **{'building.location': f('新宿区上落合一丁目4番地1、4番地4、4番地5'),
               'unit.house_number': f('上落合一丁目4番1の69'),
               'land_right.exists': f(True)})
        lands = [
            doc('land', **{'lands': [{'location': f('新宿区上落合一丁目'), 'lot_number': f('4番1'),
                'category': f('宅地'), 'area': f(846.0), 'identifier': f(None), 'right_type': f(None), 'right_share': f(None)}]}),
            doc('land', **{'lands': [{'location': f('新宿区上落合一丁目'), 'lot_number': f('4番4'),
                'category': f('宅地'), 'area': f(8.56), 'identifier': f(None), 'right_type': f(None), 'right_share': f(None)}]}),
            doc('land', **{'lands': [{'location': f('新宿区上落合一丁目'), 'lot_number': f('4番5'),
                'category': f('宅地'), 'area': f(234.98), 'identifier': f(None), 'right_type': f(None), 'right_share': f(None)}]}),
        ]
        docs = {'0': building, '1': lands[0], '2': lands[1], '3': lands[2]}
        items = [{'id': k, 'path': f'{k}.pdf', 'sha256': 'x' * 64} for k in docs]
        data = integrate(items, docs)
        self.assertEqual(data['group_review'], [])
        self.assertTrue(all(not land.get('needs_review') for land in data['lands']))

    def test_building_site_with_one_lot_still_flags_a_genuinely_unrelated_parcel(self):
        # The fix must not make the mismatch check toothless: a land parcel whose lot
        # number really doesn't belong to this building's site should still be flagged.
        building = doc('building', **{'building.location': f('新宿区上落合一丁目4番地1'), 'unit.house_number': f('101')})
        unrelated_land = doc('land', **{'lands': [{'location': f('新宿区上落合一丁目'), 'lot_number': f('9番9'),
            'category': f('宅地'), 'area': f(100.0), 'identifier': f(None), 'right_type': f(None), 'right_share': f(None)}]})
        docs = {'0': building, '1': unrelated_land}
        items = [{'id': '0', 'path': 'b.pdf', 'sha256': 'x' * 64}, {'id': '1', 'path': 'l.pdf', 'sha256': 'y' * 64}]
        data = integrate(items, docs)
        self.assertIn('土地と建物の対応:新宿区上落合一丁目9番9', data['group_review'])

    def test_leasehold_advisory_is_not_a_registration_blocker(self):
        # 借地の期間満了日... is informational (true for every leasehold_condominium),
        # not a data contradiction, so it must go to leasehold_warnings, not
        # group_review — web_registration.payload_from() treats any non-empty
        # group_review as a hard block, which would make every leasehold case
        # permanently unregistrable if this advisory lived there instead.
        building = doc('building', **{'building.location': f('新宿区上落合一丁目4番地1'), 'unit.house_number': f('101')})
        land = doc('land', **{'tenure_type': f('leasehold'),
            'leasehold': {'exists': f(True), 'type': f('賃借権'), 'details': f('期間30年')},
            'lands': [{'location': f('新宿区上落合一丁目'), 'lot_number': f('4番1'), 'category': f('宅地'),
                'area': f(100.0), 'identifier': f(None), 'right_type': f(None), 'right_share': f(None)}]})
        docs = {'0': building, '1': land}
        items = [{'id': '0', 'path': 'b.pdf', 'sha256': 'x' * 64}, {'id': '1', 'path': 'l.pdf', 'sha256': 'y' * 64}]
        data = integrate(items, docs)
        self.assertEqual(data['group_review'], [])
        self.assertIn('借地の期間満了日・更新・契約詳細（契約書等の確認が必要）', data.get('leasehold_warnings', []))
        self.assertEqual(data['property_type']['value'], 'leasehold_condominium')


if __name__ == '__main__':
    unittest.main()
