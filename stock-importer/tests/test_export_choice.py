"""우클릭 메뉴에서 무엇을 누를지 고르는 규칙.

창이 없어도 시험할 수 있는 유일한 부분이고, 잘못 고르면 엉뚱한 것을 눌러
사용자의 거래 프로그램에서 무슨 일이 벌어질지 모르는 자리라 여기만은 확실히 한다.
"""

from __future__ import annotations

import unittest

from stock_importer.hable.export import pick_export_item


class PickExportItemTests(unittest.TestCase):
    def test_prefers_csv_over_excel(self) -> None:
        # CSV는 텍스트 파일 하나만 남기고 Excel을 열지 않는다.
        names = ["복사", "엑셀 저장", "CSV 저장", "HTML 저장", "인쇄"]
        self.assertEqual(pick_export_item(names), "CSV 저장")

    def test_falls_back_to_text_then_excel(self) -> None:
        self.assertEqual(pick_export_item(["엑셀 저장", "텍스트 저장"]), "텍스트 저장")
        self.assertEqual(pick_export_item(["엑셀 저장", "HTML 저장"]), "엑셀 저장")

    def test_ignores_items_that_do_not_save(self) -> None:
        # '복사'·'인쇄'·'설정'을 누르면 표가 나오는 게 아니라 딴 일이 벌어진다.
        self.assertIsNone(pick_export_item(["복사", "인쇄", "설정", "새로고침"]))

    def test_a_copy_item_named_csv_is_still_ignored_without_save(self) -> None:
        # 'CSV로 복사'는 파일을 남기지 않는다. 저장 계열만 고른다.
        self.assertIsNone(pick_export_item(["CSV로 복사"]))

    def test_english_menus_work_too(self) -> None:
        self.assertEqual(pick_export_item(["Copy", "Save as CSV", "Save as Excel"]), "Save as CSV")

    def test_empty_menu_gives_nothing(self) -> None:
        self.assertIsNone(pick_export_item([]))

    def test_case_does_not_matter(self) -> None:
        self.assertEqual(pick_export_item(["csv 저장"]), "csv 저장")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
