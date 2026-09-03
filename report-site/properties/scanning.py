"""Transactional scan recording and alert decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .matching import classify_exclusion, explain_condition
from .models import GlobalRule, Listing, Observation, Scan, SearchCondition


@dataclass(frozen=True)
class AlertDecision:
    listing: Listing
    is_urgent: bool
    is_new: bool


@dataclass(frozen=True)
class ScanDecision:
    scan: Scan
    alerts: tuple[AlertDecision, ...]
    matched: tuple[Listing, ...]


def _timestamp(value: object, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = parse_datetime(str(value)) if value else None
    if parsed is None:
        raise ValueError(f"올바르지 않은 {label}: {value!r}")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _property_values(payload: Mapping[str, object]) -> dict[str, object]:
    try:
        area = Decimal(str(payload["exclusive_area_m2"]))
        price = int(payload["price_won"])
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("매물의 면적 또는 가격이 올바르지 않습니다.") from exc
    if not str(payload.get("listing_id", "")).strip():
        raise ValueError("매물 ID가 비어 있습니다.")
    return {
        "complex_name": str(payload.get("complex_name", "")),
        "type_name": str(payload.get("type_name", "")),
        "exclusive_area_m2": area,
        "price_won": price,
        "floor_text": str(payload.get("floor_text", "")),
        "floor": None,
        "direction": str(payload.get("direction", "")),
        "description": str(payload.get("description", "")),
        "url": str(payload.get("url", "")),
        "observed_at": _timestamp(payload.get("observed_at"), "관측 시각"),
        "is_low_floor": False,
        "effective_max_price_won": None,
        "effective_urgent_price_won": None,
    }


def _no_alert_reason(
    *,
    failed_conditions: Mapping[str, str],
    matched_count: int,
    urgent_hit: int,
    urgent_repeat: int,
    new_seen: int,
    new_muted: int,
) -> str:
    if failed_conditions:
        return (
            "카카오 미전송: 수집이 실패해 알림을 보내지 않았습니다 "
            f"(실패 조건 {len(failed_conditions)}개)"
        )
    if not matched_count:
        return "카카오 미전송: 조건을 충족한 매물이 0건입니다"

    reasons: list[str] = []
    if not urgent_hit:
        reasons.append("급매 기준(urgent_price_won) 이하로 내려온 매물 없음")
    elif urgent_repeat:
        reasons.append(f"급매 {urgent_repeat}건은 이미 같은 가격 이하로 알림을 보냈습니다")
    if not new_seen:
        reasons.append("처음 보는 매물 없음 (모두 이전 스캔에서 확인)")
    elif new_muted:
        reasons.append(f"신규 {new_muted}건은 notify_new가 꺼진 조건이라 알리지 않습니다")
    reasons.append("지금 전체 매물을 카톡으로 받으려면: send-report.bat")
    head = f"카카오 미전송: 조건충족 {matched_count}건 중 알림 대상 0건"
    return "\n".join([head, *(f"  - {reason}" for reason in reasons)])


@transaction.atomic
def record_scan(
    *,
    started_at: datetime | str,
    finished_at: datetime | str,
    observations: Iterable[Mapping[str, object]],
    successful_conditions: Iterable[str],
    failed_conditions: Mapping[str, str] | None = None,
    notify_urgent: bool = True,
    smoke: bool = False,
) -> ScanDecision:
    """Persist one scan and decide notifications before any message is sent."""
    successful_ids = list(dict.fromkeys(str(item) for item in successful_conditions))
    failures = {str(key): str(value) for key, value in (failed_conditions or {}).items()}
    conditions = {
        item.pk: item
        for item in SearchCondition.objects.filter(pk__in=successful_ids, enabled=True)
    }
    missing = [
        condition_id for condition_id in successful_ids if condition_id not in conditions
    ]
    if missing:
        raise ValueError(f"사용 가능한 검색 조건을 찾을 수 없습니다: {', '.join(missing)}")
    rule = GlobalRule.objects.get(pk=1)
    started = _timestamp(started_at, "수집 시작 시각")
    finished = _timestamp(finished_at, "수집 종료 시각")
    if finished < started:
        raise ValueError("수집 종료 시각은 시작 시각보다 빠를 수 없습니다.")

    scan = Scan.objects.create(
        started_at=started,
        finished_at=finished,
        success=not failures and bool(successful_ids),
        successful_conditions=successful_ids,
        failed_conditions=failures,
    )
    existing = {
        (item.condition_id, item.listing_id): item
        for item in Listing.objects.select_for_update().filter(
            condition_id__in=successful_ids
        )
    }
    seen_observations: set[tuple[str, str]] = set()
    seen_matched: dict[str, set[str]] = {
        condition_id: set() for condition_id in successful_ids
    }
    matched: list[Listing] = []
    alerts: list[AlertDecision] = []
    collected_count = excluded_count = urgent_hit = urgent_repeat = 0
    new_seen = new_muted = 0

    for raw_payload in observations:
        payload = dict(raw_payload)
        condition_id = str(payload.get("condition_id", ""))
        condition = conditions.get(condition_id)
        if condition is None:
            raise ValueError(
                "수집 성공 조건과 일치하지 않는 매물입니다: "
                f"{condition_id or '(없음)'}"
            )
        listing_id = str(payload.get("listing_id", "")).strip()
        identity = (condition_id, listing_id)
        if identity in seen_observations:
            raise ValueError(
                f"한 스캔에 같은 매물이 중복되었습니다: {condition_id}:{listing_id}"
            )
        seen_observations.add(identity)

        values = _property_values(payload)
        observation = Observation(
            scan=scan,
            condition=condition,
            listing_id=listing_id,
            raw_payload=payload,
            **values,
        )
        reason = explain_condition(observation, condition, rule)
        observation.exclusion_reason = reason or ""
        observation.exclusion_code = classify_exclusion(reason)
        observation.save()
        collected_count += 1
        if reason is not None:
            excluded_count += 1
            continue

        seen_matched[condition_id].add(listing_id)
        old = existing.get(identity)
        is_new = old is None
        last_alert_price = old.last_urgent_alert_price_won if old else None
        listing_values = {
            key: getattr(observation, key)
            for key in (
                "complex_name",
                "type_name",
                "exclusive_area_m2",
                "price_won",
                "floor_text",
                "floor",
                "direction",
                "description",
                "url",
                "observed_at",
                "is_low_floor",
                "effective_max_price_won",
                "effective_urgent_price_won",
            )
        }
        if old is None:
            listing = Listing(
                condition=condition,
                listing_id=listing_id,
                first_seen_at=observation.observed_at,
                last_seen_at=observation.observed_at,
                active=True,
                **listing_values,
            )
        else:
            listing = old
            for key, value in listing_values.items():
                setattr(listing, key, value)
            listing.last_seen_at = observation.observed_at
            listing.active = True

        is_urgent = listing.is_urgent
        urgent_hit += int(is_urgent)
        new_seen += int(is_new)
        should_alert = is_urgent and (
            last_alert_price is None or listing.price_won < last_alert_price
        )
        should_notify = notify_urgent and not smoke and (
            should_alert or (condition.notify_new and is_new)
        )
        if should_alert:
            scan.urgent_count += 1
        if should_notify:
            alert = AlertDecision(
                listing=listing,
                is_urgent=should_alert,
                is_new=not should_alert and is_new,
            )
            alerts.append(alert)
            if should_alert:
                listing.last_urgent_alert_price_won = listing.price_won
        else:
            urgent_repeat += int(is_urgent and not should_alert)
            new_muted += int(is_new and not condition.notify_new)
        listing.save()
        matched.append(listing)

    for condition_id, seen_ids in seen_matched.items():
        Listing.objects.filter(condition_id=condition_id, active=True).exclude(
            listing_id__in=seen_ids
        ).update(active=False)

    scan.collected_count = collected_count
    scan.matched_count = len(matched)
    scan.excluded_count = excluded_count
    if alerts:
        urgent_alerts = sum(item.is_urgent for item in alerts)
        scan.notification = (
            f"카카오 전송 대기: 급매 {urgent_alerts}건 · "
            f"신규 {len(alerts) - urgent_alerts}건 · 조건충족 {len(matched)}건"
        )
    elif smoke:
        scan.notification = "smoke 모드: 정규 급매 판정을 건너뛰고 전체 카드 전송 대기"
    else:
        scan.notification = _no_alert_reason(
            failed_conditions=failures,
            matched_count=len(matched),
            urgent_hit=urgent_hit,
            urgent_repeat=urgent_repeat,
            new_seen=new_seen,
            new_muted=new_muted,
        )
    scan.save(
        update_fields=(
            "collected_count",
            "matched_count",
            "urgent_count",
            "excluded_count",
            "notification",
        )
    )
    return ScanDecision(scan=scan, alerts=tuple(alerts), matched=tuple(matched))
