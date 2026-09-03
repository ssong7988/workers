from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from properties.models import GlobalRule, Observation, Scan, SearchCondition
from report.stats_params import month_before, resolve_range, resolve_scope


KST = ZoneInfo("Asia/Seoul")


class RangeTests(SimpleTestCase):
    databases = set()
    today = date(2026, 9, 3)

    def resolve(self, **params):
        return resolve_range(params, self.today)

    def test_no_parameters_gives_the_last_month(self) -> None:
        resolved = self.resolve()
        self.assertEqual((resolved.start, resolved.end), (date(2026, 8, 3), self.today))
        self.assertEqual(resolved.notice, "")

    def test_month_covers_the_whole_month(self) -> None:
        resolved = self.resolve(month="2026-02")
        self.assertEqual(
            (resolved.start, resolved.end), (date(2026, 2, 1), date(2026, 2, 28))
        )
        self.assertEqual(resolved.month, "2026-02")

    def test_month_wins_over_an_explicit_range(self) -> None:
        resolved = self.resolve(month="2026-09", **{"from": "2026-01-01", "to": "2026-01-31"})
        self.assertEqual(resolved.start, date(2026, 9, 1))

    def test_explicit_range(self) -> None:
        resolved = self.resolve(**{"from": "2026-08-10", "to": "2026-08-20"})
        self.assertEqual(
            (resolved.start, resolved.end), (date(2026, 8, 10), date(2026, 8, 20))
        )

    def test_unreadable_values_fall_back_instead_of_raising(self) -> None:
        """These arrive from a URL a person can type or a stale bookmark, so a
        bad value has to render the page, not a 500."""
        for params in ({"from": "abc"}, {"to": "2026-13-40"}, {"month": "nope"}, {"month": "2026-99"}):
            with self.subTest(params=params):
                resolved = self.resolve(**params)
                self.assertEqual(
                    (resolved.start, resolved.end), (date(2026, 8, 3), self.today)
                )
                self.assertTrue(resolved.notice)

    def test_reversed_dates_are_swapped_and_reported(self) -> None:
        resolved = self.resolve(**{"from": "2026-09-03", "to": "2026-09-01"})
        self.assertEqual(
            (resolved.start, resolved.end), (date(2026, 9, 1), date(2026, 9, 3))
        )
        self.assertTrue(resolved.notice)

    def test_month_before_clamps_to_a_real_date(self) -> None:
        self.assertEqual(month_before(date(2026, 3, 31)), date(2026, 2, 28))
        self.assertEqual(month_before(date(2026, 1, 15)), date(2025, 12, 15))


class ScopeTests(TestCase):
    def setUp(self) -> None:
        self.gwacheon = SearchCondition.objects.create(
            id="a", name="과천 A", complex_names=["A"], region="과천"
        )
        self.gwanggyo = SearchCondition.objects.create(
            id="b", name="광교 B", complex_names=["B"], region="광교"
        )
        self.conditions = [self.gwacheon, self.gwanggyo]

    def test_default_is_gwacheon(self) -> None:
        scope = resolve_scope({}, self.conditions)
        self.assertEqual((scope.region, scope.condition_id), ("과천", ""))

    def test_all_regions(self) -> None:
        self.assertEqual(resolve_scope({"region": "all"}, self.conditions).region, "")

    def test_a_chosen_complex_sets_its_own_region(self) -> None:
        """Otherwise the two selects could show Gwacheon while charting Gwanggyo."""
        scope = resolve_scope(
            {"region": "과천", "condition": "b"}, self.conditions
        )
        self.assertEqual((scope.region, scope.condition_id), ("광교", "b"))

    def test_unknown_values_are_ignored(self) -> None:
        scope = resolve_scope({"region": "부산", "condition": "zzz"}, self.conditions)
        self.assertEqual((scope.region, scope.condition_id), ("", ""))

    def test_default_falls_back_when_gwacheon_is_absent(self) -> None:
        scope = resolve_scope({}, [self.gwanggyo])
        self.assertEqual(scope.region, "")


class StatsViewTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create(pk=1)
        self.condition = SearchCondition.objects.create(
            id="gwacheon-a", name="과천 A", complex_names=["과천A"], region="과천"
        )
        self.other = SearchCondition.objects.create(
            id="gwanggyo-b", name="광교 B", complex_names=["광교B"], region="광교"
        )
        self.url = reverse("report-stats")

    def observe(self, day: date, price_won: int, *, condition=None, listing_id="1"):
        moment = datetime.combine(day, time(9, 0), tzinfo=KST)
        scan, _ = Scan.objects.get_or_create(
            started_at=moment, defaults={"finished_at": moment, "success": True}
        )
        Observation.objects.create(
            scan=scan,
            condition=condition or self.condition,
            listing_id=listing_id,
            complex_name="A",
            exclusive_area_m2=Decimal("84.9"),
            price_won=price_won,
            observed_at=moment,
        )

    def get(self, query=""):
        return self.client.get(f"{self.url}{query}", HTTP_HOST="127.0.0.1")

    def test_default_shows_gwacheon_and_only_the_last_month(self) -> None:
        today = datetime.now(KST).date()
        self.observe(today, 2_400_000_000)
        self.observe(today - timedelta(days=40), 9_900_000_000, listing_id="old")

        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response.context["scope"].region, "과천")
        self.assertEqual(response.context["period"].days, 1)
        self.assertEqual(response.context["period_max"], "24억")

    def test_region_filter(self) -> None:
        today = datetime.now(KST).date()
        self.observe(today, 2_400_000_000)
        self.observe(today, 1_600_000_000, condition=self.other, listing_id="2")

        self.assertEqual(self.get().context["period"].samples, 1)
        self.assertEqual(self.get("?region=all").context["period"].samples, 2)
        self.assertEqual(
            self.get("?region=광교").context["period_max"], "16억"
        )

    def test_condition_overrides_the_region(self) -> None:
        today = datetime.now(KST).date()
        self.observe(today, 1_600_000_000, condition=self.other, listing_id="2")
        response = self.get("?region=과천&condition=gwanggyo-b")
        self.assertEqual(response.context["scope"].condition_id, "gwanggyo-b")
        self.assertEqual(response.context["period"].samples, 1)

    def test_month_parameter_selects_that_month(self) -> None:
        self.observe(date(2026, 2, 10), 2_400_000_000)
        response = self.get("?month=2026-02")
        self.assertEqual(response.context["range"].start, date(2026, 2, 1))
        self.assertEqual(response.context["period"].days, 1)

    def test_broken_parameters_render_with_a_notice(self) -> None:
        response = self.get("?from=abc")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["range"].notice)
        self.assertContains(response, "되돌렸습니다")

    def test_empty_range_says_so_and_draws_no_chart(self) -> None:
        response = self.get("?month=2020-01")
        self.assertIsNone(response.context["chart"])
        self.assertContains(response, "관측된 매물이 없습니다")

    def test_chart_and_table_agree(self) -> None:
        today = datetime.now(KST).date()
        for index, eok in enumerate([21, 22, 23, 24]):
            self.observe(today, eok * 100_000_000, listing_id=str(index))
        response = self.get()
        (row,) = response.context["rows"]
        self.assertEqual(row["count"], 4)
        self.assertEqual(row["minimum"], "21억")
        self.assertEqual(row["maximum"], "24억")
        self.assertEqual(len(response.context["chart"].bars), 1)
        self.assertContains(response, "1분위")

    def test_report_links_to_the_statistics_screen(self) -> None:
        response = self.client.get(reverse("report-index"), HTTP_HOST="127.0.0.1")
        self.assertContains(response, self.url)
