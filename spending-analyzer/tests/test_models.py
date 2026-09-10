import unittest

from spending_analyzer.models import Statement, Transaction


def make_transaction(**overrides) -> Transaction:
    defaults = dict(
        billing_month="2026-09",
        used_at="2026-08-14",
        merchant="스타벅스 과천점",
        merchant_norm="스타벅스",
        billed_won=5_600,
        total_won=5_600,
        payment_type="일시불",
    )
    defaults.update(overrides)
    return Transaction(**defaults)


class TransactionTest(unittest.TestCase):
    def test_paid_in_full_is_not_an_installment(self):
        transaction = make_transaction()
        self.assertFalse(transaction.is_installment)
        self.assertEqual(transaction.remaining_installments, 0)

    def test_installment_counts_only_the_charges_still_to_come(self):
        transaction = make_transaction(
            payment_type="할부",
            billed_won=50_000,
            total_won=300_000,
            installment_seq=2,
            installment_months=6,
        )
        self.assertTrue(transaction.is_installment)
        self.assertEqual(transaction.remaining_installments, 4)

    def test_final_installment_has_nothing_remaining(self):
        transaction = make_transaction(
            payment_type="할부", installment_seq=6, installment_months=6
        )
        self.assertEqual(transaction.remaining_installments, 0)

    def test_round_trips_through_a_dict(self):
        transaction = make_transaction(category="카페·간식", category_source="rule")
        restored = Transaction.from_dict(transaction.to_dict())
        self.assertEqual(restored, transaction)

    def test_from_dict_ignores_unknown_keys(self):
        payload = make_transaction().to_dict()
        payload["없는필드"] = "무시되어야 함"
        self.assertEqual(Transaction.from_dict(payload).merchant_norm, "스타벅스")


class StatementTest(unittest.TestCase):
    def test_discrepancy_is_zero_when_rows_match_the_header(self):
        statement = Statement(
            billing_month="2026-09",
            payment_date="2026-09-25",
            total_billed_won=15_600,
            transactions=[
                make_transaction(billed_won=5_600),
                make_transaction(merchant_norm="이마트", billed_won=10_000),
            ],
        )
        self.assertEqual(statement.parsed_total_won, 15_600)
        self.assertEqual(statement.discrepancy_won, 0)

    def test_a_missed_row_shows_up_as_a_negative_discrepancy(self):
        statement = Statement(
            billing_month="2026-09",
            payment_date="2026-09-25",
            total_billed_won=15_600,
            transactions=[make_transaction(billed_won=5_600)],
        )
        self.assertEqual(statement.discrepancy_won, -10_000)

    def test_cancellations_reduce_the_parsed_total(self):
        statement = Statement(
            billing_month="2026-09",
            payment_date="2026-09-25",
            total_billed_won=0,
            transactions=[
                make_transaction(billed_won=5_600),
                make_transaction(billed_won=-5_600),
            ],
        )
        self.assertEqual(statement.discrepancy_won, 0)

    def test_round_trips_through_a_dict(self):
        statement = Statement(
            billing_month="2026-09",
            payment_date="2026-09-25",
            total_billed_won=5_600,
            transactions=[make_transaction()],
            source_ref="<abc@samsungcard.com>",
            parsed_at="2026-09-09T12:00:00+09:00",
        )
        restored = Statement.from_dict(statement.to_dict())
        self.assertEqual(restored, statement)


if __name__ == "__main__":
    unittest.main()
