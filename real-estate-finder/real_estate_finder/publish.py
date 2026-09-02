"""Check whether the hosted report site already serves a given scan.

`app/page.tsx` imports `report-data.json` at build time, so writing that file
changes nothing until the site is rebuilt and deployed. Deploying is a manual
step through the ChatGPT app-hosting UI, so nothing here can publish on its
own; what it can do is tell the truth about what is live. Only a page that
already serves this scan may be put behind the 전체 매물 보기 button.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SITE_ROOT = ROOT_DIR / "property-report-site"
SITE_DIR = SITE_ROOT / "site-app"

BUILD_TIMEOUT_SECONDS = 900
# A deploy takes a moment to go live, so the verify after a build retries.
VERIFY_ATTEMPTS = 4
VERIFY_INTERVAL_SECONDS = 6.0

_OBSERVED_AT = re.compile(r'data-observed-at="([^"]+)"')

MANUAL_STEPS = (
    "리포트는 ChatGPT 앱 호스팅 UI에서 직접 배포해야 합니다:\n"
    f"  1) cd {SITE_DIR}\n"
    "  2) npm run build\n"
    "  3) 앱 호스팅 UI에서 배포하기\n"
    "  4) python -m real_estate_finder publish-report --verify-only"
)


class ManualPublishRequired(RuntimeError):
    """The site was built, but the deploy has to be finished by hand."""


def _node_path() -> str | None:
    """The bundled Node toolchain, if the workspace still carries one."""
    candidates = sorted(SITE_ROOT.glob(".tools/node-v*"))
    return str(candidates[-1]) if candidates else None


def _build_env() -> dict[str, str]:
    env = dict(os.environ)
    node = _node_path()
    if node:
        env["PATH"] = f"{node}{os.pathsep}{env.get('PATH', '')}"
    return env


def _tail(output: str, lines: int = 20) -> str:
    return "\n".join(output.strip().splitlines()[-lines:])


def _run(
    command: list[str], cwd: Path, env: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def build_site(site_dir: Path = SITE_DIR) -> None:
    """Rebuild the site so the page picks up the freshly written JSON."""
    env = _build_env()
    npm = shutil.which("npm", path=env["PATH"])
    if not npm:
        raise RuntimeError(
            "npm을 찾지 못했습니다. property-report-site/.tools의 Node를 설치하거나 PATH에 npm을 추가하세요."
        )
    result = _run([npm, "run", "build"], site_dir, env, BUILD_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise RuntimeError(
            "사이트 빌드에 실패했습니다:\n" + _tail(result.stderr or result.stdout)
        )


def _fetch(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "real-estate-finder"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def live_observed_at(report_url: str, timeout: float = 20.0) -> str | None:
    """The `observedAt` the deployed page is serving.

    `None` covers two different situations — the site was unreachable, and the
    site answered with a build too old to carry the marker at all. Neither one
    may put the button on a card, so both collapse to the same answer here;
    `describe_live` is what tells them apart for a human.
    """
    try:
        html = _fetch(report_url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    match = _OBSERVED_AT.search(html)
    return match.group(1) if match else None


def describe_live(report_url: str, timeout: float = 20.0) -> str:
    """A human-readable account of what the deployed page is serving."""
    try:
        html = _fetch(report_url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"사이트에 접속하지 못했습니다 ({exc})"
    match = _OBSERVED_AT.search(html)
    if match:
        return match.group(1)
    return "표시된 기준 시각 없음 (배포된 빌드가 오래된 버전입니다)"


def _same_moment(left: str, right: str) -> bool:
    if left == right:
        return True
    try:
        return datetime.fromisoformat(left) == datetime.fromisoformat(right)
    except ValueError:
        return False


def is_live(expected_observed_at: str, report_url: str, *, attempts: int = 1) -> bool:
    """Whether the deployed report already shows this scan."""
    for attempt in range(attempts):
        if attempt:
            time.sleep(VERIFY_INTERVAL_SECONDS)
        observed = live_observed_at(report_url)
        if observed and _same_moment(observed, expected_observed_at):
            return True
    return False
