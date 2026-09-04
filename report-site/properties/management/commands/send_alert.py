from django.core.management.base import BaseCommand, CommandError

from properties.delivery import DeliveryError, DeliveryService


class Command(BaseCommand):
    help = (
        "임의의 텍스트 1통을 카카오톡으로 보냅니다. "
        "Airflow의 on_failure_callback이 에러 요약을 보낼 때 씁니다."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("text", help="보낼 메시지 (200자를 넘으면 잘립니다)")

    def handle(self, *args, **options) -> None:
        try:
            result = DeliveryService().send_alert(options["text"])
        except DeliveryError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(result))
