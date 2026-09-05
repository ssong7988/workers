"""요청 본문 조립과 멱등성 키."""

from __future__ import annotations

import unittest

from stock_importer.payload import POSITION_KEYS, build_import_payload, rows_hash


def row(code: str, value: str) -> dict:
    return {
        "account_number": "338-***-400 01",
        "code": code,
        "name": code.upper(),
        "currency": "KRW",
        "quantity": "10",
        "average_cost": "1000",
        "cost_amount": "10000",
        "price": "1100",
        "market_value": value,
        "market_value_krw": value,
        "unrealized_pl": "1000",
    }


class PayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [row("bbb", "20000"), row("aaa", "11000")]

    def test_body_carries_the_account_number_not_an_id(self) -> None:
        payload = build_import_payload("338-***-400 01", "2026-09-05", self.rows)
        self.assertEqual(payload["account_number"], "338-***-400 01")
        self.assertNotIn("account", payload)
        self.assertEqual(payload["document_type"], "balance")
        self.assertEqual(payload["status"], "success")

    def test_positions_keep_only_the_keys_the_server_knows(self) -> None:
        payload = build_import_payload("338-***-400 01", "2026-09-05", self.rows)
        for position in payload["positions"]:
            self.assertEqual(set(position), set(POSITION_KEYS))
            self.assertNotIn("account_number", position)

    def test_positions_are_sorted_so_the_hash_is_stable(self) -> None:
        payload = build_import_payload("338-***-400 01", "2026-09-05", self.rows)
        self.assertEqual([p["code"] for p in payload["positions"]], ["aaa", "bbb"])

    def test_the_same_holdings_in_another_order_hash_the_same(self) -> None:
        # 스크롤 순서가 달라져도 같은 자료면 서버가 duplicate로 넘겨야 한다.
        self.assertEqual(
            rows_hash("338-***-400 01", self.rows),
            rows_hash("338-***-400 01", list(reversed(self.rows))),
        )

    def test_a_changed_amount_changes_the_hash(self) -> None:
        changed = [row("bbb", "20001"), row("aaa", "11000")]
        self.assertNotEqual(
            rows_hash("338-***-400 01", self.rows),
            rows_hash("338-***-400 01", changed),
        )

    def test_two_accounts_with_identical_holdings_hash_differently(self) -> None:
        self.assertNotEqual(
            rows_hash("338-***-400 01", self.rows),
            rows_hash("338-***-781 01", self.rows),
        )

    def test_the_hash_is_a_sha256_hex_string(self) -> None:
        digest = build_import_payload("338-***-400 01", "2026-09-05", self.rows)["file_hash"]
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in digest))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
