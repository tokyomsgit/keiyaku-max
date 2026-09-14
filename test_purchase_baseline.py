import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from web_data import StoreError
from web_purchase import payload, integrated, generate, apply_snapshot, verify_fields, stage
from purchase_explanation_reader import normalize, read_purchase


def sample():
    def f(v):return {'value':v,'source_label':'試験','source_section':'物件','source_text':str(v),'page_no':1,'confidence':.99,'needs_review':False,'value_as_of_date':'2020-01-01'}
    values={'building_name':'購入重説機能テスト専用','registry_location':'試験市中央一丁目90009番2',
      'building_structure':'鉄筋コンクリート造陸屋根7階建','house_number':'中央一丁目90009番2の704',
      'unit_name':'704','unit_type':'居宅','unit_structure':'鉄筋コンクリート造1階建','unit_floor':'7階',
      'registered_area':40.49,'built_date':'2000-01-01','current_owner_name':'旧試験所有者',
      'has_land_right':True,'land_right_type':'所有権','land_right_numerator':4049,'land_right_denominator':99999,
      'management_fee':12000,'repair_reserve_fee':10000,'land_lots':[{'location':'試験市中央一丁目','lot_number':'90009番2','land_category':'宅地','area':1000}]}
    return {'is_purchase_explanation':True,'property_type':'condominium_land_right','fields':{k:f(v) for k,v in values.items()},
       'source':{'file_hash':hashlib.sha256(b'%PDF-purchase-test').hexdigest(),'original_filename':'purchase-test.pdf'}}


class PurchaseTests(unittest.TestCase):
    def test_normalization_duplicate_and_evidence_guards(self):
        raw={'is_purchase_explanation':True,'property_type':'unknown','fields':[
          {'field_code':'registered_area','value':'40.49㎡','source_text':'面積40.49㎡','page_no':1,'confidence':.99},
          {'field_code':'management_fee','value':'12,000円','source_text':'管理費12,000円','page_no':1,'confidence':.99},
          {'field_code':'house_number','value':'A','source_text':'A','page_no':1,'confidence':.99},
          {'field_code':'house_number','value':'B','source_text':'B','page_no':1,'confidence':.99}]}
        data=normalize(raw,[{'mode':'text','text':'面積40.49㎡ 管理費12,000円 A B'}])
        self.assertEqual(data['fields']['registered_area']['value'],40.49)
        self.assertEqual(data['fields']['management_fee']['value'],12000)
        self.assertIsNone(data['fields']['house_number']['value'])
        raw['fields'][0]['page_no']=99
        self.assertTrue(normalize(raw,[{'mode':'scan','text':''}])['fields']['registered_area']['needs_review'])

    def test_payload_preserves_history_and_excludes_uncertain_master(self):
        data=sample();data['fields']['current_owner_name']['needs_review']=True;before=copy.deepcopy(data)
        p=payload(data)
        self.assertEqual(data,before);self.assertNotIn('current_owner_name',p['unit'])
        self.assertEqual(p['raw_json']['format'],'normalized_purchase_v1')
        self.assertEqual(len(p['documents'][0]['values']),len(data['fields']))
        for kind in ('detached_house','unknown'):
            data['property_type']=kind
            with self.assertRaises(StoreError):payload(data)

    def test_demo_no_network_and_raw_cache_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.pdf';p.write_bytes(b'%PDF-fixture');root=Path(tmp)/'cache'
            with patch('purchase_explanation_reader.pdf_pages',return_value=[{'mode':'scan','text':''}]),patch('purchase_explanation_reader.urllib.request.build_opener') as net:
                with self.assertRaises(StoreError):read_purchase(p,root,allow_api=False)
                folder=root/hashlib.sha256(p.read_bytes()).hexdigest()
                (folder/'extracted_raw.json').write_text(json.dumps(sample()),encoding='utf8')
                self.assertTrue(read_purchase(p,root,allow_api=False)['source']['cache_reused']);net.assert_not_called()

    def test_excel_uses_only_selected_values_not_newest_document(self):
        case={'id':'case'};old={'purchase':sample()};w=SimpleNamespace(raw={'case':old})
        with patch('web_registry.generate',return_value={'warnings':[]}) as writer:
            def inspect(work,cid):
                self.assertEqual(work.raw[cid]['unit']['registered_area'],40.49)
                self.assertNotIn('current_owner_name',work.raw[cid]['unit'])
                return {'warnings':[]}
            old['purchase']['fields']['current_owner_name']['needs_review']=True
            writer.side_effect=inspect;generate(w,'case')
        self.assertIs(w.raw['case'],old)

    def test_snapshot_selects_explicit_evidence_ids(self):
        w=SimpleNamespace(raw={'c':{'building':{'property_type':'condominium_land_right'}}})
        c={'id':'c','documents':[]}
        s={'values':[{'extracted_value_id':'old','field_code':'registered_area','value':40.49},
                     {'extracted_value_id':'new','field_code':'registered_area','value':42.5}]}
        apply_snapshot(w,c,{'purchase_values':{'registered_area':'old'}},s)
        self.assertEqual(c['area'],40.49)
        apply_snapshot(w,c,{'purchase_values':{'registered_area':'new'}},s)
        self.assertEqual(c['area'],42.5)

    def test_scans_require_original_review_before_registration(self):
        data=sample();data['source'].update(page_count=1,text_pages=0)
        with self.assertRaises(StoreError):payload(data)
        parsed=normalize(data,[{'mode':'scan','text':''}])
        self.assertTrue(all(f['needs_review'] for f in parsed['fields'].values()))

    def test_manual_review_is_audited_and_invalidates_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=sample();data['source'].update(page_count=1,text_pages=0)
            w=SimpleNamespace(output=Path(tmp),remote=True,cases=[],raw={},public=lambda:{},registration_pending={})
            cid=stage(w,data);w.registration_pending={'stale':{'cid':cid}}
            folder=w.output/'purchase_cache'/data['source']['file_hash'];folder.mkdir(parents=True)
            entry={'code':'registered_area','value':42.5,'page_no':1,'source_text':'42.5','verified':True}
            verify_fields(w,cid,[entry],'condominium_land_right')
            f=w.raw[cid]['purchase']['fields']['registered_area']
            self.assertTrue(f['verified_against_original']);self.assertEqual(f['ai_confidence'],.99)
            self.assertEqual(w.registration_pending,{})
            entry['value']=float('nan')
            with self.assertRaises(StoreError):verify_fields(w,cid,[entry],'condominium_land_right')


if __name__=='__main__':unittest.main()
