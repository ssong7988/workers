"""카드 소비 요약을 카카오톡으로 보낸다.

명세서가 도착한 달에 한 번만 보낸다. 스케줄러가 매일 돌아도 이미 보낸 청구월은
건너뛰므로, 수집을 자주 확인해도 알림이 여러 번 가지 않는다.

    manage.py send_spending_digest              # 아직 안 보낸 최신 달만
    manage.py send_spending_digest --month 2026-09
    manage.py send_spending_digest --force      # 이미 보낸 달도 다시
    manage.py send_spending_digest --dry-run    # 보낼 내용만 출력
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from spending.analysis import latest_statement
from spending.delivery import SpendingDeliveryError, build_digest, send_digest
from spending.models import Statement


class Command(BaseCommand):
    help = "카드 소비 요약 한 통을 카카오톡으로 보낸다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--month", help="청구월 (YYYY-MM). 없으면 최신 달")
        parser.add_argument(
            "--force", action="store_true", help="이미 보낸 달도 다시 보낸다"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="보내지 않고 내용만 출력한다"
        )

    def handle(self, *args, **options) -> None:
        statement = self._target(options.get("month"))
        if statement is None:
            raise CommandError(
                "저장된 명세서가 없습니다. spending-analyzer가 먼저 보내야 합니다."
            )

        if statement.digest_sent_at and not options["force"]:
            self.stdout.write(
                f"{statement.billing_month}은 이미 "
                f"{timezone.localtime(statement.digest_sent_at):%Y-%m-%d %H:%M}에 보냈습니다. "
                "다시 보내려면 --force."
            )
            return

        try:
            if options["dry_run"]:
                digest = build_digest(statement.billing_month)
                self.stdout.write("--- 보낼 내용 ---")
                self.stdout.write(digest.message)
                buttons = ", ".join(title for title, _ in digest.buttons) or "없음"
                self.stdout.write(f"--- 버튼: {buttons} ---")
                return
            outcome = send_digest(statement.billing_month)
        except SpendingDeliveryError as exc:
            raise CommandError(str(exc)) from exc

        Statement.objects.filter(pk=statement.pk).update(digest_sent_at=timezone.now())
        self.stdout.write(self.style.SUCCESS(outcome))

    def _target(self, month: str | None) -> Statement | None:
        if month:
            statement = Statement.objects.filter(billing_month=month).first()
            if statement is None:
                raise CommandError(f"{month} 명세서가 없습니다.")
            return statement
        return latest_statement()
