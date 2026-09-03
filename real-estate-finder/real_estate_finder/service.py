"""Application orchestration for scans, urgent notifications, and digests."""

from __future__ import annotations

from datetime import datetime
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
from .publish import is_live
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
        # Kept for API compatibility. UI builds are an explicit deployment task;
        # scans only refresh app/report-data.json.
        self.build_report = build_report

    def scan(self, *, notify_urgent: bool = True, smoke: bool = False) -> ScanResult:
        started = iso_now()
        conditions = [condition for condition in self.config.searches if condition.enabled]
        result = ScanResult(started_at=started, finished_at=started)
        collected_by_condition: dict[str, list[Listing]] = {}
        pending_notifications: list[tuple[Listing, bool, bool]] = []
        # Counted only to explain a scan that sends nothing. Without them the
        # console cannot tell "nothing to report" apart from "something broke".
        urgent_hit = 0
        urgent_repeat = 0
        new_seen = 0
        new_muted = 0
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
                urgent_hit += is_urgent
                new_seen += is_new
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
                else:
                    urgent_repeat += is_urgent
                    new_muted += is_new and not condition.notify_new
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

        # Save before sending any notification: the report site reads this file
        # on every request, so the card's `전체 매물 보기` link must already
        # match what gets served by the time is_live() checks it below.
        if result.successful_conditions:
            state["listings"] = next_state
            state["last_successful_scan"] = iso_now()
            self.store.save_state(state)

        if pending_notifications:
            # Alerts decide *whether* to send; the card carries every matched
            # listing so one message shows the whole picture, with the alerted
            # ones badged.
            flags = {listing.key: (urgent, new) for listing, urgent, new in pending_notifications}
            items: list[CardItem] = [
                (listing, *flags.get(listing.key, (False, False)))
                for listing in result.matched
            ]
            channel = self._safe_send_card(
                items, heading="오늘의 매물", alerts=pending_notifications
            )
            urgent_alerts = sum(urgent for _, urgent, _ in pending_notifications)
            result.notification = (
                f"카카오 전송 완료({channel}): 급매 {urgent_alerts}건 · "
                f"신규 {len(pending_notifications) - urgent_alerts}건 · "
                f"카드에 조건충족 {len(result.matched)}건"
            )
        elif smoke:
            result.notification = "smoke 모드: 정규 급매 판정을 건너뛰고 전체 카드를 보냅니다"
        else:
            result.notification = _no_alert_reason(
                result,
                urgent_hit=urgent_hit,
                urgent_repeat=urgent_repeat,
                new_seen=new_seen,
                new_muted=new_muted,
            )
        result.finished_at = iso_now()
        self.store.append_observations(observed)
        self.store.append_run(result)
        return result

    def scheduled_run(self) -> ScanResult:
        result = self.scan(notify_urgent=True)
        now = datetime.now(ZoneInfo(self.config.timezone))
        if result.success and now.weekday() in self.config.digest_weekdays and now.hour == self.config.digest_hour:
            result.notification = f"{self.send_digest(result.matched)} (정기 보고)"
        elif result.failed_conditions:
            self._safe_send(scan_summary_message(result), REPORT_URL)
            result.notification = "카카오 전송 완료(텍스트): 수집 실패 요약을 보냈습니다"
        return result

    def smoke_test(self) -> ScanResult:
        result = self.scan(notify_urgent=False, smoke=True)
        if result.success and result.matched:
            # The same path scan() and send_digest() take, so a smoke test
            # arrives as one Kakao message: the card, carrying the original
            # image and the full report as its two buttons. This used to send a
            # summary plus one text per listing, which was 42 messages.
            result.notification = self.send_digest(result.matched)
        else:
            # Only when there is no card to send does a text go out instead.
            self._safe_send(scan_summary_message(result, smoke=True), REPORT_URL)
            result.notification = "카카오 전송 완료(텍스트): 조회 요약을 보냈습니다"
        return result

    def send_digest(self, listings: list[Listing] | None = None) -> str:
        if listings is None:
            state = self.store.load_state()
            listings = [
                Listing.from_dict(payload)
                for payload in state.get("listings", {}).values()
                if payload.get("active")
            ]
        if not listings:
            self._safe_send("☀️ 과천 관심 매물이 없습니다.", REPORT_URL)
            return "카카오 전송 완료(텍스트): 활성 매물이 0건이라 빈 보고를 보냈습니다"
        items: list[CardItem] = [
            (
                listing,
                listing.effective_urgent_price_won is not None
                and listing.price_won <= listing.effective_urgent_price_won,
                False,
            )
            for listing in sorted(listings, key=_sort_key)
        ]
        channel = self._safe_send_card(items, heading="과천 관심 매물")
        return f"카카오 전송 완료({channel}): 매물 {len(items)}건"

    def _safe_send_card(
        self,
        items: list[CardItem],
        *,
        heading: str,
        alerts: list[CardItem] | None = None,
    ) -> str:
        """Send the listings as one card image, degrading to text on any failure.

        The image exists to escape Kakao's 200-character text limit, but an
        alert that cannot be rendered still has to reach the user. The text
        fallback carries `alerts` when given: 200 characters cannot hold the
        full list, and losing the urgent listing to truncation is the worst
        possible outcome.

        Returns the channel that carried the message, so the caller can tell the
        user which one it was.
        """
        channel = "텍스트"
        if self.use_cards:
            try:
                observed_at = max(listing.observed_at for listing, _, _ in items)
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
                return "카드 이미지"
            except Exception as exc:
                print(f"카드 전송 실패, 텍스트로 대체합니다: {exc}")
                channel = "텍스트 폴백"
        self._safe_send(batch_listing_message(alerts or items), REPORT_URL)
        return channel

    def _publish_report(self, observed_at: str) -> str | None:
        """Link the report only when the local report server already serves this scan.

        `state.json` is saved before any notification goes out (see `scan()`),
        so the report server should already reflect this observation. A miss
        here means the server or its Tailscale Funnel tunnel is down.
        """
        try:
            if is_live(observed_at, REPORT_URL):
                return REPORT_URL
            print("리포트 서버가 이번 조회 결과를 아직 보여주지 않습니다.")
            print(
                "report-site\\run-site.bat이 실행 중인지, "
                "Tailscale Funnel이 살아있는지 확인하세요."
            )
        except Exception as exc:
            print(f"리포트 서버 확인 실패: {exc}")
        print("전체 매물 보기 버튼 없이 카드만 보냅니다.")
        return None

    def _safe_send(self, message: str, link_url: str) -> None:
        try:
            self.notifier.send(message, link_url)
        except Exception as exc:
            self.store.enqueue_notification(message, link_url, str(exc))
            raise


