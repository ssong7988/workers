"""수집기의 유일한 바깥 호출: report-site의 주식 API.

이 프로세스는 화면에서 본 것을 넘기는 일만 한다. 자산분류, 목표 비중, 국민연금
비교, 수익률과 MDD, 카카오 전송은 전부 report-site가 소유한다. 그래서 여기에는
도메인 지식이 없다 - JSON을 옮기고, 실패를 사람이 고칠 수 있는 문장으로 바꾼다.

부동산 수집기와 같은 이유로 stdlib `urllib`을 쓴다. 요청이 두 종류뿐이다.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORT_SITE_ENV = ROOT_DIR / "report-site" / ".env"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 60.0


class ApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _load_env() -> None:
    """루트 .env를 먼저, 그다음 report-site의 .env를 읽는다.

    `STOCK_API_TOKEN`과 `REPORT_PATH_TOKEN`은 report-site에서 만들어지므로
    복사하지 않고 그 파일에서 그대로 읽는다. 두 쪽이 어긋날 수가 없다.
    """
    _load_env_file(ROOT_DIR / ".env")
    _load_env_file(REPORT_SITE_ENV)


class StockApiClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        _load_env()
        self.base_url = (
            base_url or os.environ.get("STOCK_API_BASE", DEFAULT_BASE_URL)
        ).rstrip("/")
        path_token = os.environ.get("REPORT_PATH_TOKEN", "").strip().strip("/")
        self.prefix = f"/{path_token}/stock/api" if path_token else "/stock/api"
        self.token = (
            token if token is not None else os.environ.get("STOCK_API_TOKEN", "").strip()
        )
        if not self.token:
            raise ApiError(
                "STOCK_API_TOKEN을 찾을 수 없습니다.\n"
                f"{REPORT_SITE_ENV}에 STOCK_API_TOKEN을 넣고 리포트 서버를 다시 시작하세요."
            )

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        url = f"{self.base_url}{self.prefix}{path}"
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "stock-importer",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return self._decode(response.read())
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc, url) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError(
                f"리포트 서버에 연결하지 못했습니다: {url}\n"
                "report-site\\run-site.bat이 실행 중인지 확인하세요.\n"
                f"원인: {exc}"
            ) from exc

    @staticmethod
    def _decode(raw: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(f"서버 응답이 JSON이 아닙니다: {raw[:200]!r}") from exc
        if not isinstance(payload, dict):
            raise ApiError(f"서버 응답이 JSON 객체가 아닙니다: {payload!r}")
        return payload

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError, url: str) -> ApiError:
        detail = ""
        code = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            if isinstance(payload, dict):
                detail = str(payload.get("error", ""))
                code = str(payload.get("code", ""))
        except Exception:
            pass
        if exc.code == 401:
            detail = detail or "인증에 실패했습니다."
            detail += f"\n{REPORT_SITE_ENV}의 STOCK_API_TOKEN을 확인하세요."
        if code == "token_not_configured":
            detail += (
                f"\n{REPORT_SITE_ENV}에 STOCK_API_TOKEN을 넣고 "
                "report-site\\run-site.bat을 다시 시작하세요."
            )
        return ApiError(
            f"리포트 서버가 요청을 거부했습니다 ({exc.code}): {url}\n{detail or exc.reason}",
            status=exc.code,
            code=code,
        )

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/status/", None)

    def post_import_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/import-runs/", payload)

    def post_performance_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/performance-history/", payload)
