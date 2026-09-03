import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from properties.models import GlobalRule, Listing, Observation, Scan, SearchCondition


class ImportSearchesTests(TestCase):
    def test_import_is_idempotent_and_updates_existing_condition(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "searches.yaml"
            path.write_text(
                """
global_rules:
  trade_type: sale
  low_floor:
    numeric_floors: [1, 2, 3]
    labels: [저, 저층]
    price_discount_won: 100000000
schedule:
  timezone: Asia/Seoul
  digest_weekdays: [0, 1, 2, 3, 4]
  digest_hour: 8
searches:
  - id: sample-84
    name: 샘플 84
    complex_names: [샘플아파트]
    exclusive_area_m2: 84
    allowed_types: all
    max_price_won: 2000000000
    urgent_price_won: 1900000000
    enabled: true
""".strip(),
                encoding="utf-8",
            )
            call_command("import_searches", path=path, verbosity=0)
            path.write_text(
                path.read_text(encoding="utf-8").replace("샘플 84", "샘플 84 변경", 1),
                encoding="utf-8",
            )
            call_command("import_searches", path=path, verbosity=0)

        self.assertEqual(GlobalRule.objects.count(), 1)
        self.assertEqual(SearchCondition.objects.count(), 1)
        self.assertEqual(SearchCondition.objects.get().name, "샘플 84 변경")


class ImportStateTests(TestCase):
    def test_import_is_idempotent_and_preserves_alert_history(self) -> None:
        SearchCondition.objects.create(
            id="sample-84", name="샘플 84", complex_names=["샘플아파트"]
        )
        started_at = "2026-09-03T08:00:00+09:00"
        observed_at = "2026-09-03T08:01:00+09:00"
        finished_at = "2026-09-03T08:02:00+09:00"
        listing = {
            "condition_id": "sample-84",
            "listing_id": "1234567890",
            "complex_name": "샘플아파트",
            "type_name": "84A",
            "exclusive_area_m2": 84.999,
            "price_won": 1900000000,
            "floor_text": "7/20층",
            "floor": 7,
            "direction": "남향",
            "description": "샘플 매물",
            "url": "https://fin.land.naver.com/articles/1234567890",
            "observed_at": observed_at,
            "is_low_floor": False,
            "effective_max_price_won": 2000000000,
            "effective_urgent_price_won": 1900000000,
        }
        with TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "scan-runs.jsonl").write_text(
                json.dumps(
                    {
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "success": True,
                        "successful_conditions": ["sample-84"],
                        "failed_conditions": {},
                        "collected_count": 1,
                        "matched_count": 1,
                        "urgent_count": 1,
                        "excluded_count": 0,
                        "notification": "카카오 전송 완료",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (data_dir / "observations.jsonl").write_text(
                json.dumps(listing, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            state_listing = {
                **listing,
                "first_seen_at": observed_at,
                "last_seen_at": observed_at,
                "active": True,
                "last_urgent_alert_price_won": 1900000000,
            }
            (data_dir / "state.json").write_text(
                json.dumps(
                    {
                        "listings": {"sample-84:1234567890": state_listing},
                        "last_successful_scan": finished_at,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            call_command("import_state", data_dir=data_dir, verbosity=0)
            call_command("import_state", data_dir=data_dir, verbosity=0)

        self.assertEqual(Scan.objects.count(), 1)
        self.assertEqual(Observation.objects.count(), 1)
        self.assertEqual(Listing.objects.count(), 1)
        imported = Listing.objects.get()
        self.assertEqual(imported.last_urgent_alert_price_won, 1900000000)
        self.assertEqual(str(imported.exclusive_area_m2), "84.999")
