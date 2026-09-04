"""Send committed scan state as one Kakao message with two links.

The message used to be a rendered PNG card. It is now text carrying two
buttons: one to the price statistics, one to the full listing report. Both
point at this same server, so a single liveness check governs both.
"""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from .models import GlobalRule, Listing, NotificationFailure, Scan
from .notifier import (
    CardItem,
    KakaoNotifier,
    TEXT_LIMIT,
    batch_listing_message,
    scan_summary_message,
    stats_headline,
)
from .publish import is_live
from .scanning import ScanDecision
from .statistics import default_summary


STATS_BUTTON = "통계 보기"
REPORT_BUTTON = "전체 매물 보기"
ALERT_PREFIX = "⚠️ "


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

    def _buttons(self, items: list[CardItem]) -> list[tuple[str, str]]:
        """Attach the links only while the public site serves this very scan.

        A button that opens yesterday's numbers is worse than no button, so a
        stale or unreachable site drops both.
        """
        report_url = settings.REPORT_PUBLIC_URL
        if not items or not report_url:
            return []
        observed_at = max(item.observed_at for item, _, _ in items).isoformat()
        if not is_live(observed_at, report_url):
            return []
        buttons = []
        if settings.REPORT_STATS_URL:
            buttons.append((STATS_BUTTON, settings.REPORT_STATS_URL))
        buttons.append((REPORT_BUTTON, report_url))
        return buttons

    def _body(self, items: list[CardItem], *, with_stats: bool) -> str:
        """The listing lines, preceded by a statistics line when there is room."""
        headline = ""
        if with_stats:
            rule = GlobalRule.objects.filter(pk=1).only("timezone").first()
            label, period = default_summary(
                rule.timezone if rule else settings.TIME_ZONE
            )
            headline = stats_headline(label, period)
        budget = TEXT_LIMIT - (len(headline) + 1 if headline else 0)
        listings = batch_listing_message(items, budget=budget)
        return f"{headline}\n{listings}" if headline else listings

    def send_message(
        self,
        items: list[CardItem],
        *,
        alerts: list[CardItem] | None = None,
        scan: Scan | None = None,
    ) -> str:
        buttons = self._buttons(items)
        message = self._body(alerts or items, with_stats=bool(buttons))
        if not buttons:
            # No live site to link to: the text still carries the listings.
            self._send_text(message, scan=scan)
            return "텍스트"
        try:
            self.notifier.send_links(message, buttons)
        except Exception as exc:
            self._record_failure(message, exc, scan)
            if scan is not None:
                scan.notification = f"카카오 전송 실패: {exc}"
                scan.save(update_fields=("notification",))
            raise DeliveryError(f"카카오 전송 실패: {exc}") from exc
        return f"링크 {len(buttons)}개"

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
        channel = self.send_message(items, alerts=alerts, scan=decision.scan)
        urgent_count = sum(alert.is_urgent for alert in decision.alerts)
        notification = (
            f"카카오 전송 완료({channel}): 급매 {urgent_count}건 · "
            f"신규 {len(decision.alerts) - urgent_count}건 · "
            f"조건충족 {len(decision.matched)}건"
        )
        decision.scan.notification = notification
        decision.scan.save(update_fields=("notification",))
        return notification

    def send_smoke(self, decision: ScanDecision) -> str:
        if decision.scan.success and decision.matched:
            items: list[CardItem] = [
                (listing, listing.is_urgent, False) for listing in decision.matched
            ]
            channel = self.send_message(items, scan=decision.scan)
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

    def send_alert(self, text: str) -> str:
        """Send a plain-text alert - e.g. an Airflow task failure summary.

        Airflow (WSL) shells out to `manage.py send_alert` instead of talking
        to Kakao itself, so the token and `NotificationFailure` bookkeeping
        stay in this one place rather than being duplicated on the Linux side.
        """
        message = f"{ALERT_PREFIX}{text}"[:TEXT_LIMIT]
        self._send_text(message)
        return "카카오 전송 완료(텍스트): 오류 알림"

    def send_digest(self) -> str:
        listings = list(
            Listing.objects.filter(active=True, condition__enabled=True).select_related(
                "condition"
            )
        )
        if not listings:
            self._send_text("☀️ 관심 매물이 없습니다.")
            return "카카오 전송 완료(텍스트): 활성 매물이 0건이라 빈 보고를 보냈습니다"
        items: list[CardItem] = [
            (listing, listing.is_urgent, False) for listing in listings
        ]
        channel = self.send_message(items)
        return f"카카오 전송 완료({channel}): 매물 {len(items)}건"
