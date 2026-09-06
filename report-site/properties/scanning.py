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
        "building": str(payload.get("building", "")),
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
    existing_urgent: int,
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
    elif existing_urgent:
        reasons.append(f"급매 {existing_urgent}건은 이번 스캔에서 처음 발견된 매물이 아닙니다")
    if not new_seen:
        reasons.append("처음 보는 매물 없음 (모두 이전 스캔에서 확인)")
    elif new_muted:
        reasons.append(f"신규 {new_muted}건은 notify_new가 꺼진 조건이라 알리지 않습니다")
    reasons.append("지금 전체 매물을 카톡으로 받으려면: send-report.bat")
    head = f"카카오 미전송: 조건충족 {matched_count}건 중 알림 대상 0건"
    return "\n".join([head, *(f"  - {reason}" for reason in reasons)])


def dedupe_key(listing: Listing) -> tuple:
    """같은 집으로 볼 기준.

    한 단지에서 같은 타입이 같은 층에 같은 가격으로 두 건 올라오면, 중개사가
    둘일 뿐 집은 하나다. 공백은 표기 차이일 뿐이라 지우고 비교한다.
    """
    return (
        listing.condition_id,
        listing.complex_name.replace(" ", ""),
        listing.type_name.replace(" ", ""),
        listing.floor_text.replace(" ", ""),
        listing.price_won,
    )


def _same_building(one: Listing, other: Listing) -> bool:
    """동이 충돌하지 않는가.

    101동 10층과 102동 10층은 같은 가격이어도 다른 집이다. 다만 네이버가 동을
    늘 주지는 않으므로, **양쪽 다 값이 있고 서로 다를 때만** 다른 집으로 본다.
    """
    if not one.building or not other.building:
        return True
    return one.building.replace(" ", "") == other.building.replace(" ", "")


def collapse_duplicates(matched: list[Listing]) -> dict[int, Listing]:
    """중복을 대표에 붙이고, 붙인 것들을 `{pk: 대표}`로 돌려준다.

    대표는 가장 먼저 본 매물이다. 그래야 스캔마다 대표가 바뀌지 않는다.

    이번 스캔에서 본 매물만 다루므로 승격이 저절로 된다 - 대표가 사라지면
    남은 쪽이 자기 묶음의 첫 번째가 되고, 그때 `duplicate_of`가 풀린다.
    """
    buckets_by_key: dict[tuple, list[list[Listing]]] = {}
    for listing in sorted(matched, key=lambda item: (item.first_seen_at, item.listing_id)):
        buckets = buckets_by_key.setdefault(dedupe_key(listing), [])
        for bucket in buckets:
            # 묶음 전체와 견준다. 동이 없는 매물이 다리를 놓아 101동과 102동이
            # 한 묶음이 되는 일을 막는다.
            if all(_same_building(member, listing) for member in bucket):
                bucket.append(listing)
                break
        else:
            buckets.append([listing])

    duplicates: dict[int, Listing] = {}
    for buckets in buckets_by_key.values():
        for bucket in buckets:
            primary, rest = bucket[0], bucket[1:]
            if primary.duplicate_of_id is not None:
                primary.duplicate_of = None
                primary.save(update_fields=("duplicate_of",))
            for other in rest:
                if other.duplicate_of_id != primary.pk:
                    other.duplicate_of = primary
                    other.save(update_fields=("duplicate_of",))
                duplicates[other.pk] = primary
    return duplicates


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
    # 중복을 접은 뒤에 세어야 하므로 숫자가 아니라 매물을 모은다.
    urgent_new: list[Listing] = []
    new_listings: list[Listing] = []
    muted_new: list[Listing] = []
    collected_count = excluded_count = urgent_hit = existing_urgent = 0

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
        listing_values = {
            key: getattr(observation, key)
            for key in (
                "complex_name",
                "building",
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
        if is_new:
            new_listings.append(listing)
        # An urgent alert is useful only when the listing itself is new in this
        # scan.  Existing listings crossing the threshold (or dropping again)
        # remain visible in the report, but no longer generate another Kakao
        # message.  A condition's separate `notify_new` policy still applies
        # to ordinary new listings.
        should_alert = is_urgent and is_new
        should_notify = notify_urgent and not smoke and (
            should_alert or (condition.notify_new and is_new)
        )
        if should_alert:
            urgent_new.append(listing)
        if should_notify:
            alert = AlertDecision(
                listing=listing,
                is_urgent=should_alert,
                is_new=is_new,
            )
            alerts.append(alert)
            if should_alert:
                # Keep the legacy history field accurate for imported data and
                # admin visibility, although repeat-price alerting is retired.
                listing.last_urgent_alert_price_won = listing.price_won
        else:
            existing_urgent += int(is_urgent and not should_alert)
            if is_new and not condition.notify_new:
                muted_new.append(listing)
        listing.save()
        matched.append(listing)

    # 같은 집이 두 건으로 온 경우를 여기서 접는다. 행은 그대로 두고 대표만
    # 세며, 카카오도 한 번만 나간다.
    duplicates = collapse_duplicates(matched)
    if duplicates:
        alerts = [alert for alert in alerts if alert.listing.pk not in duplicates]
        matched = [listing for listing in matched if listing.pk not in duplicates]
    scan.urgent_count = sum(1 for item in urgent_new if item.pk not in duplicates)
    new_seen = sum(1 for item in new_listings if item.pk not in duplicates)
    new_muted = sum(1 for item in muted_new if item.pk not in duplicates)

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
        scan.notification = "smoke 모드: 정규 급매 판정을 건너뛰고 전체 매물 전송 대기"
    else:
        scan.notification = _no_alert_reason(
            failed_conditions=failures,
            matched_count=len(matched),
            urgent_hit=urgent_hit,
            existing_urgent=existing_urgent,
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
