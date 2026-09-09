"""시세 출처를 읽고 가격을 받아오는 규칙.

바깥 API를 실제로 부르지 않는다. 응답 문자열만 넣어 판정을 시험한다.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from portfolio.models import AssetClass, Instrument

from portfolio.prices import (
    PriceError,
    describe_source_error,
    fetch_prices,
    parse_source,
    parse_upbit,
    parse_upbit_daily,
    parse_yahoo_daily,
    fetch_daily_prices,
)

BODY = (
    '[{"market":"KRW-BTC","trade_price":95000000.0},'
    '{"market":"KRW-ETH","trade_price":4300000.0}]'
)


class ParseSourceTests(unittest.TestCase):
    def test_reads_provider_and_symbol(self) -> None:
        self.assertEqual(parse_source("upbit:KRW-BTC"), ("upbit", "KRW-BTC"))
        self.assertEqual(parse_source("  Upbit : KRW-ETH "), ("upbit", "KRW-ETH"))

    def test_anything_else_is_not_a_source(self) -> None:
        for text in ("", "KRW-BTC", "upbit:", ":KRW-BTC", None):
            with self.subTest(text=text):
                self.assertIsNone(parse_source(text))


class ParseUpbitTests(unittest.TestCase):
    def test_reads_the_current_price(self) -> None:
        prices = parse_upbit(BODY, ["KRW-BTC", "KRW-ETH"])

        self.assertEqual(prices["KRW-BTC"], Decimal("95000000.0"))

    def test_a_missing_symbol_is_an_error_not_a_zero(self) -> None:
        """빠진 심볼을 넘기면 그 자산의 평가액을 지어내게 된다."""
        with self.assertRaisesRegex(PriceError, "시세에 없는 심볼"):
            parse_upbit(BODY, ["KRW-BTC", "KRW-DOGE"])

    def test_a_broken_response_is_an_error(self) -> None:
        with self.assertRaises(PriceError):
            parse_upbit("not json", ["KRW-BTC"])

    def test_reads_daily_closes_in_oldest_first_order(self) -> None:
        body = (
            '[{"market":"KRW-BTC","candle_date_time_kst":"2026-09-03T00:00:00",'
            '"trade_price":103},{"market":"KRW-BTC",'
            '"candle_date_time_kst":"2026-09-02T00:00:00","trade_price":101}]'
        )
        self.assertEqual(
            parse_upbit_daily(body, "KRW-BTC"),
            [(date(2026, 9, 2), Decimal("101")), (date(2026, 9, 3), Decimal("103"))],
        )

    def test_daily_fetch_pages_and_keeps_requested_dates(self) -> None:
        calls = []

        def read(url: str) -> str:
            calls.append(url)
            newest = 300 if len(calls) == 1 else 100
            rows = [
                {"market": "KRW-BTC", "candle_date_time_kst": f"2026-01-{day:02d}T00:00:00", "trade_price": newest + day}
                for day in ((3, 2) if len(calls) == 1 else (1,))
            ]
            import json
            return json.dumps(rows)

        rows = fetch_daily_prices(
            "upbit:KRW-BTC", start=date(2026, 1, 1), end=date(2026, 1, 3), read=read
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual([row[0] for row in rows], [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)])

    def test_reads_yahoo_closes_and_skips_nulls(self) -> None:
        body = (
            '{"chart":{"result":[{"timestamp":[1767225600,1767312000],'
            '"indicators":{"quote":[{"close":[100.5,null]}]}}],"error":null}}'
        )
        rows = parse_yahoo_daily(body, "005930.KS")
        self.assertEqual(rows, [(date(2026, 1, 1), Decimal("100.5"))])


class FetchPricesTests(unittest.TestCase):
    def test_calls_the_provider_once_for_every_symbol(self) -> None:
        asked: list[str] = []

        def read(url: str) -> str:
            asked.append(url)
            return BODY

        prices = fetch_prices(["upbit:KRW-BTC", "upbit:KRW-ETH"], read=read)

        self.assertEqual(len(asked), 1)
        self.assertIn("KRW-BTC,KRW-ETH", asked[0])
        self.assertEqual(prices["upbit:KRW-ETH"], Decimal("4300000.0"))

    def test_an_unknown_provider_stops(self) -> None:
        with self.assertRaisesRegex(PriceError, "모르는 시세 업체"):
            fetch_prices(["binance:BTCUSDT"], read=lambda url: BODY)

    def test_a_malformed_source_stops(self) -> None:
        with self.assertRaisesRegex(PriceError, "시세 출처 형식"):
            fetch_prices(["KRW-BTC"], read=lambda url: BODY)


if __name__ == "__main__":
    unittest.main()


class DescribeSourceErrorTests(unittest.TestCase):
    """admin에서 저장하기 전에 오타를 잡는 규칙."""

    def test_a_usable_source_has_nothing_to_say(self) -> None:
        self.assertEqual(describe_source_error("upbit:KRW-BTC"), "")

    def test_a_bare_symbol_is_explained(self) -> None:
        self.assertIn("upbit:KRW-BTC", describe_source_error("KRW-BTC"))

    def test_an_unknown_provider_is_named(self) -> None:
        self.assertIn("binance", describe_source_error("binance:BTCKRW"))


class InstrumentSourceValidationTests(TestCase):
    """모델이 저장 시점에 같은 규칙을 쓴다."""

    def setUp(self) -> None:
        self.asset_class = AssetClass.objects.create(id="crypto", name="코인")

    def _instrument(self, source: str) -> Instrument:
        return Instrument(
            code="KRW-BTC",
            name="비트코인",
            asset_class=self.asset_class,
            price_source=source,
        )

    def test_a_good_source_saves(self) -> None:
        self._instrument("upbit:KRW-BTC").full_clean()

    def test_a_typo_stops_at_save_not_at_dawn(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            self._instrument("upbitKRW-BTC").full_clean()
        self.assertIn("price_source", caught.exception.message_dict)

    def test_an_empty_source_is_allowed(self) -> None:
        self._instrument("").full_clean()
