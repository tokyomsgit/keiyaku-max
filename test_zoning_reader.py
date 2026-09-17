import unittest
from zoning_reader import parse_text


class ZoningReaderTest(unittest.TestCase):
    def test_itabashi_layout(self):
        text='''印刷日：令和7年12月8日
区域区分／都市計画区域       市街化区域／都市計画区域
用途地域              第１種住居地域
特別用途地区           （なし）
建ぺい率              60%
容積率               200%
敷地面積の最低限度         70㎡
高度地区              種別：第二種高度地区 最高限度：17m
防火規制／新防火区域（都安全条例） 準防火地域／（新防火区域：なし）
日影規制              （一） 4時間-2.5時間／4m'''
        fields=parse_text(text)
        self.assertEqual(fields['zoning_type']['value'],'第１種住居地域')
        self.assertEqual(fields['building_coverage_ratio']['value'],'60%')
        self.assertEqual(fields['floor_area_ratio']['value'],'200%')
        self.assertEqual(fields['reference_date']['value'],'2025-12-08')

    def test_ambiguous_values_are_not_invented(self):
        fields=parse_text('用途地域 第１種住居地域\n用途地域 商業地域')
        self.assertNotIn('zoning_type',fields)


if __name__=='__main__':unittest.main()
