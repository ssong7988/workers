"""거래내역에서 실현손익을 누적하는 규칙.

손계산할 수 있는 작은 사례만 쓴다. 숫자가 맞는지 사람이 눈으로 따라갈 수
있어야 나중에 고칠 때도 믿을 수 있다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from portfolio.models import CashFlow
from portfolio.realized import build_realized

from .factories import make_account, make_asset_class, make_instrument


class RealizedTests(TestCase):
    def setUp(self) -> None:
        self.account = make_account()
        stocks = make_asset_class("korea-stock", "한국 주식", "domestic_stock", 10)
        self.samsung = make_instrument("005930", stocks, name="삼성전자")

    def flow(self, day: str, flow_type: str, amount: str, **extra) -> CashFlow:
        return CashFlow.objects.create(
            occurred_on=date.fromisoformat(day),
            account=self.account,
            instrument=extra.pop("instrument", self.samsung),
            flow_type=flow_type,
            amount=Decimal(amount),
            amount_krw=Decimal(amount),
            is_external=flow_type in ("deposit", "withdrawal"),
            external_key=extra.pop("key", f"{day}-{flow_type}-{amount}"),
            quantity=Decimal(extra["quantity"]) if "quantity" in extra else None,
            unit_price=Decimal(extra["unit_price"]) if "unit_price" in extra else None,
        )

    def test_selling_above_average_cost_is_a_gain(self) -> None:
        # 10주를 1,000원에 사고(1만원), 4주를 6,000원에 팔았다.
        # 판 만큼의 원가는 4 × 1,000 = 4,000원이므로 이익은 2,000원.
        self.flow("2025-01-10", "buy", "-10000", quantity="10", unit_price="1000")
        self.flow("2025-03-10", "sell", "6000", quantity="4", unit_price="1500")

        series = build_realized()

        self.assertEqual(series.total, Decimal("2000"))
        self.assertEqual(series.unknown_cost_sales, 0)

    def test_dividends_and_interest_add_straight_in(self) -> None:
        self.flow("2025-02-01", "dividend", "300")
        self.flow("2025-02-02", "interest", "50")

        series = build_realized()

        self.assertEqual(series.total, Decimal("350"))

    def test_deposits_are_not_profit(self) -> None:
        """입금은 원금이 들어온 것이지 번 것이 아니다."""
        self.flow("2025-01-05", "deposit", "1000000", instrument=None)

        series = build_realized()

        self.assertEqual(series.total, Decimal("0"))
        self.assertFalse(series.has_data)

    def test_shares_moved_in_carry_their_cost(self) -> None:
        """입고는 현금이 0이지만 수량×단가가 취득원가다."""
        self.flow("2025-01-10", "transfer_in", "0", quantity="10", unit_price="1000")
        self.flow("2025-03-10", "sell", "6000", quantity="4", unit_price="1500")

        series = build_realized()

        self.assertEqual(series.total, Decimal("2000"))

    def test_selling_what_we_never_saw_bought_is_marked_not_guessed(self) -> None:
        """1년 창 이전에 산 주식은 취득원가를 알 수 없다."""
        self.flow("2025-03-10", "sell", "6000", quantity="4", unit_price="1500")

        series = build_realized()

        self.assertEqual(series.unknown_cost_sales, 1)
        # 원가를 0으로 보면 6,000원을 다 번 것처럼 보인다. 그렇게 적기는 하되
        # 모른다는 사실을 함께 남긴다.
        self.assertEqual(series.total, Decimal("6000"))

    def test_a_sale_without_a_quantity_is_marked_unknown(self) -> None:
        """수량이 없으면 원가를 낼 수 없다. 매도대금 전액이 이익으로 잡히면서
        아무 표시도 남지 않는 것이 가장 위험하다."""
        self.flow("2025-01-10", "buy", "-10000", quantity="10", unit_price="1000")
        self.flow("2025-03-10", "sell", "6000")

        series = build_realized()

        self.assertEqual(series.unknown_cost_sales, 1)

    def test_the_running_total_is_in_date_order(self) -> None:
        self.flow("2025-03-01", "dividend", "100")
        self.flow("2025-01-01", "dividend", "300")
        self.flow("2025-02-01", "dividend", "200")

        series = build_realized()

        self.assertEqual([day.as_of.month for day in series.days], [1, 2, 3])
        self.assertEqual([day.cumulative for day in series.days], [300, 500, 600])

    def test_average_cost_survives_two_buys(self) -> None:
        # 10주 @1,000 + 10주 @2,000 => 평균 1,500. 10주를 20,000원에 팔면
        # 원가 15,000이므로 이익 5,000.
        self.flow("2025-01-10", "buy", "-10000", quantity="10", unit_price="1000")
        self.flow("2025-01-20", "buy", "-20000", quantity="10", unit_price="2000")
        self.flow("2025-05-10", "sell", "20000", quantity="10", unit_price="2000")

        series = build_realized()

        self.assertEqual(series.total, Decimal("5000"))


if __name__ == "__main__":
    pass
