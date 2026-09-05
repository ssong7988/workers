from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from portfolio.importing import (
    PortfolioImportError,
    latest_complete_date,
    record_import_run,
)
from portfolio.models import (
    UNCLASSIFIED_ASSET_CLASS_ID,
    CashFlow,
    ImportRun,
    Instrument,
    PositionSnapshot,
)

from .factories import balance_payload, hash_of, make_account, position


class RecordImportRunTests(TestCase):
    def setUp(self) -> None:
        self.account = make_account()

    def test_unknown_instrument_lands_in_unclassified(self) -> None:
        result = record_import_run(
            balance_payload(
                "kb-brokerage",
                "2026-09-01",
                [position("005930", "1000000", name="삼성전자")],
            )
        )
        self.assertEqual(result.new_instruments, ["005930"])
        instrument = Instrument.objects.get(pk="005930")
        self.assertEqual(instrument.asset_class_id, UNCLASSIFIED_ASSET_CLASS_ID)
        self.assertEqual(instrument.name, "삼성전자")

    def test_same_file_twice_changes_nothing(self) -> None:
        payload = balance_payload(
            "kb-brokerage", "2026-09-01", [position("005930", "1000000")]
        )
        record_import_run(payload)
        again = record_import_run(payload)
        self.assertTrue(again.duplicate)
        self.assertEqual(PositionSnapshot.objects.count(), 1)
        self.assertEqual(ImportRun.objects.count(), 1)

    def test_redownload_same_day_replaces_its_own_rows(self) -> None:
        record_import_run(
            balance_payload(
                "kb-brokerage",
                "2026-09-01",
                [position("005930", "1000000"), position("000660", "500000")],
                file_hash=hash_of("first"),
            )
        )
        record_import_run(
            balance_payload(
                "kb-brokerage",
                "2026-09-01",
                [position("005930", "1100000")],
                file_hash=hash_of("second"),
            )
        )
        self.assertEqual(ImportRun.objects.count(), 1)
        rows = list(PositionSnapshot.objects.all())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].market_value_krw, Decimal("1100000.00"))

    def test_overlapping_trade_periods_do_not_duplicate_cash_flows(self) -> None:
        flow = {
            "occurred_on": "2026-08-20",
            "flow_type": "deposit",
            "amount": "1000000",
            "external_key": "20260820-0001",
        }
        for index, day in enumerate(("2026-09-01", "2026-09-02")):
            record_import_run(
                {
                    "account": "kb-brokerage",
                    "as_of": day,
                    "document_type": "transfer",
                    "file_hash": hash_of(f"transfer-{index}"),
                    "cash_flows": [flow],
                }
            )
        self.assertEqual(CashFlow.objects.count(), 1)
        self.assertTrue(CashFlow.objects.get().is_external)

    def test_trades_are_not_external_cash_flows(self) -> None:
        record_import_run(
            {
                "account": "kb-brokerage",
                "as_of": "2026-09-01",
                "document_type": "trade",
                "file_hash": hash_of("trade"),
                "cash_flows": [
                    {
                        "occurred_on": "2026-09-01",
                        "flow_type": "buy",
                        "amount": "500000",
                        "external_key": "T-1",
                        "code": "005930",
                    }
                ],
            }
        )
        self.assertFalse(CashFlow.objects.get().is_external)

    def test_foreign_position_without_krw_value_is_rejected(self) -> None:
        payload = balance_payload(
            "kb-brokerage",
            "2026-09-01",
            [
                {
                    "code": "AAPL",
                    "quantity": "10",
                    "currency": "USD",
                    "market_value": "2000",
                }
            ],
        )
        with self.assertRaises(PortfolioImportError):
            record_import_run(payload)

    def test_unknown_account_is_rejected(self) -> None:
        with self.assertRaises(PortfolioImportError):
            record_import_run(
                balance_payload("kb-isa", "2026-09-01", [position("005930", "1")])
            )

    def test_positions_are_rejected_on_trade_documents(self) -> None:
        with self.assertRaises(PortfolioImportError):
            record_import_run(
                {
                    "account": "kb-brokerage",
                    "as_of": "2026-09-01",
                    "document_type": "trade",
                    "file_hash": hash_of("x"),
                    "positions": [position("005930", "1")],
                }
            )


class CompletenessTests(TestCase):
    def setUp(self) -> None:
        self.brokerage = make_account("kb-brokerage")
        self.isa = make_account("kb-isa", account_type="isa")

    def _import(self, account: str, day: str) -> None:
        record_import_run(
            balance_payload(
                account, day, [position("005930", "1000000")], file_hash=hash_of(account + day)
            )
        )

    def test_day_is_incomplete_until_every_required_account_arrives(self) -> None:
        self._import("kb-brokerage", "2026-09-01")
        self.assertIsNone(latest_complete_date())
        self._import("kb-isa", "2026-09-01")
        self.assertEqual(latest_complete_date(), date(2026, 9, 1))

    def test_optional_account_does_not_block_completeness(self) -> None:
        self.isa.required = False
        self.isa.save()
        self._import("kb-brokerage", "2026-09-01")
        self.assertEqual(latest_complete_date(), date(2026, 9, 1))

    def test_partial_later_day_does_not_replace_the_last_complete_one(self) -> None:
        self._import("kb-brokerage", "2026-09-01")
        self._import("kb-isa", "2026-09-01")
        self._import("kb-brokerage", "2026-09-02")
        self.assertEqual(latest_complete_date(), date(2026, 9, 1))
