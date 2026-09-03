from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import Client, SimpleTestCase

from real_estate_finder.models import AppConfig, LowFloorRule, SearchCondition
from real_estate_finder.storage import FileStore

from report import views


CONFIG = AppConfig(
    trade_type="sale",
    low_floor=LowFloorRule(),
    searches=(
        SearchCondition(
            id="cond-a",
            name="테스트단지",
            complex_names=("테스트단지",),
            search_url="",
            exclusive_area_m2=84,
            allowed_types=None,
            max_price_won=2_600_000_000,
            urgent_price_won=2_500_000_000,
        ),
    ),
)


def _listing_payload(
    listing_id: str,
    price_won: int,
    *,
    urgent_price_won: int | None = 2_500_000_000,
    active: bool = True,
    observed_at: str = "2026-09-03T08:00:00+09:00",
) -> dict:
    return {
        "condition_id": "cond-a",
        "listing_id": listing_id,
        "complex_name": "과천 테스트단지",
        "type_name": "84A",
        "exclusive_area_m2": 84.9,
        "price_won": price_won,
        "floor_text": "10/30층",
        "floor": 10,
        "direction": "남향",
        "description": "",
        "url": f"https://fin.land.naver.com/articles/{listing_id}",
        "observed_at": observed_at,
        "is_low_floor": False,
        "effective_max_price_won": 2_600_000_000,
        "effective_urgent_price_won": urgent_price_won,
        "first_seen_at": observed_at,
        "last_seen_at": observed_at,
        "active": active,
        "last_urgent_alert_price_won": None,
    }


class ReportViewTests(SimpleTestCase):
    databases: set[str] = set()

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.store = FileStore(Path(self.tmp_dir.name))

        for patcher in (
            mock.patch.object(views, "_store", self.store),
            mock.patch.object(views, "_config", CONFIG),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        self.client = Client()
        self.url = f"/r/{settings.REPORT_PATH_TOKEN}/"

    def _save(self, listings: list[dict], last_successful_scan: str | None = None) -> None:
        self.store.save_state(
            {
                "listings": {f"cond-a:{p['listing_id']}": p for p in listings},
                "last_successful_scan": last_successful_scan,
            }
        )

    def test_valid_token_renders_active_listings_only(self) -> None:
        self._save(
            [
                _listing_payload("1", 2_400_000_000),  # urgent
                _listing_payload("2", 2_550_000_000),  # matched, not urgent
                _listing_payload("3", 2_400_000_000, active=False),  # inactive, excluded
            ]
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('data-observed-at="2026-09-03T08:00:00+09:00"', html)
        self.assertIn(">2</div>", html)  # 확인 매물 tile: 2 active, non-urgent one excluded from count? see below
        self.assertIn("급매", html)
        self.assertNotIn("fin.land.naver.com/articles/3", html)

    def test_cache_control_is_no_store(self) -> None:
        self._save([_listing_payload("1", 2_550_000_000)])
        response = self.client.get(self.url)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_wrong_token_is_404(self) -> None:
        response = self.client.get("/r/not-the-real-token/")
        self.assertEqual(response.status_code, 404)

    def test_root_path_is_404(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 404)

    def test_missing_state_file_renders_empty_state_not_500(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("활성 매물이 없습니다", response.content.decode("utf-8"))

    def test_observed_at_falls_back_to_last_successful_scan_when_no_active_listings(self) -> None:
        self._save([], last_successful_scan="2026-09-01T00:00:00+09:00")
        response = self.client.get(self.url)
        html = response.content.decode("utf-8")
        self.assertIn('data-observed-at="2026-09-01T00:00:00+09:00"', html)
