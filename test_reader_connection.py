import unittest,tempfile
from pathlib import Path
from unittest.mock import Mock,patch
from pypdf import PdfWriter
from web_reading import read_existing
from web_data import Workspace,StoreError

class ReaderConnectionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.pdf=Path(self.tmp.name)/'valid.pdf';w=PdfWriter();w.add_blank_page(width=100,height=100);w.write(self.pdf)
 def tearDown(self):self.tmp.cleanup()
 def test_existing_reader_result_and_arguments(self):
  reader=Mock(return_value={'fields':{}});self.assertEqual(read_existing(reader,self.pdf,'cache',allow_api=False),{'fields':{}});reader.assert_called_once_with(self.pdf,'cache',allow_api=False)
 def test_invalid_pdf_never_calls_reader(self):
  self.pdf.write_bytes(b'%PDF-broken');reader=Mock()
  with self.assertRaisesRegex(StoreError,'対応していないPDF'):read_existing(reader,self.pdf)
  reader.assert_not_called()
 def test_safe_api_errors(self):
  for error,expected in [(RuntimeError('OPENAI_API_KEY private'),'API設定不足'),(RuntimeError('429 private'),'API利用上限'),(RuntimeError('secret private'),'読取処理エラー')]:
   with self.assertRaisesRegex(StoreError,expected) as raised:read_existing(Mock(side_effect=error),self.pdf)
   self.assertNotIn('private',str(raised.exception))
 def test_other_errors_name_the_failure_without_content(self):
  for error,expected in [(RuntimeError('AI API HTTP 400。認証 private'),'（詳細：AI API HTTP 400）'),(RuntimeError('AIの応答が未完了です: incomplete'),'（詳細：AI応答未完了 incomplete）'),(KeyError('private'),'（詳細：KeyError @ ')]:
   with self.assertRaises(StoreError) as raised:read_existing(Mock(side_effect=error),self.pdf)
   self.assertIn(expected,str(raised.exception));self.assertNotIn('private',str(raised.exception))
 def test_default_live_and_explicit_demo(self):
  with patch('web_data.load_env'),patch('web_data.env',return_value=None),patch.object(Workspace,'refresh'),patch('web_registry.restore'),patch('web_report.restore'),patch('web_rules.restore'),patch('web_purchase.restore'):
   self.assertFalse(Workspace().demo)
  with patch('web_data.load_env'),patch('web_data.env',side_effect=lambda k:'true' if k=='DEMO_MODE' else None),patch.object(Workspace,'load_demo'),patch('web_registry.restore'),patch('web_report.restore'),patch('web_rules.restore'),patch('web_purchase.restore'):
   self.assertTrue(Workspace().demo)
if __name__=='__main__':unittest.main()
