"""[0112] 거래내역 표를 현금흐름 행으로 바꾸는 규칙.

행은 2026-09-06에 실제 화면에서 내보낸 것을 그대로 옮겼다. 지어낸 표로
시험하면 화면이 실제로 주는 모양을 놓친다.
"""

from __future__ import annotations

import unittest

from stock_importer.parsing import RowError
from stock_importer.trades import (
    FLOW_KINDS,
    external_key,
    pair_rows,
    rows_to_cash_flows,
    trade_columns,
)

HEADERS = [
    "거래일자", "거래종류", "수량", "거래금액", "정산금액", "거래세 등", "소득세",
    "양도세", "대출금", "유가잔고", "미수변제", "통화구분", "환율", "국외수수료",
]
SECOND = [
    "", "종목명", "단가", "수수료", "펀드가입번호/신탁보수", "농특세/부가세",
    "지방소득세", "과세기준가", "신용/대출이자", "예수금", "연체변제", "외화예수금",
    "", "외화정산금액",
]
DEPOSIT = [
    ["2025/09/19", "대체입금", "", "409380.0", "409380.0", "", "0.0", "0.0", "0.0", "", "0.0", "", "0.0", "0.0"],
    ["", "", "", "0.0", "", "0.0", "0.0", "0.0", "0.0", "926278.0", "0.0", "0.0", "", "0.0"],
]
DIVIDEND = [
    ["2025/10/01", "배당금 입금", "", "30736.0", "30736.0", "", "0.0", "0.0", "0.0", "", "0.0", "", "0.0", "0.0"],
    ["", "SOL 미국배당다우존스(H)", "", "0.0", "", "0.0", "0.0", "0.0", "0.0", "957093.0", "0.0", "0.0", "", "0.0"],
]
BUY = [
    ["2025/10/30", "주식장내매수", "3.0", "348735.0", "348745.0", "", "0.0", "0.0", "0.0", "45.0", "0.0", "", "0.0", "0.0"],
    ["", "KIWOOM 국고채10년", "116245.0", "10.0", "", "0.0", "0.0", "0.0", "0.0", "1034948.0", "0.0", "0.0", "", "0.0"],
]
ACCOUNT = "338-***-781-01"


def table(*records: list[list[str]]) -> list[list[str]]:
    rows = [SECOND]
    for record in records:
        rows.extend(record)
    return rows


class ColumnTests(unittest.TestCase):
    def test_finds_both_header_lines(self) -> None:
        columns = trade_columns(HEADERS, SECOND)

        self.assertEqual(columns["date"], 0)
        self.assertEqual(columns["kind"], 1)
        self.assertEqual(columns["settled"], 4)
        self.assertEqual(columns["name"], 1)
        self.assertEqual(columns["price"], 2)
        self.assertEqual(columns["cash"], 9)

    def test_a_missing_column_is_an_error_not_a_guess(self) -> None:
        with self.assertRaisesRegex(RowError, "찾지 못한 칸"):
            trade_columns(["거래일자", "수량"], ["", "단가"])


class PairingTests(unittest.TestCase):
    def test_two_lines_make_one_transaction(self) -> None:
        pairs = pair_rows(table(DEPOSIT, DIVIDEND, BUY))

        self.assertEqual(len(pairs), 3)
        self.assertEqual(pairs[0][0][0], "2025/09/19")
        self.assertEqual(pairs[1][1][1], "SOL 미국배당다우존스(H)")

    def test_an_odd_tail_does_not_crash(self) -> None:
        pairs = pair_rows(table(DEPOSIT) + [BUY[0]])

        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[1][1], [])


