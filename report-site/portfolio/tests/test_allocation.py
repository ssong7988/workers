from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from portfolio.allocation import build_allocation
from portfolio.display import man_won_text, round_to_man
from portfolio.models import (
    UNCLASSIFIED_ASSET_CLASS_ID,
    AssetClass,
    BenchmarkAllocation,
    PortfolioTarget,
)

from .factories import make_account, make_asset_class, make_instrument, record_balance


AS_OF = date(2026, 9, 1)


class AllocationTests(TestCase):
    def setUp(self) -> None:
        self.account = make_account()
        self.stocks = make_asset_class("korea-stock", "한국 주식", "domestic_stock", 10)
        self.bonds = make_asset_class("bond", "채권", "bond", 20)
        self.unknown = AssetClass.objects.create(
            id=UNCLASSIFIED_ASSET_CLASS_ID, name="미분류", display_order=999
        )
        record_balance(
            self.account, make_instrument("005930", self.stocks), AS_OF, "600000"
        )
        record_balance(
            self.account, make_instrument("KODEX", self.bonds), AS_OF, "200000"
        )
        record_balance(
            self.account, make_instrument("NEW", self.unknown), AS_OF, "100000"
        )

    def _targets(self, stocks: str, bonds: str) -> None:
        for asset_class, percent in ((self.stocks, stocks), (self.bonds, bonds)):
            PortfolioTarget.objects.create(
                effective_from=date(2026, 1, 1),
                asset_class=asset_class,
                target_percent=Decimal(percent),
            )

    def test_unclassified_is_excluded_from_the_denominator(self) -> None:
        view = build_allocation()
        self.assertEqual(view.as_of, AS_OF)
        self.assertEqual(view.total_value, Decimal("800000.00"))
        self.assertEqual(view.unclassified_value, Decimal("100000.00"))
        self.assertEqual(view.gross_value, Decimal("900000.00"))
        ratios = {row.asset_class_id: row.ratio for row in view.rows}
        self.assertEqual(ratios["korea-stock"], Decimal("0.75"))
        self.assertEqual(ratios["bond"], Decimal("0.25"))

    def test_rebalancing_signs_and_sum(self) -> None:
        self._targets("60", "40")
        view = build_allocation()
        moves = {row.asset_class_id: row.rebalance_value for row in view.rows}
        self.assertEqual(moves["korea-stock"], Decimal("-120000.00"))
        self.assertEqual(moves["bond"], Decimal("120000.00"))
        # 총액을 유지하는 제안이므로 합계는 0이다.
        self.assertEqual(sum(moves.values()), Decimal("0"))
        self.assertEqual(view.rounding_remainder, Decimal("0"))
        self.assertEqual(view.target_note, "")

    def test_targets_that_do_not_sum_to_100_are_refused(self) -> None:
        self._targets("60", "50")
        view = build_allocation()
        self.assertIn("110", view.target_note)
        self.assertTrue(all(row.rebalance_value is None for row in view.rows))

    def test_a_target_only_class_still_gets_a_row(self) -> None:
        gold = make_asset_class("gold", "금", "alternative", 30)
        PortfolioTarget.objects.create(
            effective_from=date(2026, 1, 1), asset_class=gold, target_percent=Decimal("10")
        )
        self._targets("60", "30")
        view = build_allocation()
        gold_row = next(row for row in view.rows if row.asset_class_id == "gold")
        self.assertEqual(gold_row.market_value, Decimal("0"))
        self.assertEqual(gold_row.rebalance_value, Decimal("80000.00"))

    def test_benchmark_is_normalised_only_for_the_comparison(self) -> None:
        for category, common, percent in (
            ("국내주식", "domestic_stock", "12.7"),
            ("국내채권", "bond", "27.7"),
            ("해외주식", "foreign_stock", "35.0"),
            ("해외채권", "bond", "7.4"),
            ("대체투자", "alternative", "17.0"),
        ):
            BenchmarkAllocation.objects.create(
                as_of=date(2026, 9, 5),
                source_category=category,
                benchmark_category=common,
                source_percent=Decimal(percent),
            )
        view = build_allocation()
        rows = {row.category: row for row in view.benchmark_rows}
        # 원본 합계 99.8%는 DB에 남아 있고, 비교용으로만 100%로 맞춘다.
        self.assertEqual(
            BenchmarkAllocation.objects.get(source_category="국내채권").source_percent,
            Decimal("27.700"),
        )
        self.assertAlmostEqual(float(rows["bond"].benchmark_percent), 35.170, places=2)
        self.assertAlmostEqual(float(rows["domestic_stock"].mine_percent), 75.0, places=3)
        self.assertAlmostEqual(float(rows["bond"].mine_percent), 25.0, places=3)

    def test_empty_database_renders_as_no_data(self) -> None:
        from portfolio.models import PositionSnapshot

        PositionSnapshot.objects.all().delete()
        view = build_allocation()
        self.assertFalse(view.has_data)
        self.assertEqual(view.rows, [])


class DisplayTests(TestCase):
    def test_man_won_rounding(self) -> None:
        self.assertEqual(man_won_text(Decimal("12345678")), "1,235만원")
        self.assertEqual(man_won_text(Decimal("139924641")), "1억 3,992만원")
        self.assertEqual(man_won_text(Decimal("100000000")), "1억원")
        self.assertEqual(man_won_text(Decimal("-25000")), "-3만원")

    def test_round_to_man_keeps_won_units(self) -> None:
        self.assertEqual(round_to_man(Decimal("12345678")), Decimal("12350000"))
