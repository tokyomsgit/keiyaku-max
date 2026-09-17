"""Offline checks for the zoning storage adapter: no DB, no AI."""
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from web_zoning import cached, prepare, upload, zone_view


def blank_pdf(width=200):
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class FakeRestWorkspace:
    """A tiny in-memory PostgREST stand-in covering only the exact query shapes
    web_zoning.py issues, so upload()'s merge/letter-assignment logic can be tested
    without a live Supabase project."""
    def __init__(self):
        self.output = Path(tempfile.mkdtemp())
        self.demo = False
        self.ai_calls = 0
        self.remote = True
        self.tables = {'documents': [], 'document_versions': [], 'extracted_values': []}
        self._next_id = 1

    def case(self, cid):
        return {'building_id': 'bldg-1'}

    def refresh(self):
        pass

    def public(self):
        return {}

    def _id(self):
        self._next_id += 1
        return self._next_id - 1

    def rest(self, path, payload=None, method='GET', write=False):
        table, _, query = path.partition('?')
        if method == 'POST':
            row = dict(payload)
            key = table + '_id' if table not in ('documents', 'document_versions', 'extracted_values') else {
                'documents': 'document_id', 'document_versions': 'document_version_id', 'extracted_values': 'extracted_value_id'}[table]
            row[key] = self._id()
            self.tables[table].append(row)
            return [row]
        rows = list(self.tables[table])
        params = dict(p.split('=', 1) for p in query.split('&') if '=' in p and not p.startswith(('select=', 'order=', 'limit=')))
        for field, cond in params.items():
            if cond.startswith('eq.'):
                value = cond[3:]
                rows = [r for r in rows if str(r.get(field)) == value]
            elif cond == 'is.null':
                rows = [r for r in rows if r.get(field) is None]
        order = re.search(r'order=([^&]+)', query)
        if order:
            field, _, direction = order.group(1).partition('.')
            rows = sorted(rows, key=lambda r: r.get(field) or 0, reverse=direction == 'desc')
        limit = re.search(r'limit=(\d+)', query)
        if limit:
            rows = rows[:int(limit.group(1))]
        return rows


class ZoningStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.w = SimpleNamespace(output=Path(self.temp.name), demo=False, ai_calls=0)

    def tearDown(self):
        self.temp.cleanup()

    def test_cache_miss_then_reuse(self):
        digest = 'a' * 64
        self.assertIsNone(cached(digest, self.w.output))
        folder = self.w.output / 'zoning_cache' / digest
        folder.mkdir(parents=True)
        (folder / 'extracted_normalized.json').write_text(json.dumps({'source': {'file_hash': digest}, 'status': 'parsed'}), encoding='utf8')
        self.assertIsNotNone(cached(digest, self.w.output))

    def test_needs_ai_placeholder_is_not_a_valid_cache(self):
        digest = 'b' * 64
        folder = self.w.output / 'zoning_cache' / digest
        folder.mkdir(parents=True)
        (folder / 'extracted_normalized.json').write_text(json.dumps({'source': {'file_hash': digest}, 'status': 'needs_ai'}), encoding='utf8')
        self.assertIsNone(cached(digest, self.w.output))

    def test_zone_view_flattens_single_zone_document(self):
        data = {'fields': {'zoning_type': {'value': '商業地域', 'page_no': 1, 'source_text': 'x', 'needs_review': False}}}
        view = zone_view(data)
        self.assertEqual(len(view), 1)
        self.assertEqual(view[0]['fields'][0]['code'], 'zoning_type')
        self.assertEqual(view[0]['fields'][0]['label'], '用途地域')

    def test_prepare_requires_ai_consent_for_a_blank_page(self):
        # A page with no usable text needs AI, and prepare() must not run it without the same
        # cost-consent gate every other AI-using kind goes through (web_ai_cost.authorize()).
        from web_data import StoreError
        with self.assertRaises(StoreError):
            prepare(self.w, 'zoning.pdf', blank_pdf())


def _parsed(zoning_type):
    return {'format': 'zoning_reference_v1', 'status': 'parsed',
        'zones': [{'zoning_type': {'value': zoning_type, 'page_no': 1, 'source_text': zoning_type, 'needs_review': False}, 'zone_label': None, 'needs_review': False}],
        'fields': {'zoning_type': {'value': zoning_type, 'page_no': 1, 'source_text': zoning_type, 'needs_review': False}},
        'warnings': [], 'missing_fields': [], 'source': {'original_filename': 'x.pdf', 'page_count': 1}}


class ZoningMergeTest(unittest.TestCase):
    """A real 用途境あり case arrives as two separate single-zone PDF certificates rather
    than one multi-zone document, so upload() must merge across calls (not overwrite),
    assign letters by array position, and stay idempotent on a retried/duplicate upload."""
    def setUp(self):
        self.w = FakeRestWorkspace()

    def test_two_single_zone_uploads_merge_and_letter_by_order(self):
        with patch('zoning_reader.read_zoning', side_effect=[_parsed('商業地域'), _parsed('近隣商業地域')]):
            upload(self.w, 'case-1', [('zone_a.pdf', blank_pdf(200))])
            upload(self.w, 'case-1', [('zone_b.pdf', blank_pdf(300))])
        values = self.w.tables['extracted_values']
        self.assertEqual(len(self.w.tables['document_versions']), 2)
        latest = values[-1]['value']
        self.assertEqual([z['zone_label'] for z in latest], ['A', 'B'])
        self.assertEqual([next(f['value'] for f in z['fields'] if f['code'] == 'zoning_type') for z in latest], ['商業地域', '近隣商業地域'])
        self.assertEqual([z['source_filename'] for z in latest], ['zone_a.pdf', 'zone_b.pdf'])

    def test_reuploading_the_same_pdf_does_not_duplicate(self):
        content = blank_pdf(200)
        with patch('zoning_reader.read_zoning', return_value=_parsed('商業地域')):
            upload(self.w, 'case-1', [('zone_a.pdf', content)])
            result = upload(self.w, 'case-1', [('zone_a.pdf', content)])
        self.assertTrue(result['reused'])
        self.assertEqual(len(self.w.tables['document_versions']), 1)
        self.assertEqual(len(self.w.tables['extracted_values'][-1]['value']), 1)

    def test_four_zones_ok_but_a_fifth_is_rejected(self):
        # Rare but real: a property can straddle up to four 用途地域 (A-D).
        with patch('zoning_reader.read_zoning', side_effect=[_parsed('商業地域'), _parsed('近隣商業地域'), _parsed('準工業地域'), _parsed('工業地域'), _parsed('工業専用地域')]):
            upload(self.w, 'case-1', [('a.pdf', blank_pdf(200))])
            upload(self.w, 'case-1', [('b.pdf', blank_pdf(210))])
            upload(self.w, 'case-1', [('c.pdf', blank_pdf(220))])
            upload(self.w, 'case-1', [('d.pdf', blank_pdf(230))])
            latest = self.w.tables['extracted_values'][-1]['value']
            self.assertEqual([z['zone_label'] for z in latest], ['A', 'B', 'C', 'D'])
            from web_data import StoreError
            with self.assertRaises(StoreError):
                upload(self.w, 'case-1', [('e.pdf', blank_pdf(240))])


if __name__ == '__main__':
    unittest.main()
