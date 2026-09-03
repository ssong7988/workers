from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from properties.models import Observation, Scan, SearchCondition
from properties.statistics import (
    build_chart,
    collect_series,
    eok_text,
    summarize_period,
)


KST = ZoneInfo("Asia/Seoul")


def kst(year, month, day, hour=9, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=KST)


class StatisticsTests(TestCase):
    def setUp(self) -> None:
        self.gwacheon = SearchCondition.objects.create(
            id="gwacheon-a", name="과천 A", complex_names=["과천A"], region="과천"
        )
        self.gwanggyo = SearchCondition.objects.create(
            id="gwanggyo-b", name="광교 B", complex_names=["광교B"], region="광교"
        )
        self._scans: dict[datetime, Scan] = {}

    def observe(
        self,
        moment: datetime,
        price_won: int,
        *,
        listing_id: str = "1",
        condition: SearchCondition | None = None,
        exclusion_code: str = "",
    ) -> Observation:
        scan = self._scans.get(moment)
        if scan is None:
            scan = self._scans[moment] = Scan.objects.create(
                started_at=moment, finished_at=moment, success=True
            )
        condition = condition or self.gwacheon
        return Observation.objects.create(
            scan=scan,
            condition=condition,
            listing_id=listing_id,
            complex_name=condition.name,
            exclusive_area_m2=Decimal("84.9"),
            price_won=price_won,
            observed_at=moment,
            exclusion_code=exclusion_code,
            exclusion_reason="제외 (테스트)" if exclusion_code else "",
        )

    def series(self, **overrides):
        options = {
            "start_day": date(2026, 9, 1),
            "end_day": date(2026, 9, 30),
            "region": "",
            "condition_id": "",
        }
        options.update(overrides)
        return collect_series(**options)

    def test_repeated_scans_of_one_listing_count_once_per_day(self) -> None:
        """The scanner runs many times a day. Without collapsing to the last
        observation, a listing scanned twenty times would drag the quartiles to
        its own price."""
        for hour, price in ((9, 2_400_000_000), (12, 2_400_000_000), (18, 2_350_000_000)):
            self.observe(kst(2026, 9, 2, hour), price, listing_id="1")
        self.observe(kst(2026, 9, 2, 18), 2_500_000_000, listing_id="2")

        (day,) = self.series()
        self.assertEqual(day.count, 2)
        # The 18:00 price wins for listing 1, not the 09:00 one.
        self.assertEqual(day.minimum, 2_350_000_000)
        self.assertEqual(day.maximum, 2_500_000_000)
        self.assertEqual(day.mean, 2_425_000_000)

    def test_quartiles_and_mean(self) -> None:
        # Eight listings: comfortably past the point where quartiles are real.
        for index, eok in enumerate([21, 22, 23, 24, 25, 26, 27, 28]):
            self.observe(kst(2026, 9, 2), eok * 100_000_000, listing_id=str(index))

        (day,) = self.series()
        self.assertEqual(day.count, 8)
        self.assertEqual(day.minimum, 2_100_000_000)
        self.assertEqual(day.q1, 2_275_000_000)
        self.assertEqual(day.mean, 2_450_000_000)
        self.assertEqual(day.q3, 2_625_000_000)
        self.assertEqual(day.maximum, 2_800_000_000)

    def test_too_few_listings_have_no_quartiles(self) -> None:
        """Two listings do not have a first quartile. Interpolating one puts a
        number a quarter of the way between the pair on screen as if it were
        observed, which is what the market data is supposed to be."""
        self.observe(kst(2026, 9, 2), 1_520_000_000, listing_id="a")
        self.observe(kst(2026, 9, 2), 1_600_000_000, listing_id="b")

        (day,) = self.series()
        self.assertIsNone(day.q1)
        self.assertIsNone(day.q3)
        self.assertTrue(day.thin)
        # The honest numbers survive.
        self.assertEqual(day.minimum, 1_520_000_000)
        self.assertEqual(day.maximum, 1_600_000_000)
        self.assertEqual(day.mean, 1_560_000_000)

    def test_quartiles_appear_once_they_land_on_real_prices(self) -> None:
        """With five listings the inclusive method puts Q1 and Q3 exactly on the
        second and fourth prices, so nothing is invented. Four is still
        interpolation, so four gets nothing."""
        prices = [21, 22, 23, 24, 25]
        for index, eok in enumerate(prices[:4]):
            self.observe(kst(2026, 9, 2), eok * 100_000_000, listing_id=str(index))
        self.assertIsNone(self.series()[0].q1)

        self.observe(kst(2026, 9, 3), prices[4] * 100_000_000, listing_id="4")
        for index, eok in enumerate(prices[:4]):
            self.observe(kst(2026, 9, 3), eok * 100_000_000, listing_id=str(index))
        day = self.series()[1]
        self.assertEqual(day.count, 5)
        self.assertEqual(day.q1, 2_200_000_000)
        self.assertEqual(day.q3, 2_400_000_000)
        self.assertFalse(day.thin)

    def test_single_listing_reports_only_its_own_price(self) -> None:
        self.observe(kst(2026, 9, 2), 2_400_000_000)
        (day,) = self.series()
        self.assertEqual(
            (day.minimum, day.mean, day.maximum), (2_400_000_000,) * 3
        )
        self.assertIsNone(day.q1)
        self.assertIsNone(day.q3)

    def test_days_without_observations_are_omitted(self) -> None:
        self.observe(kst(2026, 9, 2), 2_400_000_000)
        self.observe(kst(2026, 9, 5), 2_500_000_000)
        self.assertEqual(
            [day.day for day in self.series()], [date(2026, 9, 2), date(2026, 9, 5)]
        )

    def test_population_keeps_price_exclusions_and_drops_the_rest(self) -> None:
        """Listings over a price cap passed the area and type filters, so they
        belong in the distribution; a 59m2 unit does not."""
        self.observe(kst(2026, 9, 2), 2_400_000_000, listing_id="matched")
        self.observe(
            kst(2026, 9, 2), 2_900_000_000, listing_id="pricey", exclusion_code="price"
        )
        for code in ("area", "type", "complex", "floor"):
            self.observe(
                kst(2026, 9, 2), 1_000_000_000, listing_id=code, exclusion_code=code
            )

        (day,) = self.series()
        self.assertEqual(day.count, 2)
        self.assertEqual(day.maximum, 2_900_000_000)

    def test_region_and_condition_filters(self) -> None:
        self.observe(kst(2026, 9, 2), 2_400_000_000, listing_id="a")
        self.observe(
            kst(2026, 9, 2), 900_000_000, listing_id="b", condition=self.gwanggyo
        )

        self.assertEqual(self.series()[0].count, 2)
        self.assertEqual(self.series(region="과천")[0].count, 1)
        self.assertEqual(self.series(region="광교")[0].maximum, 900_000_000)
        # A chosen complex overrides the region rather than intersecting with it.
        self.assertEqual(
            self.series(region="과천", condition_id="gwanggyo-b")[0].maximum,
            900_000_000,
        )

    def test_days_follow_the_local_timezone_not_utc(self) -> None:
        """08:00 KST is the previous day in UTC. Grouping on the raw timestamp
        would file the morning scan under yesterday."""
        self.observe(kst(2026, 9, 3, 8), 2_400_000_000, listing_id="a")
        self.observe(kst(2026, 9, 2, 23, 30), 2_500_000_000, listing_id="b")
        self.assertEqual(
            [day.day for day in self.series()], [date(2026, 9, 2), date(2026, 9, 3)]
        )

    def test_disabled_conditions_are_excluded(self) -> None:
        self.observe(kst(2026, 9, 2), 2_400_000_000)
        SearchCondition.objects.filter(pk=self.gwacheon.pk).update(enabled=False)
        self.assertEqual(self.series(), [])

    def test_range_bounds_are_inclusive_on_both_ends(self) -> None:
        self.observe(kst(2026, 9, 1, 0, 1), 2_400_000_000, listing_id="a")
        self.observe(kst(2026, 9, 30, 23, 59), 2_500_000_000, listing_id="b")
        self.observe(kst(2026, 8, 31, 23, 59), 1_000_000_000, listing_id="c")
        self.observe(kst(2026, 10, 1, 0, 1), 9_000_000_000, listing_id="d")
        self.assertEqual(
            [day.day for day in self.series()], [date(2026, 9, 1), date(2026, 9, 30)]
        )


