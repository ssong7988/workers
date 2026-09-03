from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone

from properties.models import GlobalRule, Listing, SearchCondition


class GlobalRuleTests(SimpleTestCase):
    databases = set()

    def test_schedule_validators_reject_invalid_values(self) -> None:
        rule = GlobalRule(
            low_floor_numeric_floors=[1, 2, 3],
            low_floor_labels=["저", "저층"],
            digest_weekdays=[0, 6],
            digest_hour=8,
        )
        rule.full_clean(validate_unique=False, validate_constraints=False)

        rule.digest_weekdays = [7]
        with self.assertRaises(ValidationError):
            rule.full_clean(validate_unique=False, validate_constraints=False)

    def test_defaults_preserve_existing_yaml_behavior(self) -> None:
        rule = GlobalRule()
        self.assertEqual(rule.low_floor_numeric_floors, [1, 2, 3])
        self.assertEqual(rule.low_floor_labels, ["저", "저층"])
        self.assertEqual(rule.digest_weekdays, [0, 1, 2, 3, 4])

    def test_singleton_always_uses_primary_key_one(self) -> None:
        rule = GlobalRule(id=99)
        # Exercise the singleton behavior without touching the database.
        with self.assertRaises(RuntimeError):
            rule.save_base = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError())
            rule.save()
        self.assertEqual(rule.pk, 1)


class SearchConditionTests(SimpleTestCase):
    databases = set()

    def test_allowed_types_null_means_all(self) -> None:
        condition = SearchCondition(
            id="sample-84",
            name="샘플 84",
            complex_names=["샘플아파트"],
            allowed_types=None,
            exclusive_area_m2=Decimal("84"),
        )
        condition.full_clean(validate_unique=False, validate_constraints=False)
        self.assertIsNone(condition.allowed_types)

    def test_urgent_price_cannot_exceed_max_price(self) -> None:
        condition = SearchCondition(
            id="sample-84",
            name="샘플 84",
            complex_names=["샘플아파트"],
            max_price_won=2_000_000_000,
            urgent_price_won=2_100_000_000,
        )
        with self.assertRaisesMessage(ValidationError, "급매 기준가"):
            condition.full_clean(validate_unique=False, validate_constraints=False)

    def test_search_url_must_be_naver_https(self) -> None:
        condition = SearchCondition(
            id="sample-84",
            name="샘플 84",
            complex_names=["샘플아파트"],
            search_url="https://example.com/listings",
        )
        with self.assertRaisesMessage(ValidationError, "네이버 HTTPS"):
            condition.full_clean(validate_unique=False, validate_constraints=False)


class ListingTests(SimpleTestCase):
    databases = set()

    def make_listing(self, **overrides) -> Listing:
        observed_at = timezone.make_aware(datetime(2026, 9, 3, 8, 0))
        values = {
            "condition": SearchCondition(id="sample-84", name="샘플 84"),
            "listing_id": "1234567890",
            "complex_name": "샘플아파트",
            "exclusive_area_m2": Decimal("84.990"),
            "price_won": 2_000_000_000,
            "observed_at": observed_at,
            "first_seen_at": observed_at,
            "last_seen_at": observed_at,
            "effective_urgent_price_won": 2_100_000_000,
        }
        values.update(overrides)
        return Listing(**values)

    def test_key_preserves_condition_and_listing_identity(self) -> None:
        listing = self.make_listing()
        self.assertEqual(listing.key, "sample-84:1234567890")

    def test_urgent_uses_effective_threshold(self) -> None:
        self.assertTrue(self.make_listing().is_urgent)
        self.assertFalse(
            self.make_listing(effective_urgent_price_won=1_900_000_000).is_urgent
        )
        self.assertFalse(self.make_listing(effective_urgent_price_won=None).is_urgent)
