from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from properties.models import Listing
from properties.publish import VERIFY_ATTEMPTS, describe_live, is_live


class Command(BaseCommand):
    help = "공개 리포트가 PostgreSQL의 최신 활성 매물을 서빙하는지 확인합니다."

    def handle(self, *args, **options) -> None:
        latest = (
            Listing.objects.filter(
                active=True, condition__enabled=True, duplicate_of__isnull=True
            )
            .order_by("-observed_at")
            .first()
        )
        if latest is None:
            raise CommandError("활성 매물이 없습니다.")
        observed_at = latest.observed_at.isoformat()
        report_url = settings.REPORT_PUBLIC_URL
        self.stdout.write(f"DB 상태: 기준 {observed_at}")
        self.stdout.write(f"현재 리포트 서버: {describe_live(report_url)}")
        if not is_live(observed_at, report_url, attempts=VERIFY_ATTEMPTS):
            raise CommandError("공개 리포트가 DB의 최신 조회 결과와 일치하지 않습니다.")
        self.stdout.write(self.style.SUCCESS("리포트 확인 완료"))
