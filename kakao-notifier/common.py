"""Small shared helpers implemented with the Python standard library only."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def load_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _read_json_response(request: Request, timeout: int) -> tuple[int, dict]:
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"message": body}
        return error.code, payload


def post_form_json(
    url: str, data: dict[str, str], headers: dict[str, str] | None = None
) -> tuple[int, dict]:
    request_headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        **(headers or {}),
    }
    request = Request(
        url,
        data=urlencode(data).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    return _read_json_response(request, 20)


def post_multipart_json(
    url: str,
    files: dict[str, tuple[str, bytes, str]],
    fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[int, dict]:
    """POST multipart/form-data without leaving the standard library.

    `files` maps a form field name to `(filename, content, content_type)`.
    Filenames stay ASCII so the simple Content-Disposition form is valid and we
    never need RFC 2231 encoding.
    """
    boundary = "----kakaoform" + uuid.uuid4().hex
    body = bytearray()
    for name, value in (fields or {}).items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")
    for name, (filename, content, content_type) in files.items():
        if not filename.isascii():
            raise ValueError(f"업로드 파일명은 ASCII여야 합니다: {filename}")
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        body += content + b"\r\n"
    body += f"--{boundary}--\r\n".encode("ascii")

    request = Request(
        url,
        data=bytes(body),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            **(headers or {}),
        },
        method="POST",
    )
    return _read_json_response(request, timeout)
