import tempfile
import unittest
from pathlib import Path

from spending_analyzer.config import load_config
from spending_analyzer.models import Statement, Transaction
from spending_analyzer.storage import StatementStore


VALID = """
mail:
  senders: [samsungcard.com]
  subject_keywords: [명세서]
  since: "2025-01-01"
analysis:
  fixed_cost_months: 3
  top_merchants: 10
  budgets:
    식비: 600000
ai:
  model: claude-opus-5
"""


class ConfigTest(unittest.TestCase):
    def load(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text(text, encoding="utf-8")
            return load_config(path)

    def test_reads_a_valid_file(self):
        config = self.load(VALID)
        self.assertEqual(config.mail.senders, ("samsungcard.com",))
        self.assertEqual(config.mail.port, 993)
        self.assertEqual(config.analysis.budgets, (("식비", 600000),))
        self.assertEqual(config.ai.model, "claude-opus-5")

    def test_rejects_a_config_with_no_sender(self):
        with self.assertRaisesRegex(ValueError, "senders"):
            self.load("mail:\n  senders: []\n")

    def test_rejects_a_malformed_since_date(self):
        with self.assertRaisesRegex(ValueError, "since"):
            self.load('mail:\n  senders: [a.com]\n  since: "2025/01/01"\n')

    def test_rejects_a_fixed_cost_window_too_short_to_mean_anything(self):
        with self.assertRaisesRegex(ValueError, "fixed_cost_months"):
            self.load("mail:\n  senders: [a.com]\nanalysis:\n  fixed_cost_months: 1\n")

    def test_missing_file_names_the_path(self):
        with self.assertRaisesRegex(ValueError, "설정 파일이 없습니다"):
            load_config(Path("/nonexistent/settings.yaml"))


def make_statement(month: str, total: int) -> Statement:
    return Statement(
        billing_month=month,
        payment_date=f"{month}-25",
        total_billed_won=total,
        transactions=[
            Transaction(
                billing_month=month,
                used_at=f"{month}-14",
                merchant="이마트 과천점",
                merchant_norm="이마트",
                billed_won=total,
                total_won=total,
                payment_type="일시불",
            )
        ],
        source_ref=f"<{month}@samsungcard.com>",
    )


class StatementStoreTest(unittest.TestCase):
    def test_saves_and_loads_a_month(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StatementStore(Path(directory))
            store.save(make_statement("2026-09", 120_000))
            loaded = store.load("2026-09")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.total_billed_won, 120_000)
            self.assertEqual(loaded.transactions[0].merchant_norm, "이마트")

    def test_a_resent_statement_replaces_the_month_rather_than_appending(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StatementStore(Path(directory))
            store.save(make_statement("2026-09", 120_000))
            store.save(make_statement("2026-09", 130_000))
            self.assertEqual(store.months(), ["2026-09"])
            self.assertEqual(store.load("2026-09").total_billed_won, 130_000)
            self.assertEqual(len(store.load("2026-09").transactions), 1)

    def test_months_come_back_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StatementStore(Path(directory))
            for month in ("2026-10", "2026-08", "2026-09"):
                store.save(make_statement(month, 1_000))
            self.assertEqual(store.months(), ["2026-08", "2026-09", "2026-10"])
            self.assertEqual(len(store.load_all()), 3)

    def test_missing_month_is_none_not_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(StatementStore(Path(directory)).load("2026-01"))

    def test_rejects_a_bad_month_label(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "청구월"):
                StatementStore(Path(directory)).load("2026/09")

    def test_leaves_no_temporary_file_behind(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StatementStore(Path(directory))
            store.save(make_statement("2026-09", 1_000))
            leftovers = list(store.statements_dir.glob("*.tmp"))
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
