import tempfile
import unittest
from pathlib import Path

from spending_analyzer.analyze import (
    analyze,
    category_breakdown,
    fixed_costs,
    installment_outlook,
    monthly_totals,
    next_month,
    payment_type_mix,
    top_merchants,
    trailing_average,
    uncategorized_merchants,
)
from spending_analyzer.categorize import load_rules, normalize_merchant
from spending_analyzer.models import UNCATEGORIZED, AnalysisConfig, Statement, Transaction

RULES = load_rules(Path(__file__).resolve().parents[1] / "config" / "rules.yaml")


def txn(
    merchant: str,
    billed: int,
    *,
    month: str = "2026-09",
    category: str = "기타",
    payment_type: str = "일시불",
    total: int | None = None,
    seq: int = 0,
    months: int = 0,
) -> Transaction:
    return Transaction(
        billing_month=month,
        used_at=f"{month}-14",
        merchant=merchant,
        merchant_norm=normalize_merchant(merchant),
        billed_won=billed,
        total_won=total if total is not None else billed,
        payment_type=payment_type,
        installment_seq=seq,
        installment_months=months,
        category=category,
    )


def statement(month: str, transactions: list[Transaction]) -> Statement:
    return Statement(
        billing_month=month,
        payment_date=f"{month}-25",
        total_billed_won=sum(item.billed_won for item in transactions),
        transactions=transactions,
    )


class NextMonthTest(unittest.TestCase):
    def test_rolls_over_the_year(self):
        self.assertEqual(next_month("2026-12"), "2027-01")

    def test_pads_a_single_digit_month(self):
        self.assertEqual(next_month("2026-08"), "2026-09")


class MonthlyTotalsTest(unittest.TestCase):
    def test_month_over_month_change(self):
        totals = monthly_totals(
            [
                statement("2026-08", [txn("a", 100_000)]),
                statement("2026-09", [txn("b", 150_000, month="2026-09")]),
            ]
        )
        self.assertEqual(totals[1].delta, 50_000)
        self.assertEqual(totals[1].percent, 0.5)

    def test_a_gap_in_the_statements_leaves_the_comparison_empty(self):
        # Comparing across a missing month would silently invent a trend.
        totals = monthly_totals(
            [
                statement("2026-06", [txn("a", 100_000)]),
                statement("2026-09", [txn("b", 150_000)]),
            ]
        )
        self.assertIsNone(totals[1].delta)
        self.assertIsNone(totals[1].percent)

    def test_the_first_month_has_nothing_to_compare_against(self):
        totals = monthly_totals([statement("2026-09", [txn("a", 1_000)])])
        self.assertIsNone(totals[0].delta)

    def test_results_come_back_oldest_first(self):
        totals = monthly_totals(
            [statement("2026-09", [txn("a", 1)]), statement("2026-07", [txn("b", 1)])]
        )
        self.assertEqual([item.month for item in totals], ["2026-07", "2026-09"])


class TrailingAverageTest(unittest.TestCase):
    def test_averages_only_the_window(self):
        totals = monthly_totals(
            [statement(f"2026-{m:02d}", [txn("a", m * 10_000)]) for m in range(1, 8)]
        )
        # Months 2..7 -> 20k..70k, mean 45k. January is outside the window.
        self.assertEqual(trailing_average(totals, window=6), 45_000)

    def test_no_months_is_zero_not_an_error(self):
        self.assertEqual(trailing_average([]), 0)


class CategoryBreakdownTest(unittest.TestCase):
    def test_shares_add_up_and_sort_by_size(self):
        rows = category_breakdown([txn("a", 75_000, category="식비"), txn("b", 25_000, category="교통")])
        self.assertEqual(rows[0]["category"], "식비")
        self.assertEqual(rows[0]["share"], 0.75)
        self.assertAlmostEqual(sum(row["share"] for row in rows), 1.0, places=4)

    def test_a_category_that_disappeared_is_still_listed_at_zero(self):
        rows = category_breakdown([txn("a", 10_000, category="식비")], [txn("b", 40_000, category="쇼핑")])
        shopping = next(row for row in rows if row["category"] == "쇼핑")
        self.assertEqual(shopping["total"], 0)
        self.assertEqual(shopping["delta"], -40_000)

    def test_a_month_totalling_zero_gives_no_share_rather_than_dividing_by_zero(self):
        rows = category_breakdown([txn("a", 10_000, category="식비"), txn("b", -10_000, category="식비")])
        self.assertEqual(rows[0]["share"], 0.0)

    def test_a_new_category_has_no_percentage_change(self):
        rows = category_breakdown([txn("a", 10_000, category="식비")], [])
        self.assertIsNone(rows[0]["percent"])


