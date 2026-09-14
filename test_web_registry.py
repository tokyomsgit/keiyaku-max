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

    def test_leasehold_terms_are_visible_without_exposing_codes(self):
        node=lambda value:{'value':value,'sources':[{'page':1,'text':'土地謄本'}],'needs_review':False}
        data={'property_type':node('leasehold_condominium'),'leasehold':{
          'area':node(873.97),'law_type':node('旧法'),'period_years':node(60),
          'ground_rent_unit_per_3_3sqm':node(400)}}
        case=case_from(data,'lease')
        self.assertFalse(case['generation_blocked'])
        values={f['code']:f['value'] for f in case['documents'][0]['fields']}
        self.assertEqual(values['leasehold_area'],873.97)
        self.assertEqual(values['leasehold_ground_rent_unit'],400)


if __name__=='__main__':unittest.main()
