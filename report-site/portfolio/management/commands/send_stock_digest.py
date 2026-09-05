"""금융자산 요약 한 통을 카카오톡으로 보낸다.

Dagster의 `stock_portfolio` 자산 그룹이 수집 뒤에 부를 자리이고, 사람이 손으로
확인할 때도 같은 명령을 쓴다.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from portfolio.delivery import StockDeliveryError, build_digest, send_digest


class Command(BaseCommand):
    help = "마지막 완전 수집일의 금융자산 요약을 카카오톡으로 1통 보냅니다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--as-of",
            type=date.fromisoformat,
            help="기준일 (YYYY-MM-DD). 기본값은 마지막 완전 수집일",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="보내지 않고 보낼 내용만 출력",
        )

    def handle(self, *args, **options) -> None:
        try:
            if options["dry_run"]:
                digest = build_digest(options["as_of"])
                self.stdout.write(digest.message)
                buttons = ", ".join(label for label, _url in digest.buttons) or "없음"
                self.stdout.write(self.style.WARNING(f"(전송 안 함) 버튼: {buttons}"))
                return
            self.stdout.write(self.style.SUCCESS(send_digest(options["as_of"])))
        except StockDeliveryError as exc:
            raise CommandError(str(exc)) from exc
