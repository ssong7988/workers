"""Small JSON boundary used by the collection-only process."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from properties.models import GlobalRule, SearchCondition
from properties.scanning import ScanDecision, record_scan

from .auth import bearer_required


def _error(message: str, code: str, status: int) -> JsonResponse:
    return JsonResponse({"error": message, "code": code}, status=status)


def _method_not_allowed(*allowed: str) -> JsonResponse:
    response = _error("허용되지 않은 요청 방식입니다.", "method_not_allowed", 405)
    response["Allow"] = ", ".join(allowed)
    return response


def _read_json(request: HttpRequest) -> dict[str, Any]:
    if request.content_type != "application/json":
        raise ValueError("Content-Type은 application/json이어야 합니다.")
    try:
        payload = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("요청 본문이 올바른 JSON이 아닙니다.") from exc
    if not isinstance(payload, dict):
        raise ValueError("요청 본문은 JSON 객체여야 합니다.")
    return payload


def _decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _condition_payload(condition: SearchCondition) -> dict[str, Any]:
    return {
        "id": condition.pk,
        "name": condition.name,
        "complex_names": condition.complex_names,
        "search_url": condition.search_url,
        "exclusive_area_m2": _decimal(condition.exclusive_area_m2),
        "exclusive_area_min_m2": _decimal(condition.exclusive_area_min_m2),
        "exclusive_area_max_m2": _decimal(condition.exclusive_area_max_m2),
        "allowed_types": condition.allowed_types,
        "max_price_won": condition.max_price_won,
        "urgent_price_won": condition.urgent_price_won,
        "notify_new": condition.notify_new,
        "apply_low_floor_discount": condition.apply_low_floor_discount,
    }


def _scan_payload(decision: ScanDecision) -> dict[str, Any]:
    scan = decision.scan
    return {
        "scan": {
            "id": scan.pk,
            "started_at": scan.started_at.isoformat(),
            "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
            "success": scan.success,
            "successful_conditions": scan.successful_conditions,
            "failed_conditions": scan.failed_conditions,
            "collected_count": scan.collected_count,
            "matched_count": scan.matched_count,
            "urgent_count": scan.urgent_count,
            "excluded_count": scan.excluded_count,
            "notification": scan.notification,
        },
        "alerts": [
            {
                "condition_id": alert.listing.condition_id,
                "listing_id": alert.listing.listing_id,
                "is_urgent": alert.is_urgent,
                "is_new": alert.is_new,
            }
            for alert in decision.alerts
        ],
    }


@bearer_required
def health(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return _method_not_allowed("GET")
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return _error("데이터베이스에 연결할 수 없습니다.", "database_unavailable", 503)
    return JsonResponse({"status": "ok", "database": "ok"})


@bearer_required
def conditions(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return _method_not_allowed("GET")
    try:
        rule = GlobalRule.objects.get(pk=1)
        active = SearchCondition.objects.filter(enabled=True).order_by("name")
        return JsonResponse(
            {
                "global_rule": {
                    "trade_type": rule.trade_type,
                    "low_floor_numeric_floors": rule.low_floor_numeric_floors,
                    "low_floor_labels": rule.low_floor_labels,
                    "low_floor_price_discount_won": rule.low_floor_price_discount_won,
                    "timezone": rule.timezone,
                    "digest_weekdays": rule.digest_weekdays,
                    "digest_hour": rule.digest_hour,
                },
                "conditions": [_condition_payload(item) for item in active],
            }
        )
    except GlobalRule.DoesNotExist:
        return _error("공통 규칙이 설정되지 않았습니다.", "configuration_missing", 503)
    except DatabaseError:
        return _error("검색 조건을 조회할 수 없습니다.", "database_error", 503)


@csrf_exempt
@bearer_required
def scans(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed("POST")
    try:
        payload = _read_json(request)
        observations = payload.get("observations")
        successful = payload.get("successful_conditions")
        failures = payload.get("failed_conditions", {})
        notify_urgent = payload.get("notify_urgent", True)
        smoke = payload.get("smoke", False)
        if not isinstance(observations, list):
            raise ValueError("observations는 배열이어야 합니다.")
        if not all(isinstance(item, dict) for item in observations):
            raise ValueError("observations의 각 항목은 JSON 객체여야 합니다.")
        if not isinstance(successful, list) or not all(
            isinstance(item, str) for item in successful
        ):
            raise ValueError("successful_conditions는 문자열 배열이어야 합니다.")
        if not isinstance(failures, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in failures.items()
        ):
            raise ValueError("failed_conditions는 문자열 키와 값의 객체여야 합니다.")
        overlap = set(successful) & set(failures)
        if overlap:
            raise ValueError(
                "성공 조건과 실패 조건은 겹칠 수 없습니다: "
                f"{', '.join(sorted(overlap))}"
            )
        if not isinstance(notify_urgent, bool) or not isinstance(smoke, bool):
            raise ValueError("notify_urgent와 smoke는 boolean이어야 합니다.")
        if notify_urgent or smoke:
            return _error(
                "카카오 전송은 아직 Django에 연결되지 않았습니다. "
                "현재는 notify_urgent=false인 일반 스캔 기록만 지원합니다.",
                "notification_not_available",
                501,
            )
        decision = record_scan(
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            observations=observations,
            successful_conditions=successful,
            failed_conditions=failures,
            notify_urgent=False,
            smoke=False,
        )
    except ValueError as exc:
        return _error(str(exc), "invalid_request", 400)
    except DatabaseError:
        return _error("스캔을 저장할 수 없습니다.", "database_error", 503)
    return JsonResponse(_scan_payload(decision), status=201)


@csrf_exempt
@bearer_required
def digest(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed("POST")
    return _error(
        "카카오 전체 보고는 아직 Django에 연결되지 않았습니다.",
        "notification_not_available",
        501,
    )
