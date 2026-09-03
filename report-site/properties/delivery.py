"""Send committed scan state as a Kakao card with a text fallback."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from .card import build_card_image
from .models import GlobalRule, Listing, NotificationFailure, Scan
from .notifier import (
    CardItem,
    KakaoNotifier,
    batch_listing_message,
    card_caption,
    card_heading,
    scan_summary_message,
)
from .publish import is_live
from .scanning import ScanDecision


class DeliveryError(RuntimeError):
    pass


class DeliveryService:
    def __init__(self, notifier: KakaoNotifier | None = None) -> None:
        self.notifier = notifier or KakaoNotifier()

    def _record_failure(
        self, message: str, error: Exception, scan: Scan | None = None
    ) -> None:
        NotificationFailure.objects.create(
            scan=scan,
            message=message,
            link_url=settings.REPORT_PUBLIC_URL,
            error=str(error),
            last_attempt_at=timezone.now(),
        )

    def _send_text(
        self, message: str, *, scan: Scan | None = None, link_url: str | None = None
    ) -> None:
        target = settings.REPORT_PUBLIC_URL if link_url is None else link_url
        try:
            self.notifier.send(message, target)
        except Exception as exc:
            self._record_failure(message, exc, scan)
            if scan is not None:
                scan.notification = f"카카오 전송 실패: {exc}"
                scan.save(update_fields=("notification",))
            raise DeliveryError(f"카카오 텍스트 전송 실패: {exc}") from exc

    def _report_link(self, items: list[CardItem]) -> str | None:
        report_url = settings.REPORT_PUBLIC_URL
        if not items or not report_url:
            return None
        observed_at = max(item.observed_at for item, _, _ in items).isoformat()
        return report_url if is_live(observed_at, report_url) else None

    def send_card(
        self,
        items: list[CardItem],
        *,
        heading: str,
        alerts: list[CardItem] | None = None,
        scan: Scan | None = None,
    ) -> str:
        try:
            rule = GlobalRule.objects.get(pk=1)
            report_link = self._report_link(items)
            image_path, width, height = build_card_image(
                items,
                settings.DATA_DIR / "cards" / "card.png",
                heading=heading,
                report_url=settings.REPORT_PUBLIC_URL,
                timezone_name=rule.timezone,
            )
            self.notifier.send_image(
                image_path,
                card_heading(items),
                card_caption(items),
                report_link,
                width,
                height,
            )
            return "카드 이미지"
        except Exception:
            message = batch_listing_message(alerts or items)
            self._send_text(message, scan=scan)
            return "텍스트 폴백"

    def send_scan_alerts(self, decision: ScanDecision) -> str:
        flags = {
            alert.listing.key: (alert.is_urgent, alert.is_new)
            for alert in decision.alerts
        }
        items: list[CardItem] = [
            (listing, *flags.get(listing.key, (False, False)))
            for listing in decision.matched
        ]
        alerts: list[CardItem] = [
            (alert.listing, alert.is_urgent, alert.is_new)
            for alert in decision.alerts
        ]
        channel = self.send_card(
            items,
            heading="오늘의 매물",
            alerts=alerts,
            scan=decision.scan,
        )
        urgent_count = sum(alert.is_urgent for alert in decision.alerts)
        notification = (
            f"카카오 전송 완료({channel}): 급매 {urgent_count}건 · "
            f"신규 {len(decision.alerts) - urgent_count}건 · "
            f"카드에 조건충족 {len(decision.matched)}건"
        )
        decision.scan.notification = notification
        decision.scan.save(update_fields=("notification",))
        return notification

    def send_smoke(self, decision: ScanDecision) -> str:
        if decision.scan.success and decision.matched:
            items: list[CardItem] = [
                (listing, listing.is_urgent, False) for listing in decision.matched
            ]
            channel = self.send_card(
                items,
                heading="과천 관심 매물",
                scan=decision.scan,
            )
            notification = f"카카오 전송 완료({channel}): 매물 {len(items)}건"
        else:
            message = scan_summary_message(
                success=decision.scan.success,
                collected_count=decision.scan.collected_count,
                matched_count=decision.scan.matched_count,
                urgent_count=decision.scan.urgent_count,
                failed_conditions=decision.scan.failed_conditions,
                smoke=True,
            )
            self._send_text(message, scan=decision.scan)
            notification = "카카오 전송 완료(텍스트): 조회 요약을 보냈습니다"
        decision.scan.notification = notification
        decision.scan.save(update_fields=("notification",))
        return notification

    def send_digest(self) -> str:
        listings = list(
            Listing.objects.filter(active=True, condition__enabled=True).select_related(
                "condition"
            )
        )
        if not listings:
            self._send_text("☀️ 과천 관심 매물이 없습니다.")
            return "카카오 전송 완료(텍스트): 활성 매물이 0건이라 빈 보고를 보냈습니다"
        items: list[CardItem] = [
            (listing, listing.is_urgent, False) for listing in listings
        ]
        channel = self.send_card(items, heading="과천 관심 매물")
        return f"카카오 전송 완료({channel}): 매물 {len(items)}건"
