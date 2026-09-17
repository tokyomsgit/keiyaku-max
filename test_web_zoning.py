"""Offline checks for the zoning storage adapter: no DB, no AI."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from web_zoning import cached, prepare, zone_view


def blank_pdf():
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


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


if __name__ == '__main__':
    unittest.main()
