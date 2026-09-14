import tempfile,unittest,csv,io
from pathlib import Path
from web_data import Workspace
from web_choices import choose
from web_mapping import inventory,export_csv

class UserAdminTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.w=Workspace(demo=True);self.w.output=Path(self.tmp.name)
 def test_old_keeps_master_and_choice_survives(self):
  before=self.w.raw['demo-case']['unit']['management_fee']
  s=choose(self.w,'demo-case','diff','demo-management_fee','old')
  d=next(d for d in s['cases'][0]['diffs'] if d['id']=='demo-management_fee')
  self.assertEqual(d['user_choice'],'old');self.assertEqual(self.w.raw['demo-case']['unit']['management_fee'],before)
  self.w.cases[0]['diffs'][1]['new_value']='changed'
 def test_conflict_choice_and_changed_source(self):
  c=self.w.cases[0]
  c['documents']=[{'type':k,'filename':k+'.pdf','date':'2026-01-01','version':1,'fields':[{'code':'pet_restrictions','value':v,'needs_review':False}]} for k,v in [('important_report','可'),('management_rules','不可')]]
  x=self.w.public()['cases'][0]['source_conflicts'][0]
  s=choose(self.w,'demo-case','conflict',x['choice_id'],'rules')
  self.assertEqual(s['cases'][0]['source_conflicts'][0]['chosen_source'],'rules')
  c['documents'][1]['fields'][0]['value']='条件付き可'
  self.assertNotIn('chosen_source',self.w.public()['cases'][0]['source_conflicts'][0])
 def test_mapping_csv_and_names(self):
  rows=inventory(self.w.template);data=export_csv(rows)
  parsed=list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
  self.assertEqual(len(parsed),len(rows)+1)
  sale=next(r for r in rows if r['field_code']=='sale_price')
  self.assertTrue(sale['excel_supported']);self.assertTrue(sale['cell']);self.assertEqual(sale['sheet'],'基本入力')
  self.assertTrue(any(not r['excel_supported'] for r in rows))
  self.assertNotIn('SUPABASE',data.decode('utf-8-sig'))

if __name__=='__main__':unittest.main()
