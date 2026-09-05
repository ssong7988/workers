"""화면 글자 → 서버 값 변환. 실제 내자산 화면의 열과 표기를 그대로 쓴다."""

from __future__ import annotations

import unittest

from stock_importer.parsing import (
    RowError,
    flatten_cell,
    flatten_row,
    group_by_account,
    instrument_code,
    map_columns,
    mask_account_number,
    missing_fields,
    normalize_label,
    parse_decimal,
    row_to_position,
)


# 사용자 화면의 열 순서 그대로.
HEADERS = [
    "종목명",
    "보유수량",
    "평가금액",
    "평가손익",
    "손익률",
    "현재가",
    "등락률",
    "평균매수단가",
    "총매수금액",
    "구분",
    "계좌번호",
]

# 첫 줄: ETF 배지가 종목명 칸에 따로 그려진다.
ACE_ROW = [
    ["ETF", "ACE KRX금현물"],
    ["240수"],
    ["6,547,200원"],
    ["1,588,097원"],
    ["32.02%"],
    ["27,280원"],
    ["▲ 125원(0.46%)"],
    ["20,663원"],
    ["4,959,103원"],
    ["현금"],
    ["338-263-400 01"],
]

HYUNDAI_ROW = [
    ["현대차"],
    ["7주"],
    ["2,684,500원"],
    ["-1,610,670원"],
    ["-37.49%"],
    ["383,500원"],
    ["0원(0.00%)"],
    ["613,596원"],
    ["4,295,170원"],
    ["현금"],
    ["338-711-781 01"],
]


class HeaderTests(unittest.TestCase):
    def test_normalize_label_drops_sort_marks_and_spaces(self) -> None:
        self.assertEqual(normalize_label(" 평가 금액 ▲ "), "평가금액")

    def test_maps_the_real_screen_and_ignores_columns_we_recompute(self) -> None:
        columns = map_columns(HEADERS)
        self.assertEqual(columns["name"], 0)
        self.assertEqual(columns["quantity"], 1)
        self.assertEqual(columns["market_value"], 2)
        self.assertEqual(columns["unrealized_pl"], 3)
        self.assertEqual(columns["price"], 5)
        self.assertEqual(columns["average_cost"], 7)
        self.assertEqual(columns["cost_amount"], 8)
        self.assertEqual(columns["account_number"], 10)
        # 손익률·등락률·구분은 서버가 다시 계산하거나 쓰지 않는다.
        self.assertEqual(missing_fields(columns), [])
        self.assertNotIn("currency", columns)

    def test_a_screen_without_the_account_column_is_rejected(self) -> None:
        self.assertEqual(missing_fields(map_columns(["종목명", "보유수량", "평가금액"])), [
            "account_number"
        ])


class NumberTests(unittest.TestCase):
    def test_reads_won_amounts_and_signs(self) -> None:
        self.assertEqual(parse_decimal("6,547,200원"), 6547200)
        self.assertEqual(parse_decimal("-1,610,670원"), -1610670)
        self.assertEqual(parse_decimal("0원(0.00%)"), 0)

    def test_blank_cells_are_none_not_zero(self) -> None:
        for text in ("", "   ", "-", None):
            self.assertIsNone(parse_decimal(text))

    def test_fractional_share_counts(self) -> None:
        self.assertEqual(parse_decimal("0.5주"), 0.5)


class MaskingTests(unittest.TestCase):
    def test_masks_the_middle_and_keeps_the_product_suffix(self) -> None:
        self.assertEqual(mask_account_number("338-263-400 01"), "338-***-400 01")

    def test_accounts_sharing_a_prefix_stay_distinguishable(self) -> None:
        first = mask_account_number("338-263-400 01")
        second = mask_account_number("338-711-781 01")
        self.assertNotEqual(first, second)

    def test_a_number_without_hyphens_still_gets_masked(self) -> None:
        self.assertEqual(mask_account_number("33826340001"), "338*****001")

    def test_blank_stays_blank(self) -> None:
        self.assertEqual(mask_account_number("  "), "")


