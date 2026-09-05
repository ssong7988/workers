"""H-able [1285] 총자산현황이 주는 표를 값으로 바꾸는 부분.

컬럼과 표기는 실제 화면에서 그대로 옮겼다. 창이 없어도 전부 시험할 수 있게
클립보드 글자부터 시작한다.
"""

from __future__ import annotations

import unittest

from stock_importer.parsing import (
    group_by_account,
    map_columns,
    mask_account_number,
    missing_fields,
    parse_delimited_table,
    row_to_position,
)


# 1285 통합 탭의 실제 컬럼. `구분`이 두 번 나오고 `현재가`가 없다.
HEADERS = [
    "구분",
    "계좌번호",
    "종목명",
    "구분",
    "평가손익",
    "손익률",
    "잔고수량",
    "매입단가",
    "매입금액",
    "평가금액",
]

CLIPBOARD = "\t".join(HEADERS) + "\n" + "\n".join(
    "\t".join(row)
    for row in (
        ["주식", "338-711-781-01", "삼성전자", "현금", "15,524,000", "87.75",
         "130", "136,085.00", "17,691,000", "33,215,000"],
        ["퇴직연금", "870-050-093-01", "RISE 미국S&P500(H)", "주식", "4,956,780", "52.41",
         "786", "0.00", "9,458,460", "14,415,240"],
        ["주식", "338-263-400-01", "KODEX 미국나스닥100", "현금", "4,799,595", "50.55",
         "642", "14,789.00", "9,494,535", "14,294,130"],
        ["주식", "381-719-736-01", "SK하이닉스", "현금", "-1,206,490", "-10.88",
         "6", "1,848,082.00", "11,088,490", "9,882,000"],
    )
)


class ClipboardTableTests(unittest.TestCase):
    def test_splits_a_tab_separated_copy(self) -> None:
        headers, rows = parse_delimited_table(CLIPBOARD)
        self.assertEqual(headers, HEADERS)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][2], "삼성전자")

    def test_falls_back_to_wide_spacing_when_there_are_no_tabs(self) -> None:
        text = "종목명    잔고수량    평가금액    계좌번호\n삼성전자    130    33,215,000    338-711-781-01"
        headers, rows = parse_delimited_table(text)
        self.assertEqual(headers, ["종목명", "잔고수량", "평가금액", "계좌번호"])
        self.assertEqual(rows, [["삼성전자", "130", "33,215,000", "338-711-781-01"]])

    def test_a_stray_title_line_is_dropped(self) -> None:
        # 열 수가 다른 줄은 본문으로 치지 않는다.
        text = "총자산현황\n" + CLIPBOARD
        headers, rows = parse_delimited_table(text)
        self.assertEqual(headers, HEADERS)
        self.assertEqual(len(rows), 4)

    def test_empty_text_gives_nothing(self) -> None:
        self.assertEqual(parse_delimited_table(""), ([], []))
        self.assertEqual(parse_delimited_table("   \n  "), ([], []))


class ColumnMappingTests(unittest.TestCase):
    def test_maps_the_1285_columns(self) -> None:
        columns = map_columns(HEADERS)
        self.assertEqual(missing_fields(columns), [])
        self.assertEqual(columns["account_number"], 1)
        self.assertEqual(columns["name"], 2)
        self.assertEqual(columns["unrealized_pl"], 4)
        self.assertEqual(columns["quantity"], 6)
        self.assertEqual(columns["average_cost"], 7)
        self.assertEqual(columns["cost_amount"], 8)
        self.assertEqual(columns["market_value"], 9)

    def test_this_screen_has_no_price_column(self) -> None:
        # 서버에서 price는 선택 값이다. 평가금액/수량으로 지어내지 않는다.
        self.assertNotIn("price", map_columns(HEADERS))


class FourGroupAccountNumberTests(unittest.TestCase):
    """H-able은 `338-711-781-01`처럼 네 덩어리로 준다."""

    def test_masks_only_the_second_group(self) -> None:
        self.assertEqual(mask_account_number("338-711-781-01"), "338-***-781-01")

    def test_two_accounts_sharing_the_first_group_stay_apart(self) -> None:
        # 가운데를 전부 가리면 둘 다 `338-***-***-01`이 되어 계좌가 뭉개진다.
        first = mask_account_number("338-711-781-01")
        second = mask_account_number("338-263-400-01")
        self.assertNotEqual(first, second)
        self.assertEqual({first, second}, {"338-***-781-01", "338-***-400-01"})

    def test_the_web_three_group_form_still_works(self) -> None:
        self.assertEqual(mask_account_number("338-263-400 01"), "338-***-400 01")

    def test_all_four_real_accounts_are_distinct(self) -> None:
        numbers = ["338-711-781-01", "870-050-093-01", "338-263-400-01", "381-719-736-01"]
        masked = [mask_account_number(number) for number in numbers]
        self.assertEqual(len(set(masked)), 4)
        for value in masked:
            self.assertIn("*", value)


class WholeScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        headers, rows = parse_delimited_table(CLIPBOARD)
        self.columns = map_columns(headers)
        self.positions = [row_to_position(self.columns, row) for row in rows]

    def test_reads_a_row_of_the_real_screen(self) -> None:
        samsung = self.positions[0]
        self.assertEqual(samsung["name"], "삼성전자")
        self.assertEqual(samsung["code"], "삼성전자")
        self.assertEqual(samsung["quantity"], "130")
        self.assertEqual(samsung["market_value"], "33215000")
        self.assertEqual(samsung["market_value_krw"], "33215000")
        self.assertEqual(samsung["cost_amount"], "17691000")
        self.assertEqual(samsung["average_cost"], "136085.00")
        self.assertEqual(samsung["unrealized_pl"], "15524000")
        self.assertIsNone(samsung["price"])
        self.assertEqual(samsung["account_number"], "338-***-781-01")

    def test_a_loss_keeps_its_sign(self) -> None:
        self.assertEqual(self.positions[3]["unrealized_pl"], "-1206490")

    def test_the_retirement_account_lands_in_its_own_group(self) -> None:
        grouped = group_by_account(self.positions)
        self.assertEqual(len(grouped), 4)
        self.assertEqual(len(grouped["870-***-093-01"]), 1)
        self.assertEqual(grouped["870-***-093-01"][0]["name"], "RISE 미국S&P500(H)")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
