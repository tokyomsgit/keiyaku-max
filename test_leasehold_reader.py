import unittest
from leasehold_reader import parse_land_registry_text


SAMPLE='''所在 中野区本町四丁目 69番9 宅地 873：97
権 利 部 （ 甲 区 ）
地上権設定 昭和47年2月3日 原因 昭和47年1月31日設定
目的 鉄骨鉄筋コンクリート造建物所有
存続期間 60年
地代 3・3㎡当り1月400円
支払期 毎月末日'''


class LeaseholdReaderTests(unittest.TestCase):
 def test_nakano_sample_is_old_law_superficies(self):
  result=parse_land_registry_text(SAMPLE);x=result['leasehold']
  self.assertEqual(x['right_type'],'地上権');self.assertEqual(x['law_type'],'旧法')
  self.assertEqual(x['area'],873.97);self.assertEqual(x['period_years'],60)
  self.assertEqual(x['period_start']['西暦'],'1972-01-31');self.assertEqual(x['period_end']['西暦'],'2032-01-30')
  self.assertEqual(x['ground_rent_unit_per_3_3sqm'],400);self.assertIsNone(x['ground_rent_monthly'])
  self.assertFalse(x['assignment_consent_required']);self.assertTrue(result['warnings'])
 def test_no_guess_without_leasehold_registration(self):
  result=parse_land_registry_text('所有権移転のみ');self.assertEqual(result['status'],'not_leasehold');self.assertIsNone(result['leasehold'])

if __name__=='__main__':unittest.main()
