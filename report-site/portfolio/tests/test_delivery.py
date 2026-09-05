"""카카오 요약 한 통과 버튼 두 개.

부동산 쪽과 같은 규칙을 지키는지 본다 - 이미지 없음, 텍스트 1통, 버튼은 정확히
둘, 그리고 공개 주소가 그 기준일을 서빙할 때만 버튼을 붙인다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from portfolio.delivery import (
    ALLOCATION_BUTTON,
    PERFORMANCE_BUTTON,
    TEXT_LIMIT,
    StockDeliveryError,
    build_digest,
    send_digest,
)
from portfolio.models import CashFlow, PortfolioTarget
from portfolio.performance import rebuild_metrics

from .factories import make_account, make_asset_class, make_instrument, record_balance


PUBLIC = "https://example.ts.net"


class NoDataTests(TestCase):
    def test_refuses_when_there_is_no_complete_day(self) -> None:
        with self.assertRaises(StockDeliveryError):
            build_digest()


class DigestTests(TestCase):
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

    def test_message_carries_the_numbers_a_person_wants(self) -> None:
        digest = build_digest()
        self.assertEqual(digest.as_of, date(2026, 9, 1))
        self.assertIn("금융자산 2026.09.01", digest.message)
        self.assertIn("평가 80만원", digest.message)
        self.assertIn("MDD", digest.message)
        # 80만원의 60/40 목표 → 가장 큰 조정은 12만원짜리 둘 중 하나다.
        self.assertIn("리밸런싱", digest.message)
        self.assertIn("12만원", digest.message)

    def test_message_stays_inside_the_kakao_body_limit(self) -> None:
        self.assertLessEqual(len(build_digest().message), TEXT_LIMIT)

    @override_settings(STOCK_ALLOCATION_URL="", STOCK_PERFORMANCE_URL="")
    def test_no_public_url_means_no_buttons(self) -> None:
        self.assertEqual(build_digest().buttons, [])

    @override_settings(
        STOCK_ALLOCATION_URL="http://127.0.0.1:8000/stock/allocation/",
        STOCK_PERFORMANCE_URL="http://127.0.0.1:8000/stock/performance/",
    )
    def test_loopback_is_never_sent_as_a_button(self) -> None:
        # 카카오가 열 수 없는 주소다. 붙이느니 안 붙인다.
        self.assertEqual(build_digest().buttons, [])

    @override_settings(
        STOCK_ALLOCATION_URL=f"{PUBLIC}/stock/allocation/",
        STOCK_PERFORMANCE_URL=f"{PUBLIC}/stock/performance/",
    )
    def test_buttons_only_when_the_public_page_serves_that_day(self) -> None:
        with patch("portfolio.delivery._serves", return_value=False):
            self.assertEqual(build_digest().buttons, [])
        with patch("portfolio.delivery._serves", return_value=True):
            buttons = build_digest().buttons
        self.assertEqual([label for label, _ in buttons], [ALLOCATION_BUTTON, PERFORMANCE_BUTTON])
        self.assertTrue(all(url.startswith("https://") for _, url in buttons))


class SendTests(TestCase):
    def setUp(self) -> None:
        account = make_account()
        stocks = make_asset_class("korea-stock", "한국 주식", "domestic_stock", 10)
        record_balance(account, make_instrument("005930", stocks), date(2026, 9, 1), "1000000")
        rebuild_metrics()

    def test_sends_one_text_message_and_reports_what_went(self) -> None:
        sent: list[tuple[str, list]] = []

        class Fake:
            def send_links(self, message, buttons):
                sent.append((message, buttons))

        with override_settings(STOCK_ALLOCATION_URL="", STOCK_PERFORMANCE_URL=""):
            result = send_digest(notifier=Fake())
        self.assertEqual(len(sent), 1)
        self.assertIn("금융자산", sent[0][0])
        self.assertEqual(sent[0][1], [])
        self.assertIn("버튼은 붙이지 않았습니다", result)

    def test_a_kakao_failure_is_reported_not_swallowed(self) -> None:
        class Broken:
            def send_links(self, message, buttons):
                raise RuntimeError("토큰 만료")

        with self.assertRaises(StockDeliveryError) as caught:
            send_digest(notifier=Broken())
        self.assertIn("토큰 만료", str(caught.exception))
