"""Send a text or image message to the authenticated user's KakaoTalk My Chatroom."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from common import load_env, post_form_json, post_multipart_json


BASE_DIR = Path(__file__).resolve().parent
load_env(BASE_DIR / ".env")

REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "").strip()
CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
TOKEN_FILE = Path(os.environ.get("KAKAO_TOKEN_FILE", "data/kakao-token.json"))
REPORT_URL = os.environ.get(
    "KAKAO_REPORT_URL",
    "https://my-property-report-20260902.ssong7988.chatgpt.site",
).strip()
# Fallback when the image upload API is unavailable: a public base URL that
# already serves the rendered card (e.g. the hosted report site).
IMAGE_BASE_URL = os.environ.get("KAKAO_IMAGE_BASE_URL", "").strip()
if not TOKEN_FILE.is_absolute():
    TOKEN_FILE = BASE_DIR / TOKEN_FILE

MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
IMAGE_UPLOAD_URL = "https://kapi.kakao.com/v2/api/talk/message/image/upload"
# Feed templates cap the title and description; the image carries the detail.
CAPTION_LIMIT = 180
IMAGE_BUTTON_TITLE = "원본 이미지 보기"
TEXT_BUTTON_TITLE = "전체 매물 보기"


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


def _with_token_retry(call) -> dict:
    """Run `call(access_token)`, refreshing the token once on a 401."""
    if not REST_API_KEY or not CLIENT_SECRET:
        raise RuntimeError(".env의 REST API 키와 클라이언트 시크릿을 확인하세요.")

    tokens = load_tokens()
    status, payload = call(tokens["access_token"])
    if status == 401:
        tokens = refresh_access_token(tokens)
        status, payload = call(tokens["access_token"])
    if status != 200:
        raise RuntimeError(f"카카오 API 호출 실패 ({status}): {payload}")
    return payload


def _send_template(template: dict) -> None:
    payload = _with_token_retry(
        lambda access_token: post_form_json(
            MEMO_SEND_URL,
            {"template_object": json.dumps(template, ensure_ascii=False)},
            {"Authorization": f"Bearer {access_token}"},
        )
    )
    if payload.get("result_code") != 0:
        raise RuntimeError(f"카카오 메시지 전송 실패: {payload}")


def _https(url: str) -> str:
    """Kakao returns upload URLs over http; links are registered per https domain."""
    return "https://" + url[len("http://") :] if url.startswith("http://") else url


def _image_parts(image_path: Path) -> tuple[str, bytes, str]:
    """Return the ASCII filename, bytes, and content type for an upload."""
    content_type = (
        "image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    )
    filename = "card.jpg" if content_type == "image/jpeg" else "card.png"
    return filename, image_path.read_bytes(), content_type


def send_to_me(
    message: str, link_url: str = REPORT_URL
) -> None:
    if len(message) > 200:
        raise ValueError("카카오 기본 텍스트 메시지는 200자 이하여야 합니다.")

    _send_template(
        {
            "object_type": "text",
            "text": message,
            "link": {
                "web_url": link_url,
                "mobile_web_url": link_url,
            },
            "button_title": TEXT_BUTTON_TITLE,
        }
    )


def probe_image_upload(image_path: Path) -> tuple[int, dict]:
    """Call the image upload API and return its raw response, errors included.

    Used to confirm the endpoint and app permissions before wiring the card
    pipeline to it.
    """
    filename, content, content_type = _image_parts(image_path)
    tokens = load_tokens()
    return post_multipart_json(
        IMAGE_UPLOAD_URL,
        {"file": (filename, content, content_type)},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )


def upload_image(image_path: Path) -> dict:
    """Upload an image and return its hosted `original` info (url/width/height)."""
    filename, content, content_type = _image_parts(image_path)
    payload = _with_token_retry(
        lambda access_token: post_multipart_json(
            IMAGE_UPLOAD_URL,
            {"file": (filename, content, content_type)},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    )
    original = payload.get("infos", {}).get("original") if isinstance(payload, dict) else None
    if not isinstance(original, dict) or not original.get("url"):
        raise RuntimeError(f"이미지 업로드 응답을 해석하지 못했습니다: {payload}")
    return {**original, "url": _https(original["url"])}


def send_image_to_me(
    image_url: str,
    title: str,
    description: str,
    link_url: str | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
) -> None:
    """Send the card as a feed message.

    With no `link_url` the card and its button open the full-resolution image
    itself, which is usually what you want — the card in the chat is scaled down.
    """
    target = link_url or image_url
    link = {"web_url": target, "mobile_web_url": target}
    content = {
        "title": title[:CAPTION_LIMIT],
        "description": description[:CAPTION_LIMIT],
        "image_url": image_url,
        "link": link,
    }
    if image_width:
        content["image_width"] = image_width
    if image_height:
        content["image_height"] = image_height
    button_title = TEXT_BUTTON_TITLE if link_url else IMAGE_BUTTON_TITLE
    _send_template(
        {
            "object_type": "feed",
            "content": content,
            "buttons": [{"title": button_title, "link": link}],
        }
    )


def send_card_to_me(
    image_path: Path | str,
    title: str,
    description: str,
    link_url: str | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
) -> None:
    """Upload the rendered card and send it as a feed message.

    By default the message links to the uploaded original so tapping it opens the
    card at full resolution. Falls back to a public URL under
    KAKAO_IMAGE_BASE_URL when the upload API is unavailable.

    Note: whatever domain ends up in the link must be registered under
    앱 > 제품 링크 관리 > 웹 도메인, or Kakao silently swaps it for the app's
    default domain.
    """
    path = Path(image_path)
    try:
        original = upload_image(path)
        image_url = original["url"]
        # The upload response reports the stored dimensions; prefer them so the
        # feed template renders at the right aspect ratio.
        image_width = original.get("width") or image_width
        image_height = original.get("height") or image_height
    except Exception as exc:
        if not IMAGE_BASE_URL:
            raise
        image_url = f"{IMAGE_BASE_URL.rstrip('/')}/{path.name}"
        print(f"이미지 업로드 실패, 공개 URL로 대체합니다 ({exc}): {image_url}")
    send_image_to_me(image_url, title, description, link_url, image_width, image_height)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "message", nargs="?", default="자동화 프로그램 카카오톡 연결 테스트입니다. ✅"
    )
    parser.add_argument(
        "--link",
        default=None,
        help="버튼이 열 주소 (--image에서 생략하면 업로드된 원본 이미지로 연결)",
    )
    parser.add_argument(
        "--image", type=Path, help="이미지 카드를 업로드해 feed 메시지로 전송"
    )
    parser.add_argument(
        "--upload-probe",
        type=Path,
        help="이미지 업로드 API만 호출하고 응답을 그대로 출력 (권한 확인용)",
    )
    parser.add_argument("--description", default="", help="--image 사용 시 부제")
    args = parser.parse_args()

    if args.upload_probe:
        status, payload = probe_image_upload(args.upload_probe)
        print(f"status: {status}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.image:
        send_card_to_me(args.image, args.message, args.description, args.link)
        print("카카오톡 '나와의 채팅'으로 이미지 카드를 보냈습니다.")
        return

    send_to_me(args.message, args.link or REPORT_URL)
    print("카카오톡 '나와의 채팅'으로 메시지를 보냈습니다.")


if __name__ == "__main__":
    main()
