import tempfile
import unittest
from unittest.mock import patch
import test_web_registration
from web_registration import advance, choose_candidate, preview
from web_data import StoreError

class AutoProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.w=test_web_registration.RegistrationTests().workspace(self.tmp.name)
        self.w.case.return_value={'registration_required':True}
    def test_new_and_existing(self):
        for match,mode,cid in [({'status':'new'},'new',None),({'status':'existing','cases':[{'case_id':'same'}]},'resume','same')]:
            self.w.rpc.return_value=match
            with patch('web_registration.register',return_value={'case_id':'saved'}) as save:
                self.assertEqual(advance(self.w,{'case_id':'upload'})['case_id'],'saved')
                self.assertEqual(save.call_args.args[2:],(mode,cid))
    def test_ambiguous_incomplete_and_multiple_cases_stop(self):
        for match in [{'status':'ambiguous','candidates':[{'unit_id':'a'},{'unit_id':'b'}]}, {'status':'incomplete'}, {'status':'existing','cases':[{'case_id':'a'},{'case_id':'b'}]}]:
            self.w.rpc.return_value=match
            with patch('web_registration.register') as save:
                r=advance(self.w,{'case_id':'upload'});self.assertIn('registration_preview',r);save.assert_not_called()
    def test_demo_and_unsupported_do_not_write(self):
        self.w.remote=False;advance(self.w,{'case_id':'upload'});self.w.rpc.assert_not_called()
        self.w.remote=True;self.w.raw['upload']['uploaded']['property_type']['value']='detached_house'
        self.assertIn('warning',advance(self.w,{'case_id':'upload'}));self.w.rpc.assert_not_called()
    def test_explicit_candidate_rechecked(self):
        self.w.rpc.return_value={'status':'ambiguous','candidates':[{'unit_id':'a'},{'unit_id':'b'}]}
        p=preview(self.w,'upload')
        with self.assertRaises(StoreError):choose_candidate(self.w,p['token'],'foreign')
        self.w.rpc.return_value={'status':'existing','unit_id':'b','cases':[{'case_id':'saved'}]}
        with patch('web_registration.register',return_value={'case_id':'saved'}) as save:
            choose_candidate(self.w,p['token'],'b')
            self.assertEqual(self.w.rpc.call_args.args[1]['selected_unit_id'],'b')
            self.assertEqual(save.call_args.args[2:],('resume','saved'))
    def test_failed_register_keeps_import(self):
        self.w.rpc.return_value={'status':'new'}
        with patch('web_registration.register',side_effect=StoreError('changed')):
            self.assertEqual(advance(self.w,{'case_id':'upload'})['warning'],'changed')
            self.assertIn('upload',self.w.raw)

if __name__=='__main__':unittest.main()