class PeriodSummaryTests(TestCase):
    def test_empty_series(self) -> None:
        summary = summarize_period([])
        self.assertEqual((summary.days, summary.samples), (0, 0))
        self.assertIsNone(summary.latest)
        self.assertIsNone(build_chart([]))


class ChartTests(TestCase):
    def setUp(self) -> None:
        self.condition = SearchCondition.objects.create(
            id="c", name="C", complex_names=["C"], region="과천"
        )

    def make(self, days: int) -> list:
        for index in range(days):
            scan = Scan.objects.create(started_at=kst(2026, 9, 1 + index), success=True)
            for offset in range(4):
                Observation.objects.create(
                    scan=scan,
                    condition=self.condition,
                    listing_id=str(offset),
                    complex_name="C",
                    exclusive_area_m2=Decimal("84.9"),
                    price_won=2_200_000_000 + offset * 100_000_000,
                    observed_at=kst(2026, 9, 1 + index),
                )
        return collect_series(start_day=date(2026, 9, 1), end_day=date(2026, 9, 30))

    def test_geometry_stays_inside_the_plot_and_higher_prices_sit_higher(self) -> None:
        chart = build_chart(self.make(3))
        self.assertEqual(len(chart.bars), 3)
        for bar in chart.bars:
            self.assertFalse(bar.has_box)  # four listings a day: no quartiles
            self.assertIsNone(bar.box_y)
            self.assertLess(bar.wick_top, bar.wick_bottom)
            self.assertGreaterEqual(bar.wick_top, chart.plot_top)
            self.assertLessEqual(bar.wick_bottom, chart.plot_bottom)
            self.assertGreaterEqual(bar.box_x, chart.plot_left)
            self.assertLessEqual(bar.box_x + bar.box_width, chart.plot_right)
        self.assertGreaterEqual(len(chart.ticks), 2)

    def test_x_labels_thin_out_on_long_ranges(self) -> None:
        chart = build_chart(self.make(30))
        shown = [bar for bar in chart.bars if bar.show_label]
        self.assertLessEqual(len(shown), 9)
        self.assertTrue(chart.bars[-1].show_label)

    def test_eok_text(self) -> None:
        self.assertEqual(eok_text(2_400_000_000), "24억")
        self.assertEqual(eok_text(2_350_000_000), "23.5억")
