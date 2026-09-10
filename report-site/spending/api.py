"""수집기만 쓰는 JSON 경계.

`spending-analyzer/`가 이용대금명세서를 열어 정규화한 거래를 여기로 넘긴다.
분류·집계·카카오는 전부 서버가 하므로 수집기는 이 엔드포인트만 알면 된다.
"""

from __future__ import annotations

import json

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from api.auth import bearer_required_for

from .analysis import latest_statement
from .ingest import IngestError, ingest_statement
from .models import Statement

spending_bearer_required = bearer_required_for("SPENDING_API_TOKEN")


def _error(message: str, code: str, status: int) -> JsonResponse:
    return JsonResponse({"error": message, "code": code}, status=status)


@csrf_exempt
@spending_bearer_required
def health(request: HttpRequest) -> JsonResponse:
    """수집기가 무엇을 이미 보냈는지 확인하는 자리.

    이미 있는 달을 다시 파싱하지 않도록, 저장된 청구월을 그대로 알려준다.
    """
    if request.method != "GET":
        response = _error("허용되지 않은 요청 방식입니다.", "method_not_allowed", 405)
        response["Allow"] = "GET"
        return response
    latest = latest_statement()
    return JsonResponse(
        {
            "ok": True,
            "months": list(
                Statement.objects.order_by("billing_month").values_list(
                    "billing_month", flat=True
                )
            ),
            "latest": latest.billing_month if latest else None,
        }
    )


@csrf_exempt
@spending_bearer_required
def statements(request: HttpRequest) -> JsonResponse:
    """명세서 한 통을 저장한다. 같은 청구월이 오면 그 달을 통째로 바꾼다."""
    if request.method != "POST":
        response = _error("허용되지 않은 요청 방식입니다.", "method_not_allowed", 405)
        response["Allow"] = "POST"
        return response
    if request.content_type != "application/json":
        return _error("Content-Type은 application/json이어야 합니다.", "bad_content_type", 415)
    try:
        payload = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("요청 본문이 올바른 JSON이 아닙니다.", "bad_json", 400)
    if not isinstance(payload, dict):
        return _error("요청 본문은 JSON 객체여야 합니다.", "bad_json", 400)

    try:
        result = ingest_statement(payload)
    except IngestError as exc:
        # 소계와 어긋난 명세서는 400이다. 수집기가 조용히 성공했다고 믿으면
        # 부분만 저장된 달이 그대로 남는다.
        return _error(str(exc), "rejected", 400)

    return JsonResponse(
        {
            "ok": True,
            "billing_month": result.billing_month,
            "created": result.created,
            "transactions": result.transaction_count,
            "total_billed_won": result.total_billed_won,
            "replaced": result.replaced_count,
            "message": result.describe(),
        },
        status=201 if result.created else 200,
    )
