from datetime import datetime
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from properties.models import GlobalRule, Scan


class ScanStatusCommandTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create(timezone="Asia/Seoul")

    def test_no_scans_today_fails(self) -> None:
        with self.assertRaises(CommandError):
            call_command("scan_status", "--since=07:00", stdout=StringIO())

    def test_successful_scan_after_threshold_passes(self) -> None:
        now = timezone.localtime(timezone.now())
        Scan.objects.create(
            started_at=now.replace(hour=7, minute=30, second=0, microsecond=0),
            success=True,
        )
        out = StringIO()
        call_command("scan_status", "--since=07:00", stdout=out)
        self.assertIn("성공한 수집이 있습니다", out.getvalue())

    def test_scan_before_threshold_does_not_count(self) -> None:
        now = timezone.localtime(timezone.now())
        Scan.objects.create(
            started_at=now.replace(hour=6, minute=0, second=0, microsecond=0),
            success=True,
        )
        with self.assertRaises(CommandError):
            call_command("scan_status", "--since=07:00", stdout=StringIO())

    def test_failed_scan_does_not_count(self) -> None:
        now = timezone.localtime(timezone.now())
        Scan.objects.create(
            started_at=now.replace(hour=7, minute=30, second=0, microsecond=0),
            success=False,
        )
        with self.assertRaises(CommandError):
            call_command("scan_status", "--since=07:00", stdout=StringIO())

    def test_malformed_since_is_rejected(self) -> None:
        with self.assertRaises(CommandError):
            call_command("scan_status", "--since=not-a-time", stdout=StringIO())


class SendAlertCommandTests(TestCase):
    def setUp(self) -> None:
        GlobalRule.objects.create(timezone="Asia/Seoul")

    def test_calls_delivery_service(self) -> None:
        with mock.patch(
            "properties.management.commands.send_alert.DeliveryService"
        ) as service_cls:
            service_cls.return_value.send_alert.return_value = "카카오 전송 완료(텍스트): 오류 알림"
            out = StringIO()
            call_command("send_alert", "테스트 오류", stdout=out)
        service_cls.return_value.send_alert.assert_called_once_with("테스트 오류")
        self.assertIn("오류 알림", out.getvalue())