class PaymentTypeMixTest(unittest.TestCase):
    def test_groups_and_ranks_by_amount(self):
        rows = payment_type_mix(
            [
                txn("a", 30_000, payment_type="일시불"),
                txn("b", 70_000, payment_type="할부"),
            ]
        )
        self.assertEqual(rows[0]["type"], "할부")
        self.assertEqual(rows[0]["share"], 0.7)


class InstallmentOutlookTest(unittest.TestCase):
    def test_projects_only_the_charges_still_to_come(self):
        outlook = installment_outlook(
            statement(
                "2026-09",
                [txn("노트북", 50_000, total=300_000, payment_type="할부", seq=2, months=6)],
            )
        )
        self.assertEqual(outlook["active"][0]["remaining"], 4)
        self.assertEqual(outlook["futureTotal"], 200_000)
        self.assertEqual(outlook["byMonth"][0]["month"], "2026-10")
        self.assertEqual(len(outlook["byMonth"]), 4)

    def test_a_finished_installment_projects_nothing(self):
        outlook = installment_outlook(
            statement("2026-09", [txn("노트북", 50_000, payment_type="할부", seq=6, months=6)])
        )
        self.assertEqual(outlook["active"], [])
        self.assertEqual(outlook["futureTotal"], 0)

    def test_paid_in_full_purchases_are_not_installments(self):
        outlook = installment_outlook(statement("2026-09", [txn("커피", 5_000)]))
        self.assertEqual(outlook["futureTotal"], 0)


class TopMerchantsTest(unittest.TestCase):
    def test_branches_of_one_chain_count_as_one_merchant(self):
        rows = top_merchants(
            [txn("스타벅스 과천점", 6_000), txn("스타벅스 판교점", 4_000)], RULES, limit=5
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], 10_000)
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(rows[0]["average"], 5_000)

    def test_respects_the_limit(self):
        rows = top_merchants([txn(f"가게{i}", i * 1_000) for i in range(1, 21)], RULES, limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["total"], 20_000)


class FixedCostsTest(unittest.TestCase):
    def build(self, months: int):
        return [
            statement(
                f"2026-{m:02d}",
                [txn("넷플릭스", 17_000, month=f"2026-{m:02d}"), txn(f"일회성{m}", 50_000)],
            )
            for m in range(1, months + 1)
        ]

    def test_a_merchant_seen_every_month_is_fixed_cost(self):
        result = fixed_costs(self.build(4), RULES, window=4)
        self.assertTrue(result["available"])
        names = [row["merchant"] for row in result["merchants"]]
        self.assertIn("넷플릭스", names)
        self.assertEqual(result["fixedTotal"], 17_000 * 4)

    def test_one_off_merchants_stay_variable(self):
        result = fixed_costs(self.build(4), RULES, window=4)
        self.assertNotIn("일회성1", [row["merchant"] for row in result["merchants"]])
        self.assertEqual(result["variableTotal"], 50_000 * 4)

    def test_too_few_months_reports_unavailable_instead_of_guessing(self):
        result = fixed_costs(self.build(2), RULES, window=4)
        self.assertFalse(result["available"])
        self.assertEqual(result["months"], 2)
        self.assertEqual(result["merchants"], [])


class UncategorizedTest(unittest.TestCase):
    def test_lists_unknown_merchants_biggest_first(self):
        rows = uncategorized_merchants(
            [
                txn("동네분식", 8_000, category=UNCATEGORIZED),
                txn("낯선가게", 30_000, category=UNCATEGORIZED),
                txn("스타벅스", 5_000, category="카페·간식"),
            ]
        )
        self.assertEqual([row["merchant"] for row in rows], ["낯선가게", "동네분식"])

    def test_nothing_unknown_is_an_empty_list(self):
        self.assertEqual(uncategorized_merchants([txn("스타벅스", 5_000, category="카페·간식")]), [])


class AnalyzeTest(unittest.TestCase):
    def test_no_statements_reports_empty_rather_than_failing(self):
        result = analyze([], RULES, AnalysisConfig())
        self.assertTrue(result["empty"])
        self.assertIsNone(result["latest"])

    def test_builds_the_whole_payload_from_two_months(self):
        result = analyze(
            [
                statement("2026-08", [txn("스타벅스", 20_000, month="2026-08", category="카페·간식")]),
                statement("2026-09", [txn("스타벅스", 30_000, category="카페·간식")]),
            ],
            RULES,
            AnalysisConfig(budgets=(("카페·간식", 100_000),)),
        )
        self.assertEqual(result["latest"], "2026-09")
        self.assertEqual(result["latestTotal"], 30_000)
        self.assertEqual(result["months"][-1]["delta"], 10_000)
        self.assertEqual(result["categories"][0]["previous"], 20_000)
        self.assertEqual(result["budgets"][0]["ratio"], 0.3)
        self.assertEqual(len(result["transactions"]), 1)


if __name__ == "__main__":
    unittest.main()
