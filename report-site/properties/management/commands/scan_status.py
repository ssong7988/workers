"""Answer, by exit code, whether a successful scan ran today after a given time.

Airflow's morning-digest DAG uses this instead of reading its own metadata:
what matters before sending the digest is whether there is fresh data to send,
not whether a particular DAG run happened to succeed. A scan started by hand
counts just as much as a scheduled one.

`--json` adds a machine-readable payload on stdout without changing that exit
code contract. Dagster's `naver_listings` asset uses it to attach the scan's
own counts to the materialization, which is what makes the Catalog worth
looking at - Dagster shells out to `run-scan.ps1` and would otherwise know
nothing about what the scan produced. The payload is pure ASCII
(`json.dumps` escapes non-ASCII by default) so the caller can decode it
without guessing the Windows console codepage.
"""

import json
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
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="사람이 읽는 문구 대신 JSON 한 줄을 출력합니다. 종료 코드는 동일합니다.",
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

        # Scan.Meta.ordering is ("-started_at",), so first() is the latest one.
        scan = Scan.objects.filter(started_at__gte=threshold, success=True).first()

        if options["as_json"]:
            self.stdout.write(json.dumps(self._payload(threshold, scan, tz)))
        if scan is not None:
            if not options["as_json"]:
                self.stdout.write(
                    self.style.SUCCESS(f"{threshold.isoformat()} 이후 성공한 수집이 있습니다.")
                )
            return
        raise CommandError(f"{threshold.isoformat()} 이후 성공한 수집이 없습니다.")

    @staticmethod
    def _payload(threshold: datetime, scan: Scan | None, tz: ZoneInfo) -> dict:
        """Keys stay stable - dagster_project/definitions.py reads them by name.

        `started_at` is localized: it ends up on a Dagster materialization for
        a person to read, and the column is stored in UTC.
        """
        if scan is None:
            return {"found": False, "threshold": threshold.isoformat(), "scan": None}
        return {
            "found": True,
            "threshold": threshold.isoformat(),
            "scan": {
                "started_at": timezone.localtime(scan.started_at, tz).isoformat(),
                "collected": scan.collected_count,
                "matched": scan.matched_count,
                "urgent": scan.urgent_count,
                "excluded": scan.excluded_count,
            },
        }
