"""Import the initial YAML rules into the database."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from properties.models import GlobalRule, SearchCondition


def _decimal_or_none(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


class Command(BaseCommand):
    help = "검색조건 초기 YAML을 공통 규칙과 검색 조건 테이블로 이관합니다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--path",
            type=Path,
            help="YAML 경로 (기본값: properties/seed/searches.yaml)",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        path = options["path"] or Path(__file__).resolve().parents[2] / "seed" / "searches.yaml"
        if not path.exists():
            raise CommandError(f"검색조건 파일이 없습니다: {path}")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise CommandError(f"검색조건 파일을 읽을 수 없습니다: {exc}") from exc

        global_raw = raw.get("global_rules", {})
        low_floor = global_raw.get("low_floor", {})
        schedule = raw.get("schedule", {})
        rule_values = {
            "trade_type": str(global_raw.get("trade_type", "sale")),
            "low_floor_numeric_floors": [
                int(value) for value in low_floor.get("numeric_floors", [1, 2, 3])
            ],
            "low_floor_labels": [
                str(value).strip() for value in low_floor.get("labels", ["저", "저층"])
            ],
            "low_floor_price_discount_won": int(
                low_floor.get("price_discount_won", 100_000_000)
            ),
            "timezone": str(schedule.get("timezone", "Asia/Seoul")),
            "digest_weekdays": [
                int(value) for value in schedule.get("digest_weekdays", [0, 1, 2, 3, 4])
            ],
            "digest_hour": int(schedule.get("digest_hour", 8)),
        }
        rule = GlobalRule(pk=1, **rule_values)
        rule.full_clean(validate_unique=False)
        GlobalRule.objects.update_or_create(pk=1, defaults=rule_values)

        created = 0
        updated = 0
        seen_ids: set[str] = set()
        for item in raw.get("searches", []):
            try:
                condition_id = str(item["id"])
                name = str(item["name"])
            except (KeyError, TypeError) as exc:
                raise CommandError("각 검색 조건에는 id와 name이 필요합니다.") from exc
            if condition_id in seen_ids:
                raise CommandError(f"검색 조건 id가 중복되었습니다: {condition_id}")
            seen_ids.add(condition_id)
            allowed = item.get("allowed_types", "all")
            values = {
                "name": name,
                "complex_names": [
                    str(value).strip()
                    for value in item.get("complex_names", [name])
                ],
                "search_url": str(item.get("search_url", "")).strip(),
                "exclusive_area_m2": _decimal_or_none(item.get("exclusive_area_m2")),
                "exclusive_area_min_m2": _decimal_or_none(
                    item.get("exclusive_area_min_m2")
                ),
                "exclusive_area_max_m2": _decimal_or_none(
                    item.get("exclusive_area_max_m2")
                ),
                "allowed_types": (
                    None
                    if allowed == "all" or allowed is None
                    else [str(value).upper() for value in allowed]
                ),
                "max_price_won": item.get("max_price_won"),
                "urgent_price_won": item.get("urgent_price_won"),
                "notify_new": bool(item.get("notify_new", False)),
                "apply_low_floor_discount": bool(
                    item.get("apply_low_floor_discount", True)
                ),
                "enabled": bool(item.get("enabled", True)),
            }
            candidate = SearchCondition(id=condition_id, **values)
            candidate.full_clean(validate_unique=False)
            _, was_created = SearchCondition.objects.update_or_create(
                id=condition_id, defaults=values
            )
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"검색조건 이관 완료: 공통 규칙 1개, 신규 {created}개, 갱신 {updated}개"
            )
        )
