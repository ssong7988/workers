"""파싱한 명세서를 리포트 서버로 넘긴다.

역할 경계는 저장소의 다른 수집기와 같다 — **여기는 수집만 한다.** 분류 규칙,
집계, 화면, 카카오 요약은 전부 report-site(Django+PostgreSQL)가 소유하므로,
이 모듈이 아는 것은 엔드포인트 하나와 토큰 하나뿐이다.

표준 라이브러리만 쓴다. `kakao-notifier`가 외부 패키지 없이 도는 관례에 맞고,
JSON 한 통을 POST하는 데 HTTP 클라이언트를 들여올 이유가 없다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .models import Statement


TIMEOUT_SECONDS = 60


class PushError(RuntimeError):
    """서버가 명세서를 받지 못했을 때."""


@dataclass
class PushResult:
    billing_month: str
    created: bool
    transactions: int
    message: str


def _request(url: str, token: str, payload: dict | None, method: str) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "spending-analyzer",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            message = json.loads(detail).get("error", detail)
        except json.JSONDecodeError:
            message = detail
        # 서버가 소계 불일치를 400으로 거절한다. 그 문장을 그대로 올려야
        # 무엇이 어긋났는지 여기서 읽을 수 있다.
        raise PushError(f"서버가 거절했습니다 (HTTP {exc.code}): {message}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PushError(
            f"리포트 서버에 접속하지 못했습니다: {exc}\n"
            "  run-site.bat이 떠 있는지, SPENDING_API_URL이 맞는지 확인하세요."
        ) from exc


def stored_months(base_url: str, token: str) -> list[str]:
    """서버가 이미 들고 있는 청구월. 다시 파싱할 필요가 없는 달을 알려준다."""
    payload = _request(f"{base_url.rstrip('/')}/health/", token, None, "GET")
    return list(payload.get("months", []))


def push_statement(base_url: str, token: str, statement: Statement) -> PushResult:
    """명세서 한 통을 보낸다. 같은 청구월이면 서버가 그 달을 통째로 바꾼다."""
    payload = _request(
        f"{base_url.rstrip('/')}/statements/", token, statement.to_dict(), "POST"
    )
    return PushResult(
        billing_month=payload.get("billing_month", statement.billing_month),
        created=bool(payload.get("created")),
        transactions=int(payload.get("transactions", 0)),
        message=payload.get("message", ""),
    )
