"""Send a text message to the authenticated user's KakaoTalk My Chatroom."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from common import load_env, post_form_json


BASE_DIR = Path(__file__).resolve().parent
load_env(BASE_DIR / ".env")

REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "").strip()
CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
TOKEN_FILE = Path(os.environ.get("KAKAO_TOKEN_FILE", "data/kakao-token.json"))
if not TOKEN_FILE.is_absolute():
    TOKEN_FILE = BASE_DIR / TOKEN_FILE


def load_tokens() -> dict:
    if not TOKEN_FILE.exists():
        raise RuntimeError("토큰 파일이 없습니다. 먼저 `python auth.py`를 실행하세요.")
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))


def save_tokens(tokens: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def refresh_access_token(tokens: dict) -> dict:
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("리프레시 토큰이 없습니다. `python auth.py`를 다시 실행하세요.")

    status, refreshed = post_form_json(
        "https://kauth.kakao.com/oauth/token",
        {
            "grant_type": "refresh_token",
            "client_id": REST_API_KEY,
            "refresh_token": refresh_token,
            "client_secret": CLIENT_SECRET,
        },
    )
    if status != 200:
        raise RuntimeError(f"토큰 갱신 실패 ({status}): {refreshed}")

    tokens["access_token"] = refreshed["access_token"]
    tokens["expires_in"] = refreshed.get("expires_in")
    if refreshed.get("refresh_token"):
        tokens["refresh_token"] = refreshed["refresh_token"]
        tokens["refresh_token_expires_in"] = refreshed.get(
            "refresh_token_expires_in"
        )
    save_tokens(tokens)
    return tokens


def _send(access_token: str, message: str, link_url: str) -> tuple[int, dict]:
    template = {
        "object_type": "text",
        "text": message,
        "link": {
            "web_url": link_url,
            "mobile_web_url": link_url,
        },
        "button_title": "네이버 부동산 열기",
    }
    return post_form_json(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        {"template_object": json.dumps(template, ensure_ascii=False)},
        {"Authorization": f"Bearer {access_token}"},
    )


def send_to_me(
    message: str, link_url: str = "https://fin.land.naver.com/"
) -> None:
    if not REST_API_KEY or not CLIENT_SECRET:
        raise RuntimeError(".env의 REST API 키와 클라이언트 시크릿을 확인하세요.")

    tokens = load_tokens()
    if len(message) > 200:
        raise ValueError("카카오 기본 텍스트 메시지는 200자 이하여야 합니다.")

    status, payload = _send(tokens["access_token"], message, link_url)

    if status == 401:
        tokens = refresh_access_token(tokens)
        status, payload = _send(tokens["access_token"], message, link_url)

    if status != 200:
        raise RuntimeError(f"카카오 메시지 전송 실패 ({status}): {payload}")
    if payload.get("result_code") != 0:
        raise RuntimeError(f"카카오 메시지 전송 실패: {payload}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "message", nargs="?", default="자동화 프로그램 카카오톡 연결 테스트입니다. ✅"
    )
    parser.add_argument("--link", default="https://fin.land.naver.com/")
    args = parser.parse_args()
    send_to_me(args.message, args.link)
    print("카카오톡 '나와의 채팅'으로 메시지를 보냈습니다.")


if __name__ == "__main__":
    main()
