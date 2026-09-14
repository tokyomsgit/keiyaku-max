import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from web_report import upload, restore
from web_data import StoreError


class ReportUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.pdf=b'%PDF-cached-report';self.digest=hashlib.sha256(self.pdf).hexdigest()
        self.data={'is_important_report':True,'source':{'file_hash':self.digest},'fields':{
            'management_fee':{'value':13500,'confidence':.99,'source_text':'13500','page_no':1,'needs_review':False}}}
        self.case={'id':'c','unit_id':'f0a00000-0000-4000-8000-000000000001','documents':[
            {'version_id':'old','type':'important_report','fields':[{'code':'management_fee','value':12000}]}], 'diffs':[]}
        self.w=SimpleNamespace(output=self.root,demo=True,remote=False,ai_calls=0,
            case=lambda cid:self.case if cid=='c' else self.fail('unexpected case'),public=lambda:{'cases':[self.case]})
        folder=self.root/'report_cache'/self.digest;folder.mkdir(parents=True)
        (folder/'extracted_normalized.json').write_text(json.dumps(self.data))

    def test_demo_hash_reuse_idempotency_and_no_auto_adoption(self):
        with patch('important_report_reader.read_report',side_effect=AssertionError('AI forbidden')):
            result=upload(self.w,'c',[('report.pdf',self.pdf)])
            upload(self.w,'c',[('renamed.pdf',self.pdf)])
        self.assertEqual(result['reused'],1);self.assertEqual(len(self.case['documents']),2)
        self.assertEqual(len(self.case['diffs']),1)
        self.assertFalse(self.case['diffs'][0]['can_adopt'])
        self.assertEqual(self.case['documents'][0]['fields'][0]['value'],12000)
        self.assertFalse(self.case['documents'][1]['fields'][0]['approved'])
        self.case['documents']=self.case['documents'][:1];self.case['diffs']=[]
        restore(self.w);self.assertEqual(len(self.case['documents']),2)
        self.assertEqual(self.w.ai_calls,0)

    def test_unknown_demo_pdf_stops_without_reader(self):
        with patch('important_report_reader.read_report',side_effect=AssertionError('AI forbidden')):
            with self.assertRaises(StoreError):upload(self.w,'c',[('unknown.pdf',b'%PDF-unknown')])
        self.assertEqual(len(self.case['documents']),1)

    def test_remote_passes_selected_unit_to_existing_store_and_refreshes(self):
        self.w.remote=True;self.w.rpc=Mock(return_value={'document_version_id':'saved'});self.w.refresh=Mock()
        before=copy.deepcopy(self.case)
        upload(self.w,'c',[('report.pdf',self.pdf)])
        name,payload=self.w.rpc.call_args.args
        self.assertEqual(name,'rpc/save_important_report')
        self.assertEqual(payload['identity']['unit_id'],self.case['unit_id'])
        self.assertEqual(payload['source']['file_hash'],self.digest)
        self.assertEqual(payload['status'],'provisional')
        self.assertEqual(self.case,before);self.w.refresh.assert_called_once()

    def test_failed_save_does_not_attach_candidates(self):
        self.w.remote=True;self.w.rpc=Mock(side_effect=StoreError('failed'));self.w.refresh=Mock()
        with self.assertRaises(StoreError):upload(self.w,'c',[('report.pdf',self.pdf)])
        self.assertEqual(len(self.case['documents']),1);self.w.refresh.assert_not_called()

    def test_unregistered_case_blocked_before_read(self):
        self.w.remote=True;self.case['unit_id']=None
        with self.assertRaises(StoreError):upload(self.w,'c',[('report.pdf',self.pdf)])
        self.assertEqual(self.w.ai_calls,0)


if __name__=='__main__':unittest.main()
