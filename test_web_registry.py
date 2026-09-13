import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from web_registry import cached,case_from,upload,generate
from web_data import StoreError


class UploadTests(unittest.TestCase):
    def test_exact_hash_cache_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'verification_all/documents/a';folder.mkdir(parents=True)
            digest=hashlib.sha256(b'%PDF-test').hexdigest()
            (folder/'cache.json').write_text(json.dumps({'sha256':digest}))
            (folder/'normalized.json').write_text(json.dumps({'sample':True}))
            self.assertEqual(cached(digest,root,root),{'sample':True})
            self.assertIsNone(cached('0'*64,root,root))

    def test_demo_unknown_pdf_never_calls_reader(self):
        with tempfile.TemporaryDirectory() as tmp,patch('web_registry.reader_root',return_value=Path(tmp)):
            w=SimpleNamespace(output=Path(tmp),demo=True,ai_calls=0)
            with self.assertRaises(StoreError):upload(w,[('unknown.pdf',b'%PDF-unknown')])
            self.assertEqual(w.ai_calls,0)

    def test_detached_unknown_and_conflicts_block_generation(self):
        for kind in ('detached_house','unknown','land_only'):
            data={'property_type':{'value':kind}}
            c=case_from(data,'test');self.assertTrue(c['generation_blocked'])
        c=case_from({'property_type':{'value':'condominium_land_right'},'group_review':['conflict']},'test')
        self.assertTrue(c['generation_blocked'])
        c=case_from({'property_type':{'value':'condominium_land_right'}},'test')
        self.assertFalse(c['generation_blocked'])


if __name__=='__main__':unittest.main()
