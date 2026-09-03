from django.core.management.base import BaseCommand, CommandError

from properties.delivery import DeliveryError, DeliveryService


class Command(BaseCommand):
    help = "PostgreSQL의 활성 매물 전체를 카카오톡 메시지 1통으로 전송합니다."

    def handle(self, *args, **options) -> None:
        try:
            result = DeliveryService().send_digest()
        except DeliveryError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(result))