class CodeTests(unittest.TestCase):
    def test_uses_the_screen_code_when_there_is_one(self) -> None:
        self.assertEqual(instrument_code("삼성전자", "005930"), "005930")

    def test_falls_back_to_a_unicode_slug_of_the_name(self) -> None:
        self.assertEqual(
            instrument_code("KODEX 미국나스닥100(H)"), "kodex-미국나스닥100-h"
        )
        self.assertEqual(instrument_code("ACE KRX금현물"), "ace-krx금현물")

    def test_the_same_name_in_two_accounts_gets_one_code(self) -> None:
        self.assertEqual(instrument_code("현대차"), instrument_code("현대차"))


class CellTests(unittest.TestCase):
    def test_drops_the_etf_badge_from_the_name(self) -> None:
        self.assertEqual(flatten_cell(["ETF", "ACE KRX금현물"], is_name=True), "ACE KRX금현물")

    def test_keeps_a_badge_when_it_is_the_only_thing_there(self) -> None:
        self.assertEqual(flatten_cell(["ETF"], is_name=True), "ETF")

    def test_joins_split_number_fragments(self) -> None:
        self.assertEqual(flatten_cell(["6,547,200", "원"]), "6,547,200 원")


class RowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.columns = map_columns(HEADERS)

    def _position(self, row):
        return row_to_position(self.columns, flatten_row(self.columns, row))

    def test_reads_a_whole_line_of_the_real_screen(self) -> None:
        position = self._position(ACE_ROW)
        self.assertEqual(position["name"], "ACE KRX금현물")
        self.assertEqual(position["code"], "ace-krx금현물")
        self.assertEqual(position["quantity"], "240")
        self.assertEqual(position["market_value"], "6547200")
        self.assertEqual(position["market_value_krw"], "6547200")
        self.assertEqual(position["unrealized_pl"], "1588097")
        self.assertEqual(position["price"], "27280")
        self.assertEqual(position["average_cost"], "20663")
        self.assertEqual(position["cost_amount"], "4959103")
        self.assertEqual(position["currency"], "KRW")
        self.assertEqual(position["account_number"], "338-***-400 01")

    def test_a_loss_keeps_its_sign(self) -> None:
        self.assertEqual(self._position(HYUNDAI_ROW)["unrealized_pl"], "-1610670")

    def test_a_total_line_without_a_name_is_refused(self) -> None:
        row = [[] for _ in HEADERS]
        row[2] = ["49,000,000원"]
        with self.assertRaises(RowError):
            self._position(row)

    def test_a_row_without_an_account_number_is_refused(self) -> None:
        row = [list(cell) for cell in ACE_ROW]
        row[10] = []
        with self.assertRaises(RowError):
            self._position(row)

    def test_foreign_currency_without_a_won_column_is_refused(self) -> None:
        headers = ["종목명", "수량", "평가금액", "통화", "계좌번호"]
        columns = map_columns(headers)
        cells = ["APPLE", "10", "1,500.00", "USD", "338-263-400 01"]
        # 환율을 지어내지 않는다. 원화평가액이 있는 화면을 찾아야 한다.
        with self.assertRaises(RowError):
            row_to_position(columns, cells)


class GroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.columns = map_columns(HEADERS)
        self.rows = [
            row_to_position(self.columns, flatten_row(self.columns, row))
            for row in (ACE_ROW, HYUNDAI_ROW)
        ]

    def test_splits_by_account(self) -> None:
        grouped = group_by_account(self.rows)
        self.assertEqual(sorted(grouped), ["338-***-400 01", "338-***-781 01"])
        self.assertEqual(len(grouped["338-***-400 01"]), 1)

    def test_the_same_instrument_twice_in_one_account_stops_the_run(self) -> None:
        with self.assertRaises(RowError):
            group_by_account([self.rows[0], dict(self.rows[0])])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
