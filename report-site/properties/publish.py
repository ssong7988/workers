"""Check whether the public report serves the expected database state."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlparse


VERIFY_ATTEMPTS = 4
VERIFY_INTERVAL_SECONDS = 6.0
_OBSERVED_AT = re.compile(r'data-observed-at="([^"]+)"')


def is_public_report_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname not in {
        None,
        "localhost",
        "127.0.0.1",
        "::1",
    }


def _fetch(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "property-report"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def live_observed_at(report_url: str, timeout: float = 20.0) -> str | None:
    if not is_public_report_url(report_url):
        return None
    try:
        html = _fetch(report_url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    match = _OBSERVED_AT.search(html)
    return match.group(1) if match else None


def describe_live(report_url: str, timeout: float = 20.0) -> str:
    if not is_public_report_url(report_url):
        return "공개 HTTPS 리포트 주소가 설정되지 않았습니다"
    try:
        html = _fetch(report_url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return f"사이트에 접속하지 못했습니다 ({exc})"
    match = _OBSERVED_AT.search(html)
    return match.group(1) if match else "리포트 서버 응답에 기준 시각이 없습니다"


def _same_moment(left: str, right: str) -> bool:
    if left == right:
        return True
    try:
        return datetime.fromisoformat(left) == datetime.fromisoformat(right)
    except ValueError:
        return False


def is_live(expected_observed_at: str, report_url: str, *, attempts: int = 1) -> bool:
    for attempt in range(attempts):
        if attempt:
            time.sleep(VERIFY_INTERVAL_SECONDS)
        observed = live_observed_at(report_url)
        if observed and _same_moment(observed, expected_observed_at):
            return True
    return False
