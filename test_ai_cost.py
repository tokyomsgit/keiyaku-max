import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from web_ai_cost import prepare,authorize,permit,estimate,summary,local_result,cache_hit
from web_data import StoreError

class CostTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.w=SimpleNamespace(output=Path(self.temp.name),demo=False,ai_calls=0)
  self.file=('report','sample.pdf',b'%PDF-synthetic')
  self.pages=[{'page_no':1,'mode':'scan','text':'','renderer':'pypdf'}]
 def tearDown(self):self.temp.cleanup()
 def plan(self):
  with patch('web_ai_cost.cache_hit',return_value=False),patch('important_report_reader.pdf_pages',return_value=self.pages):return prepare(self.w,[self.file])
 def test_cached_zero(self):
  with patch('web_ai_cost.cache_hit',return_value=True),patch('important_report_reader.pdf_pages',side_effect=AssertionError('no PDF work')):
   p=prepare(self.w,[self.file]);self.assertEqual(p['estimate_jpy'],0);self.assertEqual(p['ai_files'],0)
 def test_text_local_no_api(self):
  self.pages=[{'page_no':1,'mode':'text','renderer':'pypdf','text':'重要事項調査報告書\n管理費：12,000円\n修繕積立金：8,000円'}]
  p=self.plan();self.assertEqual(p['files'][0]['mode'],'local');self.assertEqual(p['estimate_jpy'],0)
  h=hashlib.sha256(self.file[2]).hexdigest();d=json.loads((self.w.output/'report_cache'/h/'extracted_normalized.json').read_text(encoding='utf8'))
  self.assertEqual(d['fields']['management_fee']['value'],12000);self.assertTrue(d['fields']['management_fee']['needs_review']);self.assertTrue(cache_hit(self.w,'report',h))
 def test_scan_needs_explicit_confirmation(self):
  p=self.plan();self.assertEqual(p['ai_files'],1);self.assertIsNone(p['estimate_jpy'])
  with self.assertRaises(StoreError):authorize(self.w,p['token'],[self.file],False)
  self.assertFalse(getattr(self.w,'ai_grants',{}))
  authorize(self.w,p['token'],[self.file],True);pdf=self.w.output/'test.pdf';pdf.write_bytes(self.file[2]);permit(self.w,'report',pdf)
  with self.assertRaises(StoreError):permit(self.w,'report',pdf)
 def test_known_pricing_and_unknown_model(self):
  config={'usd_to_jpy':150,'models':{'test':{'image_page_estimate_usd':.01,'input_per_1m_tokens_usd':2,'output_per_1m_tokens_usd':8,'prompt_tokens_estimate':1000,'output_tokens_estimate':1000}}}
  self.assertEqual(estimate(self.pages,'test',config),3);self.assertIsNone(estimate(self.pages,'unknown',config))
 def test_limit_and_demo_fail_closed(self):
  with patch('web_ai_cost.env',side_effect=lambda k:'100' if k=='AI_COST_LIMIT_JPY' else None):
   p=self.plan();self.assertTrue(p['blocked'])
   with self.assertRaises(StoreError):authorize(self.w,p['token'],[self.file],True)
   with patch('web_ai_cost.estimate',return_value=101):self.assertTrue(self.plan()['blocked'])
   with patch('web_ai_cost.estimate',return_value=50):self.assertFalse(self.plan()['blocked'])
  self.w.demo=True;p=self.plan();self.assertTrue(p['blocked'])
 def test_post_count_and_reupload(self):
  p=self.plan();self.w.ai_calls=1;result={'state':{'cases':[{'id':'c','pending_documents':[]}]},'case_id':'c'}
  r=summary(self.w,p,[self.file],result,0);self.assertEqual(r['analysis_summary']['api_calls'],1)
  with patch('web_ai_cost.cache_hit',return_value=True):again=prepare(self.w,[self.file])
  r=summary(self.w,again,[self.file],result,1);self.assertEqual(r['analysis_summary']['api_calls'],0);self.assertEqual(r['analysis_summary']['session_total']['api_calls'],1)
 def test_token_file_binding(self):
  p=self.plan()
  with self.assertRaises(StoreError):authorize(self.w,p['token'],[('report','other.pdf',b'%PDF-other')],True)
 def test_regulations_scan_ocr_used_never_ai(self):
  self.file=('rules','rules.pdf',b'%PDF-synthetic')
  with patch('management_rules_reader.readable_text',side_effect=lambda pages,pdf:[dict(p,ocr_text='管理規約\n第1条　ペットの飼育を禁止する。') for p in pages]):
   p=self.plan()
  self.assertEqual(p['files'][0]['mode'],'local');self.assertEqual(p['ai_files'],0);self.assertFalse(p['blocked'])
  h=hashlib.sha256(self.file[2]).hexdigest();d=json.loads((self.w.output/'rules_cache'/h/'extracted_normalized.json').read_text(encoding='utf8'))
  self.assertIn('OCR',d['fields']['pet_restrictions']['source_section']);self.assertTrue(d['fields']['pet_restrictions']['needs_review'])
 def test_regulations_unrecognizable_scan_raises(self):
  self.file=('rules','rules.pdf',b'%PDF-synthetic')
  with self.assertRaises(StoreError):self.plan()
 def test_ai_reader_mock_then_cache(self):
  from web_report import upload
  case={'id':'test','documents':[],'diffs':[]}
  self.w.remote=False;self.w.raw={};self.w.case=lambda cid:case;self.w.public=lambda:{'cases':[case]}
  p=self.plan();authorize(self.w,p['token'],[self.file],True)
  digest=hashlib.sha256(self.file[2]).hexdigest()
  data={'is_important_report':True,'source':{'file_hash':digest},'fields':{'management_fee':{'value':12000,'source_text':'管理費12000円','page_no':1,'confidence':.9}}}
  with patch('important_report_reader.read_report',return_value=data) as reader,patch('web_report.read_existing',side_effect=lambda f,*a,**k:f(*a,**k)):
   result=upload(self.w,'test',[(self.file[1],self.file[2])]);summary(self.w,p,[self.file],result,0)
   self.assertEqual(result['analysis_summary']['api_calls'],1);self.assertEqual(reader.call_count,1)
   again=prepare(self.w,[self.file]);self.assertEqual(again['ai_files'],0)
   upload(self.w,'test',[(self.file[1],self.file[2])]);self.assertEqual(reader.call_count,1);self.assertEqual(self.w.ai_calls,1)
if __name__=='__main__':unittest.main()
