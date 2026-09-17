import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from web_data import StoreError
from web_registration import payload_from, preview, register, iso_date
from web_registry import generate


def fixture():
    def f(value, digest='a'*64):
        return {'value':value,'needs_review':False,'sources':[{'page':2,'text':str(value),'file_hash':digest,'source_pdf':'fixture.pdf'}]}
    return {'property_type':f('condominium_land_right'),
        'building':{'name':f('試験建物'),'location':f('試験所在')},
        'unit':{'house_number':f('試験1の101'),'name':f('101'),'built_date':f('平成12年1月1日')},
        'owner':{'name':f('試験所有者')},'lands':[
            {'location':f('試験所在',h),'lot_number':f(n,h),'area':f(12.34,h),'category':f('宅地',h)}
            for h,n in [('b'*64,'1'),('c'*64,'2')]],
        'registration_documents':[{'file_hash':h*64,'original_filename':h+'.pdf'} for h in 'abc']}


class RegistrationTests(unittest.TestCase):
    def test_per_document_evidence_and_raw_unchanged(self):
        data=fixture();before=copy.deepcopy(data);p=payload_from(data)
        self.assertEqual(data,before)
        self.assertEqual(p['unit']['built_date'],'2000-01-01')
        self.assertEqual(len(p['building']['land_lots']),2)
        for doc in p['documents'][1:]:
            land=next(x for x in doc['values'] if x['field_code']=='land_lots')
            self.assertEqual(len(land['provenance']['sources']),8)
            self.assertEqual(land['page_no'],2)
            self.assertIn('試験所在',land['source_text'])
        # Registry extraction has no native confidence score; a fully-sourced, non-review
        # field is treated as fully confident so it can actually be adopted via web_review_diff.
        self.assertEqual(p['fields'][0]['confidence'],1.0)

    def test_low_confidence_and_review_values_never_enter_master(self):
        for change in ({'needs_review':True},{'confidence':.5}):
            data=fixture();data['owner']['name'].update(change)
            p=payload_from(data)
            self.assertNotIn('current_owner_name',p['unit'])
            self.assertTrue(next(f for f in p['fields'] if f['field_code']=='current_owner_name')['needs_review'])

    def test_block_unsupported_conflicting_and_unattributed(self):
        for kind in ('detached_house','unknown','land_only'):
            data=fixture();data['property_type']['value']=kind
            with self.assertRaises(StoreError):payload_from(data)
        data=fixture();data['group_review']=['conflict']
        with self.assertRaises(StoreError):payload_from(data)
        data=fixture();data['owner']['name']['sources'][0]['file_hash']='f'*64
        with self.assertRaises(StoreError):payload_from(data)

    def test_date_era_boundaries(self):
        self.assertEqual(iso_date('令和元年5月1日'),'2019-05-01')
        for v in ('令和元年4月30日','平成31年5月1日','平成12年2月30日'):
            self.assertIsNone(iso_date(v))

    def test_leasehold_terms_are_saved_as_extracted_values(self):
        data=fixture();data['property_type']['value']='leasehold_condominium'
        source={'page':1,'text':'地上権設定','file_hash':'a'*64,'source_pdf':'fixture.pdf'}
        data['leasehold']={'area':{'value':873.97,'needs_review':False,'sources':[source]},
          'law_type':{'value':'旧法','needs_review':False,'sources':[source]},
          'ground_rent_unit_per_3_3sqm':{'value':400,'needs_review':True,'sources':[source]}}
        payload=payload_from(data)
        fields={x['field_code']:x for x in payload['fields']}
        self.assertEqual(fields['leasehold_area']['value'],873.97)
        self.assertEqual(fields['leasehold_law_type']['value'],'旧法')
        self.assertTrue(fields['leasehold_ground_rent_unit']['needs_review'])

    def workspace(self,root,remote=True):
        return SimpleNamespace(remote=remote,raw={'upload':{'uploaded':fixture()}},case=Mock(),
            rpc=Mock(return_value={'status':'new','cases':[]}),output=Path(root),cases=[{'id':'upload'}],
            refresh=Mock(),public=Mock(return_value={}))

    def test_preview_read_only_and_confirmation_required(self):
        with tempfile.TemporaryDirectory() as root:
            w=self.workspace(root);p=preview(w,'upload')
            self.assertNotIn('write',w.rpc.call_args.kwargs)
            with self.assertRaises(StoreError):register(w,'unknown','new')
            w.rpc.assert_called_once()
            w.rpc.return_value={'case_id':'saved','unit_id':'unit'}
            result=register(w,p['token'],'new')
            self.assertEqual(result['case_id'],'saved')
            self.assertTrue(w.rpc.call_args.kwargs['write'])
            self.assertEqual(w.rpc.call_args.args[1]['raw_json']['format'],'normalized_registry_v1')

    def test_demo_ambiguity_and_wrong_resume_stop_without_write(self):
        with tempfile.TemporaryDirectory() as root:
            w=self.workspace(root,False);self.assertTrue(preview(w,'upload')['demo']);w.rpc.assert_not_called()
            with self.assertRaises(StoreError):register(w,'token','new')
            w.remote=True;w.rpc.return_value={'status':'ambiguous','cases':[]}
            p=preview(w,'upload');w.rpc.reset_mock()
            with self.assertRaises(StoreError):register(w,p['token'],'new')
            w.rpc.assert_not_called()
            w.rpc.return_value={'status':'existing','cases':[{'case_id':'allowed'}]}
            p=preview(w,'upload');w.rpc.reset_mock()
            with self.assertRaises(StoreError):register(w,p['token'],'resume','other')
            w.rpc.assert_not_called()

    def test_changed_match_and_failed_save_preserve_staging(self):
        with tempfile.TemporaryDirectory() as root:
            w=self.workspace(root);p=preview(w,'upload');w.rpc.return_value={'match_changed':True}
            with self.assertRaises(StoreError):register(w,p['token'],'new')
            w.refresh.assert_not_called();self.assertIn('upload',w.raw)
            self.assertFalse((Path(root)/'imports/upload/registration.json').exists())

    def test_excel_stops_before_registration(self):
        w=SimpleNamespace(case=lambda cid:{'registration_required':True})
        with self.assertRaisesRegex(StoreError,'登録前'):
            generate(w,'upload')


if __name__=='__main__':unittest.main()
