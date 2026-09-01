"""Small shared helpers implemented with the Python standard library only."""

from __future__ import annotations

import json
import os
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
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"message": body}
        return error.code, payload
