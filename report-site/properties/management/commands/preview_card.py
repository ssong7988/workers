from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from properties.card import CardRenderError, build_card_image
from properties.models import GlobalRule, Listing


class Command(BaseCommand):
    help = "PostgreSQL의 활성 매물로 카드 이미지만 만들고 전송하지 않습니다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--out",
            type=Path,
            default=settings.DATA_DIR / "card-preview.png",
        )

    def handle(self, *args, **options) -> None:
        listings = list(
            Listing.objects.filter(active=True, condition__enabled=True).select_related(
                "condition"
            )
        )
        if not listings:
            raise CommandError("활성 매물이 없습니다.")
        rule = GlobalRule.objects.get(pk=1)
        items = [(listing, listing.is_urgent, False) for listing in listings]
        try:
            image_path, width, height = build_card_image(
                items,
                options["out"],
                heading="과천 관심 매물",
                report_url=settings.REPORT_PUBLIC_URL,
                timezone_name=rule.timezone,
            )
        except CardRenderError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"카드 이미지 생성: {image_path} ({width}x{height}px, 매물 {len(items)}건)"
            )
        )
