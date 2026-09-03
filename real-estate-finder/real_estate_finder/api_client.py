"""The collector's only outward call: report-site's JSON API.

This process scrapes Naver and hands over what it saw. Everything after that -
which listings match, which are urgent or new, what the report shows, what
KakaoTalk receives - belongs to report-site. So this module carries no domain
knowledge: it moves JSON and turns failures into messages a person can act on.

stdlib `urllib` on purpose; the project has no HTTP dependency and this needs
four requests.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

# A scan POST renders the card image in a headless browser and calls Kakao
# before it answers, so it is minutes, not seconds. The read-only calls are
# short enough that a hang means the server is wedged.
SCAN_TIMEOUT_SECONDS = 600.0
QUICK_TIMEOUT_SECONDS = 20.0


class ApiError(RuntimeError):
    """A request the server refused, or could not be made at all."""

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
    """Read the shared root .env, then report-site's own.

    `FINDER_API_TOKEN` is generated in `report-site/.env` and read straight from
    there rather than copied, so the two sides cannot drift out of sync.
    """
    _load_env_file(ROOT_DIR / ".env")
    _load_env_file(ROOT_DIR / "report-site" / ".env")


class ReportSiteClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        _load_env()
        self.base_url = (
            base_url or os.environ.get("FINDER_API_BASE", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.token = token if token is not None else os.environ.get("FINDER_API_TOKEN", "").strip()
        if not self.token:
            raise ApiError(
                "FINDER_API_TOKEN을 찾을 수 없습니다.\n"
                f"{ROOT_DIR / 'report-site' / '.env'}에 FINDER_API_TOKEN이 있는지 확인하세요."
            )

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None, timeout: float
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "real-estate-finder",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
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
        """Surface the server's own message; it explains far more than the code."""
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
            detail += f"\n{ROOT_DIR / 'report-site' / '.env'}의 FINDER_API_TOKEN을 확인하세요."
        return ApiError(
            f"리포트 서버가 요청을 거부했습니다 ({exc.code}): {url}\n{detail or exc.reason}",
            status=exc.code,
            code=code,
        )

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health/", None, QUICK_TIMEOUT_SECONDS)

    def conditions(self) -> dict[str, Any]:
        return self._request("GET", "/api/conditions/", None, QUICK_TIMEOUT_SECONDS)

    def post_scan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/scans/", payload, SCAN_TIMEOUT_SECONDS)

    def send_digest(self) -> dict[str, Any]:
        return self._request("POST", "/api/digest/", {}, SCAN_TIMEOUT_SECONDS)
