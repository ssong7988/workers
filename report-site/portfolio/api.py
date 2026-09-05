"""주식 수집기 전용 JSON 경계.

부동산 `api/`와 같은 이유로 DRF를 쓰지 않는다 - 엔드포인트가 둘뿐이고,
검증을 명시적으로 적어두는 편이 읽기 쉽다. 토큰만 다르다
(`STOCK_API_TOKEN`): 사이트가 Funnel로 인터넷에 열려 있어 이 경로도 밖에서
닿고, 수집기 하나가 털렸을 때 다른 도메인까지 열리면 안 된다.
"""

from __future__ import annotations

import json
from typing import Any

from django.db import DatabaseError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from api.auth import bearer_required_for

from .importing import (
    PortfolioImportError,
    account_status,
    latest_complete_date,
    record_import_run,
)
from .models import UNCLASSIFIED_ASSET_CLASS_ID, Instrument
from .performance import rebuild_metrics


stock_bearer_required = bearer_required_for("STOCK_API_TOKEN")


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


def _unclassified_count() -> int:
    return Instrument.objects.filter(asset_class_id=UNCLASSIFIED_ASSET_CLASS_ID).count()


@csrf_exempt
@stock_bearer_required
def import_runs(request: HttpRequest) -> JsonResponse:
    """계좌 하나의 자료 하나를 받는다.

    수집기는 계좌·자료별로 여러 번 부른다. 그날의 완전 스냅샷이 성립하는지는
    매번 응답의 `complete_as_of`로 알려준다 - 마지막 계좌가 들어온 순간
    성과가 다시 계산돼 있어야 카카오가 최신값을 붙일 수 있다.
    """
    if request.method != "POST":
        return _method_not_allowed("POST")
    try:
        payload = _read_json(request)
    except ValueError as exc:
        return _error(str(exc), "invalid_request", 400)

    before = latest_complete_date()
    try:
        result = record_import_run(payload)
    except PortfolioImportError as exc:
        return _error(str(exc), "invalid_request", 400)
    except DatabaseError:
        return _error("수집 결과를 저장할 수 없습니다.", "database_error", 503)

    after = latest_complete_date()
    recomputed = 0
    if after is not None and after != before:
        try:
            recomputed = rebuild_metrics()
        except DatabaseError:
            return _error("성과를 계산할 수 없습니다.", "database_error", 503)

    return JsonResponse(
        {
            "import_run": {
                "id": result.run.pk,
                "as_of": result.run.as_of.isoformat(),
                "account": result.run.account_id,
                "document_type": result.run.document_type,
                "status": result.run.status,
                "row_count": result.run.row_count,
            },
            "duplicate": result.duplicate,
            "positions": result.position_count,
            "cash_flows": result.cash_flow_count,
            "new_instruments": result.new_instruments,
            "complete_as_of": after.isoformat() if after else None,
            "metrics_days": recomputed,
        },
        status=200 if result.duplicate else 201,
    )


@stock_bearer_required
def status(request: HttpRequest) -> JsonResponse:
    """마지막 완전 수집일, 계좌별 성공 여부, 미분류 종목 수."""
    if request.method != "GET":
        return _method_not_allowed("GET")
    try:
        as_of = latest_complete_date()
        return JsonResponse(
            {
                "complete_as_of": as_of.isoformat() if as_of else None,
                "accounts": account_status(as_of),
                "unclassified_instruments": _unclassified_count(),
            }
        )
    except DatabaseError:
        return _error("상태를 조회할 수 없습니다.", "database_error", 503)
