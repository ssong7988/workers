"""Perform the one-time Kakao OAuth login and save the user tokens locally."""

from __future__ import annotations

import json
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from common import load_env, post_form_json


load_env()

REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "").strip()
CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.environ.get(
    "KAKAO_REDIRECT_URI", "http://localhost:4000/oauth/callback"
).strip()
TOKEN_FILE = Path(os.environ.get("KAKAO_TOKEN_FILE", "data/kakao-token.json"))


def require_settings() -> None:
    if not REST_API_KEY or "여기에_" in REST_API_KEY:
        raise SystemExit(".env에 KAKAO_REST_API_KEY를 입력하세요.")
    if not CLIENT_SECRET or "여기에_" in CLIENT_SECRET:
        raise SystemExit(".env에 KAKAO_CLIENT_SECRET을 입력하세요.")


def exchange_code(code: str) -> dict:
    status, payload = post_form_json(
        "https://kauth.kakao.com/oauth/token",
        {
            "grant_type": "authorization_code",
            "client_id": REST_API_KEY,
            "redirect_uri": REDIRECT_URI,
            "code": code,
            "client_secret": CLIENT_SECRET,
        },
    )
    if status != 200:
        raise RuntimeError(f"토큰 발급 실패 ({status}): {payload}")
    return payload


def save_tokens(tokens: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    require_settings()

    parsed_redirect = urlparse(REDIRECT_URI)
    if parsed_redirect.hostname not in {"localhost", "127.0.0.1"}:
        raise SystemExit("로컬 인증에서는 redirect URI의 호스트가 localhost여야 합니다.")

    state = secrets.token_urlsafe(24)
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            query = parse_qs(urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                result["error"] = "OAuth state가 일치하지 않습니다."
                status, body = 400, "인증 요청이 올바르지 않습니다."
            elif "error" in query:
                result["error"] = query.get("error_description", query["error"])[0]
                status, body = 400, "카카오 로그인이 취소되거나 실패했습니다."
            elif "code" not in query:
                result["error"] = "인가 코드가 없습니다."
                status, body = 400, "인가 코드가 없습니다."
            else:
                result["code"] = query["code"][0]
                status, body = 200, "인증 완료. 이 창을 닫고 터미널로 돌아가세요."

            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *args: object) -> None:
            return

    port = parsed_redirect.port or 80
    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    auth_url = "https://kauth.kakao.com/oauth/authorize?" + urlencode(
        {
            "response_type": "code",
            "client_id": REST_API_KEY,
            "redirect_uri": REDIRECT_URI,
            "scope": "talk_message",
            "state": state,
        }
    )

    print("브라우저에서 카카오 로그인과 메시지 권한에 동의하세요.")
    print(f"브라우저가 열리지 않으면 다음 주소를 여세요:\n{auth_url}\n")
    threading.Timer(0.5, lambda: webbrowser.open(auth_url)).start()
    server.handle_request()
    server.server_close()

    if "error" in result:
        raise SystemExit(f"인증 실패: {result['error']}")

    tokens = exchange_code(result["code"])
    save_tokens(tokens)
    print(f"인증 성공: 토큰을 {TOKEN_FILE}에 저장했습니다.")


if __name__ == "__main__":
    main()
