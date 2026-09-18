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

    def test_table_format_label_is_not_matched_mid_word(self):
        # A real district-plan NAME can itself end in "地区計画" (e.g. "新川・茅場町地区地区計画").
        # An unanchored 地区計画\s+(...) regex matches inside that word and then wrongly grabs
        # the next line's unrelated text as if it were this field's value.
        fields=parse_text('新川・茅場町地区地区計画\nー\n')
        self.assertNotIn('district_plan',fields)

    def test_ambiguous_values_are_not_invented(self):
        fields=parse_text('用途地域 第１種住居地域\n用途地域 商業地域')
        self.assertNotIn('zoning_type',fields)

    def test_setagaya_imap_layout(self):
        text='''都市計画情報 検索結果                     世田谷区 都市整備政策部 都市計画課
 区域区分                   市街化区域               土地区画整理事業を施行すべき区域       なし
 用途地域                   近隣商業地域              土地区画整理事業 地区名           なし
 建ぺい率(％)                80                  市街地再開発事業               なし
 容積率(％)                 300                 特定街区                   なし
 敷地規模の最低限度(m2)          なし                  都市計画駐車場 名称             なし
 特別用途地区                 なし                  都市計画公園・緑地 開設区分         なし
 高度地区                   28ｍ第３種高度地区          都市計画公園・緑地 名称           なし
 最低限高度地区(7ｍ)            なし
 防火指定                   準防火地域               都市計画交通広場 整備状況（完成       なし
 日影規制                   ５時間以上 ３時間以上 ４ｍ      都市計画交通広場 名称            なし
 風致地区                   なし                  高度利用地区                 なし
（注記）この図面の都市計画情報は、令和8年6月30日時点のものです。                                    令和8年7月30日
https://www.sonicweb-asp.jp/setagaya/preview?theme=toshikeikaku'''
        fields=parse_text(text)
        self.assertEqual(fields['zoning_type']['value'],'近隣商業地域')
        self.assertEqual(fields['building_coverage_ratio']['value'],'80%')
        self.assertEqual(fields['floor_area_ratio']['value'],'300%')
        self.assertEqual(fields['semi_fire_zone']['value'],'準防火地域')
        self.assertNotIn('fire_zone',fields)
        self.assertEqual(fields['height_district']['value'],'28m第3種')
        self.assertNotIn('minimum_height_district',fields)
        self.assertEqual(fields['height_use_district']['value'],'なし')
        self.assertEqual(fields['reference_date']['value'],'2026-06-30')


if __name__=='__main__':unittest.main()
