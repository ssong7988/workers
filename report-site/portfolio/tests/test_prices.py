"""시세 출처를 읽고 가격을 받아오는 규칙.

바깥 API를 실제로 부르지 않는다. 응답 문자열만 넣어 판정을 시험한다.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from portfolio.prices import PriceError, fetch_prices, parse_source, parse_upbit

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