def _no_alert_reason(
    result: ScanResult,
    *,
    urgent_hit: int,
    urgent_repeat: int,
    new_seen: int,
    new_muted: int,
) -> str:
    """Explain a scan that sent nothing.

    Sending only on an alert is the intended policy, but staying silent about it
    made a perfectly normal run look like a failed one.
    """
    if result.failed_conditions:
        return (
            "카카오 미전송: 수집이 실패해 알림을 보내지 않았습니다 "
            f"(실패 조건 {len(result.failed_conditions)}개)"
        )
    if not result.matched:
        return "카카오 미전송: 조건을 충족한 매물이 0건입니다"

    reasons: list[str] = []
    if not urgent_hit:
        reasons.append("급매 기준(urgent_price_won) 이하로 내려온 매물 없음")
    elif urgent_repeat:
        reasons.append(f"급매 {urgent_repeat}건은 이미 같은 가격 이하로 알림을 보냈습니다")
    if not new_seen:
        reasons.append("처음 보는 매물 없음 (모두 이전 스캔에서 확인)")
    elif new_muted:
        reasons.append(f"신규 {new_muted}건은 notify_new가 꺼진 조건이라 알리지 않습니다")
    reasons.append(
        "지금 전체 매물을 카톡으로 받으려면: send-report.bat "
        "(또는 python -m real_estate_finder send-digest)"
    )
    head = f"카카오 미전송: 조건충족 {len(result.matched)}건 중 알림 대상 0건"
    return "\n".join([head, *(f"  - {reason}" for reason in reasons)])


def _sort_key(listing: Listing) -> tuple[bool, int, int]:
    urgent = (
        listing.effective_urgent_price_won is not None
        and listing.price_won <= listing.effective_urgent_price_won
    )
    floor = listing.floor if listing.floor is not None else 999
    return (not urgent, listing.price_won, floor)
