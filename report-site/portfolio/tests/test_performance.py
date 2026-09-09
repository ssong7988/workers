from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from portfolio.models import CashFlow, DailyPortfolioMetric, HableAccountDailyMetric
from portfolio.hable_history import portfolio_history
from portfolio.performance import class_performance, rebuild_metrics

from .factories import make_account, make_asset_class, make_instrument, record_balance


def close(value: Decimal, expected: str, places: int = 6) -> bool:
    return abs(value - Decimal(expected)) < Decimal(10) ** -places


class HableHistoryTests(TestCase):
    def test_combines_only_days_present_for_every_kb_account(self) -> None:
        first = make_account("kb-a", masked_number="1**")
        second = make_account("kb-b", masked_number="2**")
        for account, first_value, second_value, second_return in (
            (first, "100000", "110000", "0.10"),
            (second, "300000", "270000", "-0.10"),
        ):
            for day, value, daily_return in (
                (date(2026, 1, 1), first_value, "0"),
                (date(2026, 1, 2), second_value, second_return),
            ):
                HableAccountDailyMetric.objects.create(
                    account=account, as_of=day, market_value=value,
                    investment_pl="0", daily_return=daily_return,
                    account_cumulative_return=daily_return,
                )
        rows = portfolio_history()
        self.assertEqual(len(rows), 2)
        # 10% * 100/400 + -10% * 300/400 = -5%
        self.assertTrue(close(rows[-1].cumulative_return, "-0.05"))


class RebuildMetricsTests(TestCase):
    """손으로 계산한 사례 하나를 그대로 맞춘다.

    1일 100만원 → 2일 115만원(그날 10만원 입금) → 3일 103.5만원.
      2일 수익률 = (115 - 100 - 10) / 100 = +5%   (장 마감 입금이라 가중치 0)
      3일 수익률 = (103.5 - 115) / 115 = -10%
      지수 = 1.05 × 0.9 = 0.945,  누적 수익률 -5.5%
      고점 1.05 이후 낙폭 -10%가 그대로 MDD
      투자손익 = 103.5 - 100 - 10 = -6.5만원
    """

    def setUp(self) -> None:
        self.account = make_account()
        self.asset_class = make_asset_class("bond", "채권", "bond")
        self.instrument = make_instrument("KODEX", self.asset_class)
        for day, value in (
            (date(2026, 1, 1), "1000000"),
            (date(2026, 1, 2), "1150000"),
            (date(2026, 1, 3), "1035000"),
        ):
            record_balance(self.account, self.instrument, day, value)
        CashFlow.objects.create(
            occurred_on=date(2026, 1, 2),
            account=self.account,
            flow_type="deposit",
            amount=Decimal("100000"),
            amount_krw=Decimal("100000"),
            is_external=True,
            external_key="D-1",
        )

    def test_returns_index_and_drawdown(self) -> None:
        self.assertEqual(rebuild_metrics(), 3)
        rows = {row.as_of: row for row in DailyPortfolioMetric.objects.all()}

        self.assertTrue(close(rows[date(2026, 1, 2)].daily_return, "0.05"))
        self.assertTrue(close(rows[date(2026, 1, 3)].daily_return, "-0.10"))

        last = rows[date(2026, 1, 3)]
        self.assertTrue(close(last.index_value, "0.945"))
        self.assertTrue(close(last.cumulative_return, "-0.055"))
        self.assertTrue(close(last.max_drawdown, "-0.10"))
        self.assertEqual(last.investment_pl, Decimal("-65000.00"))
        self.assertEqual(last.cumulative_external_flow, Decimal("100000.00"))

    def test_deposit_alone_is_not_a_return(self) -> None:
        """입금만 있고 값이 그대로면 수익률은 0이어야 한다."""
        DailyPortfolioMetric.objects.all().delete()
        CashFlow.objects.all().delete()
        record_balance(
            self.account, self.instrument, date(2026, 1, 4), "1235000"
        )
        CashFlow.objects.create(
            occurred_on=date(2026, 1, 4),
            account=self.account,
            flow_type="deposit",
            amount=Decimal("200000"),
            amount_krw=Decimal("200000"),
            is_external=True,
            external_key="D-2",
        )
        rebuild_metrics()
        last = DailyPortfolioMetric.objects.get(as_of=date(2026, 1, 4))
        self.assertTrue(close(last.daily_return, "0"))

    def test_flow_in_the_middle_of_a_gap_is_weighted(self) -> None:
        """수집을 건너뛴 구간의 입금은 경과일만큼 분모에 들어간다."""
        DailyPortfolioMetric.objects.all().delete()
        CashFlow.objects.all().delete()
        record_balance(self.account, self.instrument, date(2026, 1, 11), "1200000")
        CashFlow.objects.create(
            # 직전 완전 수집일은 1/3이므로 구간은 8일이고, 1/6은 3일째다.
            # 가중치 (8 - 3) / 8 = 0.625.
            occurred_on=date(2026, 1, 6),
            account=self.account,
            flow_type="deposit",
            amount=Decimal("100000"),
            amount_krw=Decimal("100000"),
            is_external=True,
            external_key="D-3",
        )
        rebuild_metrics()
        row = DailyPortfolioMetric.objects.get(as_of=date(2026, 1, 11))
        # (1200000 - 1035000 - 100000) / (1035000 + 100000 * 0.625)
        self.assertTrue(close(row.daily_return, "0.05922551", places=7))


class ClassPerformanceTests(TestCase):
    def setUp(self) -> None:
        self.account = make_account()
        self.stocks = make_asset_class("korea-stock", "한국 주식", "domestic_stock", 10)
        self.bonds = make_asset_class("bond", "채권", "bond", 20)
        self.samsung = make_instrument("005930", self.stocks)
        self.kodex = make_instrument("KODEX", self.bonds)

    def test_one_observation_gives_no_return(self) -> None:
        record_balance(self.account, self.samsung, date(2026, 1, 1), "1000000")
        rows = class_performance([date(2026, 1, 1)])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].period_return)

    def test_money_moved_in_is_not_counted_as_gain(self) -> None:
        days = [date(2026, 1, 1), date(2026, 1, 2)]
        record_balance(self.account, self.samsung, days[0], "1000000")
        record_balance(self.account, self.kodex, days[0], "1000000")
        # 채권 50만원을 팔아 주식을 샀다. 가격은 하나도 움직이지 않았다.
        record_balance(self.account, self.samsung, days[1], "1500000")
        record_balance(self.account, self.kodex, days[1], "500000")
        for flow_type, code, amount in (
            ("buy", "005930", "500000"),
            ("sell", "KODEX", "500000"),
        ):
            CashFlow.objects.create(
                occurred_on=days[1],
                account=self.account,
                instrument_id=code,
                flow_type=flow_type,
                amount=Decimal(amount),
                amount_krw=Decimal(amount),
                external_key=f"{flow_type}-1",
            )
        rows = {row.asset_class_id: row for row in class_performance(days)}
        self.assertTrue(close(rows["korea-stock"].period_return, "0"))
        self.assertTrue(close(rows["bond"].period_return, "0"))
