"""Import legacy JSON/JSONL runtime state without modifying the source files."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from properties.models import (
    Listing,
    NotificationFailure,
    Observation,
    Scan,
    SearchCondition,
)


def _timestamp(value: object, label: str):
    parsed = parse_datetime(str(value)) if value else None
    if parsed is None:
        raise CommandError(f"올바르지 않은 {label}: {value!r}")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _json_lines(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise CommandError(f"{path}:{line_number}: JSON 오류: {exc}") from exc


def _property_values(payload: dict) -> dict:
    return {
        "complex_name": str(payload.get("complex_name", "")),
        "type_name": str(payload.get("type_name", "")),
        "exclusive_area_m2": Decimal(str(payload["exclusive_area_m2"])),
        "price_won": int(payload["price_won"]),
        "floor_text": str(payload.get("floor_text", "")),
        "floor": payload.get("floor"),
        "direction": str(payload.get("direction", "")),
        "description": str(payload.get("description", "")),
        "url": str(payload.get("url", "")),
        "observed_at": _timestamp(payload.get("observed_at"), "관측 시각"),
        "is_low_floor": bool(payload.get("is_low_floor", False)),
        "effective_max_price_won": payload.get("effective_max_price_won"),
        "effective_urgent_price_won": payload.get("effective_urgent_price_won"),
    }


class Command(BaseCommand):
    help = "기존 state.json 및 JSONL 실행 기록을 PostgreSQL로 이관합니다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--data-dir",
            type=Path,
            help="기존 데이터 디렉터리 (기본값: real-estate-finder/data)",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        data_dir = options["data_dir"] or settings.ROOT_DIR / "real-estate-finder" / "data"
        state_path = data_dir / "state.json"
        if not state_path.exists():
            raise CommandError(f"상태 파일이 없습니다: {state_path}")
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"상태 파일을 읽을 수 없습니다: {exc}") from exc

        conditions = {item.pk: item for item in SearchCondition.objects.all()}
        if not conditions:
            raise CommandError("검색 조건이 없습니다. import_searches를 먼저 실행하세요.")

        scans: list[Scan] = []
        for payload in _json_lines(data_dir / "scan-runs.jsonl"):
            started_at = _timestamp(payload.get("started_at"), "수집 시작 시각")
            values = {
                "finished_at": (
                    _timestamp(payload["finished_at"], "수집 종료 시각")
                    if payload.get("finished_at")
                    else None
                ),
                "success": bool(payload.get("success", False)),
                "successful_conditions": payload.get("successful_conditions", []),
                "failed_conditions": payload.get("failed_conditions", {}),
                "collected_count": int(payload.get("collected_count", 0)),
                "matched_count": int(payload.get("matched_count", 0)),
                "urgent_count": int(payload.get("urgent_count", 0)),
                "excluded_count": int(payload.get("excluded_count", 0)),
                "notification": str(payload.get("notification", "")),
            }
            scan, _ = Scan.objects.update_or_create(started_at=started_at, defaults=values)
            scans.append(scan)
        scans.sort(key=lambda item: item.started_at)

        observation_count = 0
        for payload in _json_lines(data_dir / "observations.jsonl"):
            values = _property_values(payload)
            observed_at = values["observed_at"]
            scan = next(
                (
                    item
                    for item in reversed(scans)
                    if item.started_at <= observed_at
                    and (item.finished_at is None or observed_at <= item.finished_at)
                ),
                None,
            )
            if scan is None:
                raise CommandError(
                    f"관측 {payload.get('listing_id')}의 수집 실행을 찾을 수 없습니다."
                )
            condition = conditions.get(str(payload.get("condition_id", "")))
            Observation.objects.update_or_create(
                scan=scan,
                condition=condition,
                listing_id=str(payload["listing_id"]),
                defaults={**values, "raw_payload": payload},
            )
            observation_count += 1

        listing_count = 0
        for payload in state.get("listings", {}).values():
            condition_id = str(payload.get("condition_id", ""))
            condition = conditions.get(condition_id)
            if condition is None:
                raise CommandError(f"매물의 검색 조건을 찾을 수 없습니다: {condition_id}")
            values = _property_values(payload)
            values.update(
                {
                    "first_seen_at": _timestamp(
                        payload.get("first_seen_at"), "최초 확인 시각"
                    ),
                    "last_seen_at": _timestamp(
                        payload.get("last_seen_at"), "최근 확인 시각"
                    ),
                    "active": bool(payload.get("active", False)),
                    "last_urgent_alert_price_won": payload.get(
                        "last_urgent_alert_price_won"
                    ),
                }
            )
            Listing.objects.update_or_create(
                condition=condition,
                listing_id=str(payload["listing_id"]),
                defaults=values,
            )
            listing_count += 1

        failure_count = 0
        for payload in _json_lines(data_dir / "notification-queue.jsonl"):
            NotificationFailure.objects.get_or_create(
                message=str(payload.get("message", "")),
                link_url=str(payload.get("link_url", "")),
                error=str(payload.get("error", "")),
            )
            failure_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                "상태 이관 완료: "
                f"수집 실행 {len(scans)}개, 원본 {observation_count}개, "
                f"매물 {listing_count}개, 알림 실패 {failure_count}개"
            )
        )
