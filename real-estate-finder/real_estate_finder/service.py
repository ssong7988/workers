"""Application orchestration for scans, urgent notifications, and digests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .card import CardItem, build_card_image
from .models import AppConfig, Listing, ScanResult, iso_now
from .notifier import (
    REPORT_URL,
    KakaoNotifier,
    batch_listing_message,
    card_caption,
    card_heading,
    scan_summary_message,
)
from .parsing import matches_condition
from .publish import MANUAL_STEPS, build_site, is_live
from .report import write_report_data
from .storage import FileStore


class FinderService:
    def __init__(
        self,
        config: AppConfig,
        collector,
        store: FileStore,
        notifier: KakaoNotifier,
        use_cards: bool = True,
        build_report: bool = False,
    ) -> None:
        self.config = config
        self.collector = collector
        self.store = store
        self.notifier = notifier
        self.use_cards = use_cards
        # Kept for API compatibility. UI builds are now an explicit local task;
        # scans only refresh app/report-data.json.
        self.build_report = build_report

    def scan(self, *, notify_urgent: bool = True, smoke: bool = False) -> ScanResult:
        started = iso_now()
        conditions = [condition for condition in self.config.searches if condition.enabled]
        result = ScanResult(started_at=started, finished_at=started)
        collected_by_condition: dict[str, list[Listing]] = {}
        pending_notifications: list[tuple[Listing, bool, bool]] = []
        try:
            collected_by_condition = self.collector.collect_all(conditions)
            for condition in conditions:
                result.successful_conditions.append(condition.id)
        except Exception as exc:
            for condition in conditions:
                result.failed_conditions[condition.id] = str(exc)

        state = self.store.load_state()
        previous = state.setdefault("listings", {})
        next_state = dict(previous)
        observed: list[Listing] = []
        for condition in conditions:
            if condition.id not in collected_by_condition:
                continue
            condition_listings = collected_by_condition[condition.id]
            result.collected_count += len(condition_listings)
            seen_keys: set[str] = set()
            for listing in condition_listings:
                observed.append(listing)
                if not matches_condition(listing, condition, self.config.low_floor):
                    result.excluded_count += 1
                    continue
                seen_keys.add(listing.key)
                result.matched.append(listing)
                old = previous.get(listing.key, {})
                last_alert_price = old.get("last_urgent_alert_price_won")
                is_urgent = (
                    listing.effective_urgent_price_won is not None
                    and listing.price_won <= listing.effective_urgent_price_won
                )
                is_new = not bool(old)
                should_alert = is_urgent and (
                    last_alert_price is None or listing.price_won < int(last_alert_price)
                )
                if should_alert:
                    result.urgent.append(listing)
                    if notify_urgent and not smoke:
                        pending_notifications.append((listing, True, False))
                        last_alert_price = listing.price_won
                elif condition.notify_new and is_new and notify_urgent and not smoke:
                    pending_notifications.append((listing, False, True))
                payload = listing.to_dict()
                payload.update(
                    {
                        "first_seen_at": old.get("first_seen_at", listing.observed_at),
                        "last_seen_at": listing.observed_at,
                        "active": True,
                        "last_urgent_alert_price_won": last_alert_price,
                    }
                )
                next_state[listing.key] = payload
            for key, payload in list(next_state.items()):
                if payload.get("condition_id") == condition.id and key not in seen_keys:
                    payload["active"] = False

        if pending_notifications:
            # Alerts decide *whether* to send; the card carries every matched
            # listing so one message shows the whole picture, with the alerted
            # ones badged.
            flags = {listing.key: (urgent, new) for listing, urgent, new in pending_notifications}
            items: list[CardItem] = [
                (listing, *flags.get(listing.key, (False, False)))
                for listing in result.matched
            ]
            self._safe_send_card(
                items, heading="오늘의 매물", alerts=pending_notifications
            )
        result.finished_at = iso_now()
        self.store.append_observations(observed)
        self.store.append_run(result)
        if result.successful_conditions:
            state["listings"] = next_state
            state["last_successful_scan"] = result.finished_at
            self.store.save_state(state)
        return result

    def scheduled_run(self) -> ScanResult:
        result = self.scan(notify_urgent=True)
        now = datetime.now(ZoneInfo(self.config.timezone))
        if result.success and now.weekday() in self.config.digest_weekdays and now.hour == self.config.digest_hour:
            self.send_digest(result.matched)
        elif result.failed_conditions:
            self._safe_send(scan_summary_message(result), REPORT_URL)
        return result

    def smoke_test(self) -> ScanResult:
        result = self.scan(notify_urgent=False, smoke=True)
        if result.success and result.matched:
            # The same path scan() and send_digest() take, so a smoke test
            # arrives as one Kakao message: the card, carrying the original
            # image and the full report as its two buttons. This used to send a
            # summary plus one text per listing, which was 42 messages.
            self.send_digest(result.matched)
        else:
            # Only when there is no card to send does a text go out instead.
            self._safe_send(scan_summary_message(result, smoke=True), REPORT_URL)
        return result

    def send_digest(self, listings: list[Listing] | None = None) -> None:
        if listings is None:
            state = self.store.load_state()
            listings = [
                Listing.from_dict(payload)
                for payload in state.get("listings", {}).values()
                if payload.get("active")
            ]
        if not listings:
            self._safe_send("☀️ 과천 관심 매물이 없습니다.", REPORT_URL)
            return
        items: list[CardItem] = [
            (
                listing,
                listing.effective_urgent_price_won is not None
                and listing.price_won <= listing.effective_urgent_price_won,
                False,
            )
            for listing in sorted(listings, key=_sort_key)
        ]
        self._safe_send_card(items, heading="과천 관심 매물")

    def _safe_send_card(
        self,
        items: list[CardItem],
        *,
        heading: str,
        alerts: list[CardItem] | None = None,
    ) -> None:
        """Send the listings as one card image, degrading to text on any failure.

        The image exists to escape Kakao's 200-character text limit, but an
        alert that cannot be rendered still has to reach the user. The text
        fallback carries `alerts` when given: 200 characters cannot hold the
        full list, and losing the urgent listing to truncation is the worst
        possible outcome.
        """
        if self.use_cards:
            try:
                report_output = (
                    Path(__file__).resolve().parents[2]
                    / "property-report-site"
                    / "site-app"
                    / "app"
                    / "report-data.json"
                )
                observed_at = max(listing.observed_at for listing, _, _ in items)
                write_report_data(
                    [listing for listing, _, _ in items],
                    self.config,
                    report_output,
                    observed_at=observed_at,
                )
                report_link = self._publish_report(observed_at)
                image_path, width, height = build_card_image(
                    items,
                    self.store.data_dir / "cards" / "card.png",
                    heading=heading,
                    report_url=REPORT_URL,
                    timezone=self.config.timezone,
                )
                # Keep the full-resolution image action and add the hosted report
                # as a second Kakao button.
                self.notifier.send_image(
                    image_path,
                    card_heading(items),
                    card_caption(items),
                    report_link,
                    width,
                    height,
                )
                return
            except Exception as exc:
                print(f"카드 전송 실패, 텍스트로 대체합니다: {exc}")
        self._safe_send(batch_listing_message(alerts or items), REPORT_URL)

    def _publish_report(self, observed_at: str) -> str | None:
        """Link the report only when the local UI already serves this scan.

        The scanner writes the JSON but never builds or deploys the UI. Next.js
        development mode notices the changed file by itself. A stopped or stale
        local server simply means the Kakao card has no report button.
        """
        try:
            if is_live(observed_at, REPORT_URL):
                return REPORT_URL
            print("이번 결과는 아직 로컬 UI에 반영되지 않았습니다.")
            print(MANUAL_STEPS)
        except Exception as exc:
            print(f"로컬 UI 확인 실패: {exc}")
        print("전체 매물 보기 버튼 없이 카드만 보냅니다.")
        return None

    def _safe_send(self, message: str, link_url: str) -> None:
        try:
            self.notifier.send(message, link_url)
        except Exception as exc:
            self.store.enqueue_notification(message, link_url, str(exc))
            raise


def _sort_key(listing: Listing) -> tuple[bool, int, int]:
    urgent = (
        listing.effective_urgent_price_won is not None
        and listing.price_won <= listing.effective_urgent_price_won
    )
    floor = listing.floor if listing.floor is not None else 999
    return (not urgent, listing.price_won, floor)
