from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from real_estate_finder import service as service_module
from real_estate_finder.models import AppConfig, Listing, LowFloorRule, SearchCondition
from real_estate_finder.notifier import KakaoNotifier
from real_estate_finder.service import FinderService
from real_estate_finder.storage import FileStore


CONDITION = SearchCondition(
    id="weverfield",
    name="위버필드",
    complex_names=("위버필드",),
    search_url="https://new.land.naver.com/complexes/1",
    exclusive_area_m2=84,
    allowed_types=None,
    max_price_won=2_600_000_000,
    urgent_price_won=2_500_000_000,
)
CONFIG = AppConfig("sale", LowFloorRule(), (CONDITION,))


def make_listing(price: int) -> Listing:
    return Listing(
        condition_id="weverfield",
        listing_id="123",
        complex_name="과천 위버필드",
        type_name="84A",
        exclusive_area_m2=84.9,
        price_won=price,
        floor_text="10/30층",
        floor=10,
        direction="남향",
        description="",
        url="https://fin.land.naver.com/articles/123",
        observed_at="2026-09-02T09:00:00+09:00",
    )


class FakeCollector:
    def __init__(self, item: Listing) -> None:
        self.item = item

    def collect_all(self, _conditions):
        return {"weverfield": [self.item]}


class MappingCollector:
    def __init__(self, mapping):
        self.mapping = mapping

    def collect_all(self, _conditions):
        return self.mapping


def text_service(config, collector, store, notifier) -> FinderService:
    """Service on the text path, so these tests never launch a browser."""
    return FinderService(config, collector, store, notifier, use_cards=False)


