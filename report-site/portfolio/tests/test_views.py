from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.test import TestCase

from portfolio.models import CashFlow, PortfolioTarget
from portfolio.performance import rebuild_metrics

from .factories import make_account, make_asset_class, make_instrument, record_balance


ALLOCATION_URL = f"{settings.ALLOCATION_URL_PATH}/"
PERFORMANCE_URL = f"{settings.PERFORMANCE_URL_PATH}/"


class EmptyScreenTests(TestCase):
    def test_both_screens_render_without_any_data(self) -> None:
        for url, expected in (
            (ALLOCATION_URL, "아직 완전한 수집 결과가 없습니다"),
            (PERFORMANCE_URL, "아직 성과를 계산할 자료가 없습니다"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, expected)


class PopulatedScreenTests(TestCase):
    def setUp(self) -> None:
        account = make_account()
        stocks = make_asset_class("korea-stock", "한국 주식", "domestic_stock", 10)
        bonds = make_asset_class("bond", "채권", "bond", 20)
        samsung = make_instrument("005930", stocks)
        kodex = make_instrument("KODEX", bonds)
        for day, stock_value, bond_value in (
            (date(2026, 8, 31), "600000", "400000"),
            (date(2026, 9, 1), "600000", "200000"),
        ):
            record_balance(account, samsung, day, stock_value)
            record_balance(account, kodex, day, bond_value)
        CashFlow.objects.create(
            occurred_on=date(2026, 9, 1),
            account=account,
            flow_type="withdrawal",
            amount=Decimal("-200000"),
            amount_krw=Decimal("-200000"),
            is_external=True,
            external_key="W-1",
        )
        for asset_class, percent in ((stocks, "60"), (bonds, "40")):
            PortfolioTarget.objects.create(
                effective_from=date(2026, 1, 1),
                asset_class=asset_class,
                target_percent=Decimal(percent),
            )
        rebuild_metrics()

    def test_allocation_shows_rebalancing_and_the_two_tabs(self) -> None:
        response = self.client.get(ALLOCATION_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "한국 주식")
        # 80만원의 60/40 목표 → 주식 -12만원, 채권 +12만원
        self.assertContains(response, "-12만원")
        self.assertContains(response, "+12만원")
        self.assertContains(response, PERFORMANCE_URL)

    def test_performance_range_links_and_summary(self) -> None:
        response = self.client.get(PERFORMANCE_URL, {"range": "1m"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MDD")
        self.assertContains(response, "1개월")
        self.assertContains(response, ALLOCATION_URL)

    def test_unknown_range_falls_back_to_the_default(self) -> None:
        response = self.client.get(PERFORMANCE_URL, {"range": "nonsense"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1년")
