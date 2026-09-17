import copy
import hashlib
import json
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from web_data import StoreError
from management_rules_schema import normalize, MAPPING
from management_rules_store import make_payload
from web_rules import prepare, upload, conflicts
from web_documents import upload as mixed_upload, pending_names, flush
from management_rules_reader import local_candidates, read_rules


def sample():
    return {'is_management_rules':True,'building_name':'試験建物','fields':{'pet_restrictions':{
        'value':'犬猫は禁止','source_article':'第12条','source_section':'使用制限','source_text':'犬猫は禁止',
        'page_no':1,'confidence':.99}}}


class RulesTests(unittest.TestCase):
    def test_rate_limit_fallback_is_cached_without_another_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf=Path(tmp)/'rules.pdf';pdf.write_bytes(b'%PDF-fixture')
            pages=[{'page_no':1,'mode':'text','text':'管理規約 第12条 犬猫は禁止'}]
            error=HTTPError('https://api.openai.com/v1/responses',429,'rate limit',{},io.BytesIO(b'{"error":{"code":"rate_limit_exceeded"}}'))
            count=Mock()
            with patch('management_rules_reader.pdf_pages',return_value=pages),patch('management_rules_reader.content_for_pdf',return_value=[]),patch('management_rules_reader.env',return_value='test'),patch('urllib.request.build_opener') as network:
                network.return_value.open.side_effect=error
                result=read_rules(pdf,Path(tmp)/'cache',on_api=count)
                self.assertTrue(result['fields']['pet_restrictions']['needs_review']);count.assert_called_once()
                network.reset_mock();read_rules(pdf,Path(tmp)/'cache',on_api=count);network.assert_not_called()

    def test_local_candidates_never_choose_between_multiple_rules(self):
        pages=[{'page_no':1,'mode':'text','text':'管理規約 第12条 犬猫は禁止 第13条 犬の例外'}]
        r=normalize(local_candidates(pages),pages)['fields']['pet_restrictions']
        self.assertIsNone(r['value']);self.assertIsNone(r['confidence']);self.assertTrue(r['needs_review'])
        self.assertEqual(len(r['candidates']),2)

    def test_evidence_text_scan_and_null_are_preserved(self):
        raw=sample();checked=normalize(raw,[{'mode':'text','text':'第12条 犬猫は禁止'}])
        self.assertEqual(len(checked['fields']),len(MAPPING))
        self.assertFalse(checked['fields']['pet_restrictions']['needs_review'])
        self.assertEqual(checked['fields']['pet_restrictions']['source_article'],'第12条')
        self.assertTrue(checked['fields']['parking_rules']['needs_review'])
        for page in ({'mode':'scan','text':''},{'mode':'text','text':'別の文章'}):
            self.assertTrue(normalize(raw,[page])['fields']['pet_restrictions']['needs_review'])

    def test_demo_unknown_rules_does_not_call_api(self):
        with tempfile.TemporaryDirectory() as tmp,patch('web_rules.cached',return_value=None),patch('management_rules_reader.read_rules') as reader:
            w=SimpleNamespace(output=Path(tmp),demo=True)
            with self.assertRaises(StoreError):prepare(w,'rules.pdf',b'%PDF-test')
            reader.assert_not_called()

    def test_correct_building_scope_and_wrong_building_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            content=b'%PDF-rules';digest=hashlib.sha256(content).hexdigest();raw=sample();raw['source']={'file_hash':digest}
            folder=Path(tmp)/'rules_cache'/digest;folder.mkdir(parents=True);(folder/'extracted_normalized.json').write_text(json.dumps(raw))
            c={'id':'00000000-0000-4000-8000-000000000001','building_id':'00000000-0000-4000-8000-000000000002','building_name':'試験建物'}
            w=SimpleNamespace(output=Path(tmp),demo=True,remote=True,case=lambda cid:c,rpc=Mock(),refresh=Mock(),public=Mock(return_value={}))
            upload(w,c['id'],[('rules.pdf',content)])
            name,p=w.rpc.call_args.args;self.assertEqual(name,'rpc/save_management_rules')
            self.assertEqual(p['building_id'],c['building_id']);self.assertNotIn('unit_id',p)
            c['building_name']='別建物';w.rpc.reset_mock()
            with self.assertRaises(StoreError):upload(w,c['id'],[('rules.pdf',content)])
            w.rpc.assert_not_called()

    def test_conflicting_sources_are_review_not_overwrite(self):
        c={'documents':[{'type':'important_report','filename':'report.pdf','fields':[{'code':'pet_restrictions','value':'飼育可能'}]},
            {'type':'management_rules','filename':'rules.pdf','fields':[{'code':'pet_restrictions','value':'犬猫は禁止'}]}]}
        before=copy.deepcopy(c);self.assertEqual(len(conflicts(c)),1);self.assertEqual(c,before)

    def test_mixed_upload_waits_for_registration_then_retries_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            w=SimpleNamespace(output=Path(tmp),remote=True,case=lambda cid:{'unit_id':None},public=lambda:{})
            with patch('web_registry.upload',return_value={'case_id':'upload-case'}),patch('web_report.upload') as report,patch('web_rules.upload') as rules:
                mixed_upload(w,None,[('registry','building.pdf',b'%PDF-b'),('report','report.pdf',b'%PDF-r'),('rules','rules.pdf',b'%PDF-m')])
                report.assert_not_called();rules.assert_not_called();self.assertEqual(len(pending_names(w,'upload-case')),2)
                report.side_effect=StoreError('failure')
                self.assertIsNotNone(flush(w,'upload-case','saved-case'));rules.assert_not_called()
                report.side_effect=None;flush(w,'saved-case','saved-case')
                self.assertEqual(report.call_args.args[1],'saved-case');self.assertEqual(rules.call_args.args[1],'saved-case')
                self.assertEqual(pending_names(w,'saved-case'),[])
                report.reset_mock();rules.reset_mock();flush(w,'saved-case','saved-case')
                report.assert_not_called();rules.assert_not_called()


if __name__=='__main__':unittest.main()
