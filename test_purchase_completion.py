import copy
import unittest
from unittest.mock import patch
import web_data
from purchase_explanation_reader import normalize
from purchase_excel import append_purchase_fields
from management_rules_schema import apply_review


class CompletionTests(unittest.TestCase):
    def test_transaction_and_wall_area_types(self):
        raw={'is_purchase_explanation':True,'property_type':'condominium_land_right','fields':[
            {'field_code':code,'value':v,'page_no':1,'source_text':v,'confidence':.99}
            for code,v in [('wall_center_area','41.78㎡'),('sale_price','30,000,000円'),('handover_date','2026-02-30')]]}
        result=normalize(raw,[{'mode':'text','text':'41.78㎡ 30,000,000円 2026-02-30'}])['fields']
        self.assertEqual(result['wall_center_area']['value'],41.78)
        self.assertEqual(result['sale_price']['value'],30000000)
        self.assertIsNone(result['handover_date']['value'])

    def test_named_date_parts_and_unknown_clear(self):
        fields={'handover_date':{'value':'2026-09-30','confidence':1,'needs_review':False,'source_text':'2026-09-30','page_no':2},
                'sale_price':{'value':999999,'needs_review':True}}
        before=copy.deepcopy(fields)
        with patch('purchase_excel.write_named_excel',return_value={'output':None,'written':[]}) as writer:
            append_purchase_fields('unused.xlsm',fields)
        values=writer.call_args.args[2];mapping=writer.call_args.args[3]
        self.assertEqual([values['handover_date_'+k]['value'] for k in ('era','year','month','day')],['令和',8,9,30])
        self.assertEqual(values['sale_price']['value'],'')
        self.assertEqual(mapping['sale_price']['excel_named_range'],'購入時_sale_price')
        self.assertEqual(fields,before)

    def test_rules_review_hash_evidence_and_uncertainty(self):
        raw={'is_management_rules':True,'fields':{}}
        item={'value':'騒音は禁止','source_text':'騒音は禁止','page_no':1,'confidence':1,'verified_at':'2026-09-14',
              'verified_against_original':True,'needs_review':False,'review_reasons':[]}
        review={'file_hash':'a'*64,'fields':{'instrument_restrictions':item}}
        with self.assertRaises(ValueError):apply_review(raw,review,'b'*64)
        data=apply_review(raw,review,'a'*64,[{'mode':'text','text':'騒音は禁止'}])
        self.assertFalse(data['fields']['instrument_restrictions']['needs_review'])
        self.assertTrue(data['fields']['private_garden_rules']['needs_review'])
        bad=apply_review(raw,review,'a'*64,[{'mode':'text','text':'別条文'}])
        self.assertTrue(bad['fields']['instrument_restrictions']['needs_review'])


if __name__=='__main__':unittest.main()
