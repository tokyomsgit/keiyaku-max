"""Offline checks for the cloud worker: no storage, DB or AI access."""
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

import cloud_worker as w


class CloudWorkerTest(unittest.TestCase):
    def test_purchase_is_read_first_for_new_case(self):
        self.assertEqual(w.batches(['registry', 'purchase', 'report'], None), [[1], [0, 2]])
        self.assertEqual(w.batches(['registry', 'purchase'], 'case'), [[0, 1]])

    def test_filename_only_signals_for_textless_pdfs(self):
        blank = b'%PDF-1.4\n%%EOF'
        self.assertEqual(w.classify('建物謄本.pdf', blank), 'registry')
        self.assertEqual(w.classify('重調 704.pdf', blank), 'report')
        self.assertIsNone(w.classify('会社謄本.pdf', blank))
        self.assertIsNone(w.classify('重調発行に関する委任状.pdf', blank))
        self.assertIsNone(w.classify('用途地域.pdf', blank))
        self.assertIsNone(w.classify('scan001.pdf', blank))

    def test_cache_round_trip_rejects_foreign_paths(self):
        digest = 'a' * 64
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            (out / 'report_cache' / digest).mkdir(parents=True)
            (out / 'report_cache' / digest / 'extracted_normalized.json').write_text('{}', encoding='utf8')
            packed = w.pack_cache(out, digest)
            stream = io.BytesIO(packed)
            with zipfile.ZipFile(stream, 'a') as archive:
                archive.writestr('report_cache/' + 'b' * 64 + '/x.json', '{}')
                archive.writestr('../evil.json', '{}')
            target = out / 'restored'
            w.unpack_cache(target, digest, stream.getvalue())
            self.assertTrue((target / 'report_cache' / digest / 'extracted_normalized.json').is_file())
            self.assertFalse((target / 'report_cache' / ('b' * 64)).exists())
            self.assertFalse((out / 'evil.json').exists())
        self.assertIsNone(w.pack_cache(Path(tempfile.gettempdir()) / 'missing-cache-root', digest))


if __name__ == '__main__':
    unittest.main()
