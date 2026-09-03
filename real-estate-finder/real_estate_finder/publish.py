"""Check whether the local report server is serving the latest scan.

The scanner writes `data/state.json`; the report site (Django, run via
`report-site/run-site.bat`) reads it on every request, so there is no build or
deploy step. This module only verifies the server (and its Tailscale Funnel
tunnel, when used) is up and answering with the expected scan.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from datetime import datetime


# A server restart or a slow tunnel can take a moment to become ready.
VERIFY_ATTEMPTS = 4
VERIFY_INTERVAL_SECONDS = 6.0

_OBSERVED_AT = re.compile(r'data-observed-at="([^"]+)"')


def _fetch(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "real-estate-finder"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def live_observed_at(report_url: str, timeout: float = 20.0) -> str | None:
    """The `observedAt` the report server is currently serving.

    `None` covers two different situations — the server was unreachable, and it
    answered without the marker at all. Neither one may put the button on a
    card, so both collapse to the same answer here; `describe_live` is what
    tells them apart for a human.
    """
    try:
        html = _fetch(report_url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    match = _OBSERVED_AT.search(html)
    return match.group(1) if match else None


def describe_live(report_url: str, timeout: float = 20.0) -> str:
    """A human-readable account of what the report server is serving."""
    try:
        html = _fetch(report_url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"사이트에 접속하지 못했습니다 ({exc})"
    match = _OBSERVED_AT.search(html)
    if match:
        return match.group(1)
    return "리포트 서버 응답에 기준 시각이 없습니다"


def _same_moment(left: str, right: str) -> bool:
    if left == right:
        return True
    try:
        return datetime.fromisoformat(left) == datetime.fromisoformat(right)
    except ValueError:
        return False


def is_live(expected_observed_at: str, report_url: str, *, attempts: int = 1) -> bool:
    """Whether the report server already shows this scan."""
    for attempt in range(attempts):
        if attempt:
            time.sleep(VERIFY_INTERVAL_SECONDS)
        observed = live_observed_at(report_url)
        if observed and _same_moment(observed, expected_observed_at):
            return True
    return False
