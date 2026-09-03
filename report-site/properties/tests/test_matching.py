from datetime import datetime
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone

from properties.matching import (
    classify_exclusion,
    explain_condition,
    matches_condition,
    normalize_type_name,
    parse_floor,
    parse_price_won,
)
from properties.models import GlobalRule, Observation, SearchCondition


class MatchingTests(SimpleTestCase):
    databases = set()

    def setUp(self) -> None:
        self.rule = GlobalRule()
        self.condition = SearchCondition(
            id="sample-84",
            name="샘플 84",
            complex_names=["샘플아파트"],
            exclusive_area_m2=Decimal("84"),
            allowed_types=["84A"],
            max_price_won=2_600_000_000,
            urgent_price_won=2_500_000_000,
        )

    def listing(self, **overrides) -> Observation:
        values = {
            "listing_id": "123",
            "complex_name": "과천 샘플아파트",
            "type_name": "84.9A",
            "exclusive_area_m2": Decimal("84.900"),
            "price_won": 2_500_000_000,
            "floor_text": "10/30층",
            "observed_at": timezone.make_aware(datetime(2026, 9, 3, 9, 0)),
        }
        values.update(overrides)
        return Observation(**values)

    def test_match_fills_floor_and_effective_thresholds(self) -> None:
        item = self.listing()
        self.assertTrue(matches_condition(item, self.condition, self.rule))
        self.assertEqual(item.floor, 10)
        self.assertFalse(item.is_low_floor)
        self.assertEqual(item.effective_max_price_won, 2_600_000_000)
        self.assertEqual(item.effective_urgent_price_won, 2_500_000_000)

    def test_low_floor_uses_discounted_cap(self) -> None:
        item = self.listing(price_won=2_550_000_000, floor_text="2/25층")
        reason = explain_condition(item, self.condition, self.rule)
        self.assertIn("가격 초과", reason)
        self.assertIn("저층기준", reason)
        self.assertEqual(item.effective_urgent_price_won, 2_400_000_000)

    def test_area_type_alias_and_unknown_floor_reasons(self) -> None:
        cases = (
            (self.listing(complex_name="다른 단지"), "단지명 불일치"),
            (self.listing(exclusive_area_m2=Decimal("82.999")), "면적 미달"),
            (self.listing(type_name="106A"), "타입 제외"),
            (self.listing(floor_text="미상"), "층 해석 실패"),
        )
        for item, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, explain_condition(item, self.condition, self.rule))

    def test_middle_floor_does_not_read_building_height(self) -> None:
        self.assertEqual(parse_floor("중/23층", self.rule), (None, False, True))

    def test_floor_variants_preserve_existing_behavior(self) -> None:
        for text in ("1층", "2/30층", "3층", "저/25층", "저층"):
            with self.subTest(text=text):
                self.assertTrue(parse_floor(text, self.rule)[1])
        self.assertEqual(parse_floor("21/25층", self.rule), (21, False, True))
        self.assertEqual(parse_floor("정보없음", self.rule), (None, False, False))

    def test_price_and_type_normalization_preserve_existing_behavior(self) -> None:
        self.assertEqual(parse_price_won("25억"), 2_500_000_000)
        self.assertEqual(parse_price_won("24억 5,000"), 2_450_000_000)
        self.assertEqual(parse_price_won("255,000만원"), 2_550_000_000)
        self.assertEqual(normalize_type_name("84.94 a"), "84A")

    def test_every_exclusion_branch_maps_to_a_code(self) -> None:
        """The reasons are Korean display strings; the codes are what the
        statistics query filters on. If a reason is reworded without updating
        `EXCLUSION_CODES`, this fails instead of silently returning "other"."""
        cases = (
            (self.listing(complex_name="다른 단지"), "complex"),
            (self.listing(exclusive_area_m2=Decimal("82.999")), "area"),
            (self.listing(exclusive_area_m2=Decimal("86.001")), "area"),
            (self.listing(type_name="106A"), "type"),
            (self.listing(floor_text="미상"), "floor"),
            (self.listing(price_won=2_700_000_000), "price"),
        )
        for item, expected in cases:
            with self.subTest(expected=expected):
                reason = explain_condition(item, self.condition, self.rule)
                self.assertIsNotNone(reason)
                self.assertEqual(classify_exclusion(reason), expected)

    def test_matching_listing_has_no_exclusion_code(self) -> None:
        self.assertEqual(classify_exclusion(None), "")
        self.assertEqual(classify_exclusion(""), "")
