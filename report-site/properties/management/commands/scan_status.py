"""Answer, by exit code, whether a successful scan ran today after a given time.

Airflow's morning-digest DAG uses this instead of reading its own metadata:
what matters before sending the digest is whether there is fresh data to send,
not whether a particular DAG run happened to succeed. A scan started by hand
counts just as much as a scheduled one.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from properties.models import GlobalRule, Scan


class Command(BaseCommand):
    help = "오늘 지정한 시각 이후 성공한 수집이 있으면 0, 없으면 1로 종료합니다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--since",
            default="00:00",
            help="이 시각(HH:MM, 로컬 시간) 이후로 찾습니다. 기본값 00:00(오늘 전체).",
        )

    def handle(self, *args, **options) -> None:
        try:
            hour, minute = (int(part) for part in options["since"].split(":", 1))
        except ValueError as exc:
            raise CommandError("--since는 HH:MM 형식이어야 합니다.") from exc

        rule = GlobalRule.objects.filter(pk=1).only("timezone").first()
        tz = ZoneInfo(rule.timezone if rule else settings.TIME_ZONE)
        today = timezone.localtime(timezone.now(), tz).date()
        threshold = datetime.combine(today, time(hour, minute), tzinfo=tz)

        found = Scan.objects.filter(started_at__gte=threshold, success=True).exists()
        if found:
            self.stdout.write(self.style.SUCCESS(f"{threshold.isoformat()} 이후 성공한 수집이 있습니다."))
            return
        raise CommandError(f"{threshold.isoformat()} 이후 성공한 수집이 없습니다.")