class RecordingImageSender:
    """Stands in for the Kakao image send, capturing what it was handed."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple] = []

    def __call__(self, image_path, title, description, link_url) -> None:
        self.calls.append((image_path, title, description, link_url))
        if self.error:
            raise self.error


class ServiceTests(unittest.TestCase):
    def test_first_urgent_and_further_drop_only(self) -> None:
        sent: list[str] = []
        notifier = KakaoNotifier(Path("."), sender=lambda message, _url: sent.append(message))
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            first = text_service(CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier)
            result = first.scan()
            self.assertEqual(len(result.urgent), 1)
            self.assertEqual(len(sent), 1)

            same = text_service(CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier)
            self.assertEqual(len(same.scan().urgent), 0)
            self.assertEqual(len(sent), 1)

            lower = text_service(CONFIG, FakeCollector(make_listing(2_490_000_000)), store, notifier)
            self.assertEqual(len(lower.scan().urgent), 1)
            self.assertEqual(len(sent), 2)

    def test_smoke_does_not_consume_alert_history(self) -> None:
        sent: list[str] = []
        notifier = KakaoNotifier(Path("."), sender=lambda message, _url: sent.append(message))
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = text_service(CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier)
            service.smoke_test()
            state = store.load_state()
            self.assertIsNone(state["listings"]["weverfield:123"]["last_urgent_alert_price_won"])
            # One message, whichever path it takes. This once sent a summary
            # plus one text per listing, which reached 42 messages on a real run.
            self.assertEqual(len(sent), 1)

    def test_smoke_sends_one_card_with_the_report_link(self) -> None:
        """The card is one Kakao message, and REPORT_URL is what adds its
        second button beside the full-resolution image."""
        sent: list[str] = []
        image_sender = RecordingImageSender()
        notifier = KakaoNotifier(
            Path("."),
            sender=lambda message, _url: sent.append(message),
            image_sender=image_sender,
        )
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(
                CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier
            )
            with mock.patch.object(service_module, "write_report_data"), mock.patch.object(
                service_module, "is_live", return_value=True
            ), mock.patch.object(service_module, "build_site"):
                service.smoke_test()
            self.assertEqual(len(image_sender.calls), 1)
            self.assertEqual(len(sent), 0)
            self.assertEqual(image_sender.calls[0][3], service_module.REPORT_URL)

    def test_smoke_failure_sends_one_text_and_no_card(self) -> None:
        sent: list[str] = []
        image_sender = RecordingImageSender()
        notifier = KakaoNotifier(
            Path("."),
            sender=lambda message, _url: sent.append(message),
            image_sender=image_sender,
        )

        class BrokenCollector:
            def collect_all(self, _conditions):
                raise RuntimeError("수집 실패")

        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(CONFIG, BrokenCollector(), store, notifier)
            result = service.smoke_test()
            self.assertFalse(result.success)
            self.assertEqual(len(image_sender.calls), 0)
            self.assertEqual(len(sent), 1)
            self.assertIn("실패", sent[0])

    def test_notify_new_without_urgent_threshold(self) -> None:
        condition = SearchCondition(
            id="worldmark",
            name="광교푸르지오월드마크 전체",
            complex_names=("광교푸르지오월드마크",),
            search_url="",
            exclusive_area_m2=None,
            allowed_types=None,
            max_price_won=None,
            urgent_price_won=None,
            notify_new=True,
            apply_low_floor_discount=False,
        )
        config = AppConfig("sale", LowFloorRule(), (condition,))
        item = make_listing(1_800_000_000)
        item.condition_id = "worldmark"
        item.complex_name = "광교푸르지오월드마크(주상복합)"
        sent: list[str] = []
        notifier = KakaoNotifier(Path("."), sender=lambda message, _url: sent.append(message))
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = text_service(
                config, MappingCollector({"worldmark": [item]}), store, notifier
            )
            first = service.scan()
            self.assertEqual(len(first.urgent), 0)
            self.assertEqual(len(sent), 1)
            self.assertIn("신규", sent[0])
            service.scan()
            self.assertEqual(len(sent), 1)


class CardPathTests(unittest.TestCase):
    """The card exists to carry more than Kakao's 200-character text limit."""

    def setUp(self) -> None:
        self.built: list[list] = []

        def fake_build(items, out_path, **_kwargs):
            self.built.append(list(items))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"png")
            return out_path, 1080, 4992

        for patcher in (
            mock.patch.object(service_module, "build_card_image", fake_build),
            # Never touch the real site checkout or run a deploy from a test.
            mock.patch.object(service_module, "write_report_data"),
            mock.patch.object(service_module, "is_live", return_value=True),
            mock.patch.object(service_module, "build_site"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _digest_listings(self, count: int) -> list[Listing]:
        listings = []
        for index in range(count):
            listing = make_listing(2_400_000_000 + index * 1_000_000)
            listing.listing_id = str(index)
            listings.append(listing)
        return listings

    def test_digest_sends_one_card_with_every_listing(self) -> None:
        image_sender = RecordingImageSender()
        notifier = KakaoNotifier(Path("."), sender=lambda *_: None, image_sender=image_sender)
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(CONFIG, FakeCollector(make_listing(1)), store, notifier)
            service.send_digest(self._digest_listings(30))

        self.assertEqual(len(image_sender.calls), 1, "digest must be one message, not one per listing")
        self.assertEqual(len(self.built[0]), 30, "no listing may be dropped")

    def _card_service(self, store, notifier):
        return FinderService(
            CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier
        )

    def test_scan_does_not_build_the_ui(self) -> None:
        """The UI has its own deployment lifecycle; a scan only refreshes its data."""
        image_sender = RecordingImageSender()
        notifier = KakaoNotifier(Path("."), sender=lambda *_: None, image_sender=image_sender)
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            with mock.patch.object(service_module, "build_site") as build:
                self._card_service(store, notifier).scan()

        self.assertEqual(build.call_count, 0, "스캔이 UI 빌드를 실행하면 안 된다")

    def test_build_failure_never_holds_up_the_alert(self) -> None:
        image_sender = RecordingImageSender()
        sent: list[str] = []
        notifier = KakaoNotifier(
            Path("."), sender=lambda message, _url: sent.append(message), image_sender=image_sender
        )
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            with mock.patch.object(
                service_module, "build_site", side_effect=RuntimeError("타입 오류")
            ):
                self._card_service(store, notifier).scan()

        self.assertEqual(len(image_sender.calls), 1, "빌드가 깨져도 카드는 나가야 한다")
        self.assertEqual(sent, [], "텍스트 경로로 떨어지면 안 된다")

    def test_build_can_be_turned_off_for_frequent_scans(self) -> None:
        """Hourly scans will run with the build on its own schedule instead."""
        image_sender = RecordingImageSender()
        notifier = KakaoNotifier(Path("."), sender=lambda *_: None, image_sender=image_sender)
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(
                CONFIG,
                FakeCollector(make_listing(2_500_000_000)),
                store,
                notifier,
                build_report=False,
            )
            with mock.patch.object(service_module, "build_site") as build:
                service.scan()

        self.assertEqual(build.call_count, 0)
        self.assertEqual(len(image_sender.calls), 1, "빌드를 껐어도 카드는 나가야 한다")

    def test_unpublished_report_drops_the_button(self) -> None:
        """A button onto the previously deployed report is worse than no button."""
        image_sender = RecordingImageSender()
        notifier = KakaoNotifier(Path("."), sender=lambda *_: None, image_sender=image_sender)
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            with mock.patch.object(service_module, "is_live", return_value=False):
                self._card_service(store, notifier).scan()

        self.assertEqual(len(image_sender.calls), 1, "카드는 그대로 나가야 한다")
        self.assertIsNone(image_sender.calls[0][3], "라이브 반영 전이면 리포트 링크를 빼야 한다")

    def test_live_check_failure_never_holds_up_the_alert(self) -> None:
        image_sender = RecordingImageSender()
        sent: list[str] = []
        notifier = KakaoNotifier(
            Path("."), sender=lambda message, _url: sent.append(message), image_sender=image_sender
        )
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            with mock.patch.object(
                service_module, "is_live", side_effect=OSError("사이트 접속 실패")
            ):
                self._card_service(store, notifier).scan()

        self.assertEqual(len(image_sender.calls), 1, "확인이 실패해도 급매 알림은 나가야 한다")
        self.assertIsNone(image_sender.calls[0][3])
        self.assertEqual(sent, [], "텍스트 경로로 떨어지면 안 된다")

    def test_published_report_keeps_the_button(self) -> None:
        image_sender = RecordingImageSender()
        notifier = KakaoNotifier(Path("."), sender=lambda *_: None, image_sender=image_sender)
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            self._card_service(store, notifier).scan()

        self.assertEqual(image_sender.calls[0][3], service_module.REPORT_URL)

    def _matched_set(self):
        """One urgent listing plus two that merely match the condition."""
        urgent = make_listing(2_500_000_000)
        urgent.listing_id = "urgent"
        first = make_listing(2_550_000_000)
        first.listing_id = "plain1"
        second = make_listing(2_580_000_000)
        second.listing_id = "plain2"
        return [urgent, first, second]

    def test_card_carries_every_matched_listing(self) -> None:
        image_sender = RecordingImageSender()
        notifier = KakaoNotifier(Path("."), sender=lambda *_: None, image_sender=image_sender)
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(
                CONFIG,
                MappingCollector({"weverfield": self._matched_set()}),
                store,
                notifier,
            )
            service.scan()

        self.assertEqual(len(image_sender.calls), 1, "알림은 한 통이어야 한다")
        flags = {listing.listing_id: (urgent, new) for listing, urgent, new in self.built[0]}
        self.assertEqual(len(flags), 3, "카드에는 조건충족 전체가 담겨야 한다")
        self.assertEqual(flags["urgent"], (True, False))
        self.assertEqual(flags["plain1"], (False, False))
        self.assertEqual(flags["plain2"], (False, False))

    def test_no_alert_sends_nothing(self) -> None:
        image_sender = RecordingImageSender()
        sent: list[str] = []
        notifier = KakaoNotifier(
            Path("."), sender=lambda message, _url: sent.append(message), image_sender=image_sender
        )
        plain = make_listing(2_550_000_000)  # matches, but never dips to urgent
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(
                CONFIG, MappingCollector({"weverfield": [plain]}), store, notifier
            )
            result = service.scan()

        self.assertEqual(len(result.matched), 1)
        self.assertEqual(image_sender.calls, [], "알림이 없으면 카드도 보내지 않는다")
        self.assertEqual(sent, [])

    def test_fallback_text_carries_alerts_only(self) -> None:
        image_sender = RecordingImageSender(error=RuntimeError("렌더 실패"))
        sent: list[str] = []
        notifier = KakaoNotifier(
            Path("."), sender=lambda message, _url: sent.append(message), image_sender=image_sender
        )
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(
                CONFIG,
                MappingCollector({"weverfield": self._matched_set()}),
                store,
                notifier,
            )
            service.scan()

        # 200 characters cannot hold all three, and the urgent one must survive.
        self.assertEqual(len(sent), 1)
        self.assertIn("1건", sent[0])
        self.assertIn("급매1", sent[0])

    def test_scan_alert_uses_the_card(self) -> None:
        image_sender = RecordingImageSender()
        sent: list[str] = []
        notifier = KakaoNotifier(
            Path("."), sender=lambda message, _url: sent.append(message), image_sender=image_sender
        )
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(
                CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier
            )
            service.scan()

        self.assertEqual(len(image_sender.calls), 1)
        self.assertEqual(sent, [], "the text path must not also fire")
        _path, title, _description, link_url = image_sender.calls[0]
        self.assertIn("급매 1", title)
        self.assertEqual(link_url, service_module.REPORT_URL)

    def test_card_failure_falls_back_to_text(self) -> None:
        image_sender = RecordingImageSender(error=RuntimeError("업로드 실패"))
        sent: list[str] = []
        notifier = KakaoNotifier(
            Path("."), sender=lambda message, _url: sent.append(message), image_sender=image_sender
        )
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(
                CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier
            )
            service.scan()

        self.assertEqual(len(sent), 1, "an alert must still reach the user")
        self.assertIn("급매", sent[0])

    def test_total_failure_is_queued(self) -> None:
        def explode(*_args, **_kwargs):
            raise RuntimeError("카카오 다운")

        notifier = KakaoNotifier(
            Path("."), sender=explode, image_sender=RecordingImageSender(RuntimeError("렌더 실패"))
        )
        with tempfile.TemporaryDirectory() as directory:
            store = FileStore(Path(directory))
            service = FinderService(
                CONFIG, FakeCollector(make_listing(2_500_000_000)), store, notifier
            )
            with self.assertRaises(RuntimeError):
                service.scan()
            queued = store.queue_path.read_text(encoding="utf-8").strip().splitlines()

        self.assertEqual(len(queued), 1)
        self.assertIn("급매", queued[0])


if __name__ == "__main__":
    unittest.main()