class CashFlowTests(unittest.TestCase):
    def flows(self, *records: list[list[str]]) -> list[dict]:
        return rows_to_cash_flows(HEADERS, table(*records), ACCOUNT)

    def test_a_bank_transfer_is_external_money(self) -> None:
        """대체입금은 은행에서 넘어오는 월 납입이다(2026-09-06 확인)."""
        flow = self.flows(DEPOSIT)[0]

        self.assertEqual(flow["flow_type"], "deposit")
        self.assertEqual(flow["occurred_on"], "2025-09-19")
        self.assertEqual(flow["amount"], "409380")

    def test_a_dividend_carries_its_instrument(self) -> None:
        flow = self.flows(DIVIDEND)[0]

        self.assertEqual(flow["flow_type"], "dividend")
        self.assertEqual(flow["name"], "SOL 미국배당다우존스(H)")
        self.assertEqual(flow["amount"], "30736")

    def test_a_buy_takes_cash_out_and_keeps_quantity_and_price(self) -> None:
        flow = self.flows(BUY)[0]

        self.assertEqual(flow["flow_type"], "buy")
        # 정산금액 348,745 = 거래금액 348,735 + 수수료 10. 현금은 그만큼 준다.
        self.assertEqual(flow["amount"], "-348745")
        self.assertEqual(flow["quantity"], "3")
        self.assertEqual(flow["unit_price"], "116245")

    def test_an_unknown_kind_stops_instead_of_guessing(self) -> None:
        strange = [list(BUY[0]), list(BUY[1])]
        strange[0][1] = "듣도보도못한거래"

        with self.assertRaisesRegex(RowError, "모르는 거래종류"):
            self.flows(strange)

    def test_shares_moved_in_carry_a_price_but_no_cash(self) -> None:
        moved = [
            ["2026/01/30", "일괄대체 입고", "100.0", "0.0", "0.0", "", "0.0", "0.0", "0.0", "130.0", "0.0", "", "0.0", "0.0"],
            ["", "삼성전자", "160500.0", "0.0", "", "0.0", "0.0", "0.0", "0.0", "178640.0", "0.0", "0.0", "", "0.0"],
        ]

        flow = self.flows(moved)[0]

        self.assertEqual(flow["flow_type"], "transfer_in")
        self.assertEqual(flow["amount"], "0")
        self.assertEqual(flow["quantity"], "100")
        self.assertEqual(flow["unit_price"], "160500")

    def test_a_trading_restriction_is_not_a_disposal(self) -> None:
        """매매제한 등록은 주식을 묶어 둘 뿐 소유권이 바뀌지 않는다.

        출고로 기록하면 나중에 팔 때 취득원가가 사라져 손익이 틀린다.
        """
        locked = [
            ["2026/01/30", "매매제한(출고포함)등록 출고", "100", "", "0", "", "0", "0", "0", "30", "0", "", "0", "0"],
            ["", "삼성전자", "", "0", "", "0", "0", "0", "0", "0", "0", "0", "", "0"],
        ]

        self.assertEqual(self.flows(locked), [])

    def test_an_ignored_kind_is_not_reported_as_unknown(self) -> None:
        from stock_importer.trades import unknown_kinds

        locked = [
            ["2026/01/30", "매매제한(출고포함)등록 출고", "100", "", "0", "", "0", "0", "0", "30", "0", "", "0", "0"],
            ["", "삼성전자", "", "0", "", "0", "0", "0", "0", "0", "0", "0", "", "0"],
        ]

        self.assertEqual(unknown_kinds(HEADERS, table(locked)), [])

    def test_every_known_kind_maps_to_a_server_flow_type(self) -> None:
        allowed = {
            "deposit", "withdrawal", "dividend", "interest", "fee", "tax",
            "buy", "sell", "transfer_in", "transfer_out",
        }
        for kind, (flow_type, _sign) in FLOW_KINDS.items():
            with self.subTest(kind=kind):
                self.assertIn(flow_type, allowed)


class ExternalKeyTests(unittest.TestCase):
    def test_the_same_row_gets_the_same_key_every_time(self) -> None:
        first = rows_to_cash_flows(HEADERS, table(DEPOSIT, BUY), ACCOUNT)
        again = rows_to_cash_flows(HEADERS, table(DEPOSIT, BUY), ACCOUNT)

        self.assertEqual(
            [flow["external_key"] for flow in first],
            [flow["external_key"] for flow in again],
        )

    def test_two_identical_transactions_on_one_day_stay_apart(self) -> None:
        flows = rows_to_cash_flows(HEADERS, table(DEPOSIT, DEPOSIT), ACCOUNT)

        self.assertEqual(len(flows), 2)
        self.assertNotEqual(flows[0]["external_key"], flows[1]["external_key"])

    def test_a_different_account_gets_a_different_key(self) -> None:
        mine = rows_to_cash_flows(HEADERS, table(DEPOSIT), ACCOUNT)[0]
        other = rows_to_cash_flows(HEADERS, table(DEPOSIT), "381-***-736-01")[0]

        self.assertNotEqual(mine["external_key"], other["external_key"])

    def test_the_key_does_not_carry_the_account_number(self) -> None:
        seen: dict[str, int] = {}
        key = external_key(
            "338-***-781-01",
            {"occurred_on": "2025-09-19", "flow_type": "deposit", "amount": "1"},
            seen,
        )

        self.assertNotIn("338", key)


if __name__ == "__main__":
    unittest.main()
