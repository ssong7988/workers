"""주식 수집기 전용 JSON 경계.

부동산 `api/`와 같은 이유로 DRF를 쓰지 않는다 - 엔드포인트가 둘뿐이고,
검증을 명시적으로 적어두는 편이 읽기 쉽다. 토큰만 다르다
(`STOCK_API_TOKEN`): 사이트가 Funnel로 인터넷에 열려 있어 이 경로도 밖에서
닿고, 수집기 하나가 털렸을 때 다른 도메인까지 열리면 안 된다.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import DatabaseError, transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from api.auth import bearer_required_for

from .importing import (
    PortfolioImportError,
    account_status,
    latest_complete_date,
    record_import_run,
)
from .models import (
    HableAccountDailyMetric,
    Instrument,
    InvestmentAccount,
    UNCLASSIFIED_ASSET_CLASS_ID,
)
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
def performance_history(request: HttpRequest) -> JsonResponse:
    """[0354] 계좌별 일간 기록을 멱등하게 저장한다."""
    if request.method != "POST":
        return _method_not_allowed("POST")
    try:
        payload = _read_json(request)
        accounts = payload.get("accounts")
        if not isinstance(accounts, list) or not accounts:
            raise ValueError("accounts는 비어 있지 않은 배열이어야 합니다.")
        saved = 0
        with transaction.atomic():
            for block in accounts:
                if not isinstance(block, dict):
                    raise ValueError("계좌 항목은 객체여야 합니다.")
                number = str(block.get("account_number") or "").strip()
                if not number or "*" not in number:
                    raise ValueError("마스킹 계좌번호가 필요합니다.")
                matches = list(
                    InvestmentAccount.objects.filter(masked_number=number, active=True)
                )
                if len(matches) != 1:
                    raise ValueError(f"등록된 활성 계좌 하나와 일치하지 않습니다: {number}")
                rows = block.get("rows")
                if not isinstance(rows, list):
                    raise ValueError(f"rows가 배열이 아닙니다: {number}")
                first_day = min((date.fromisoformat(str(row["as_of"])) for row in rows), default=None)
                for row in rows:
                    as_of = date.fromisoformat(str(row["as_of"]))
                    values = {
                        key: Decimal(str(row[key]))
                        for key in ("market_value", "deposit", "withdrawal", "investment_pl", "daily_return", "cumulative_return")
                    }
                    if any(not value.is_finite() for value in values.values()):
                        raise ValueError("성과 값은 유한한 숫자여야 합니다.")
                    # [0354] 조회 첫날은 기준점이라 수익률·입출금을 0으로 준다.
                    # 범위를 옮겨 재조회했을 때 기존 실제 일간 기록을 0으로 덮지 않는다.
                    if as_of == first_day and HableAccountDailyMetric.objects.filter(
                        account=matches[0], as_of=as_of
                    ).exists():
                        continue
                    HableAccountDailyMetric.objects.update_or_create(
                        account=matches[0], as_of=as_of,
                        defaults={
                            "market_value": values["market_value"],
                            "deposit": values["deposit"],
                            "withdrawal": values["withdrawal"],
                            "investment_pl": values["investment_pl"],
                            "daily_return": values["daily_return"],
                            "account_cumulative_return": values["cumulative_return"],
                        },
                    )
                    saved += 1
        return JsonResponse({"saved": saved}, status=201)
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        return _error(str(exc), "invalid_request", 400)
    except DatabaseError:
        return _error("과거 성과를 저장할 수 없습니다.", "database_error", 503)


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
