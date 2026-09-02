"""Build the hosted report site, deploy it, and confirm the live page matches.

`app/page.tsx` imports `report-data.json` at build time, so writing that file
changes nothing until the site is rebuilt and deployed. Publishing therefore
ends with a live check: only a page that already serves this scan may be put
behind the 전체 매물 보기 button.
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
REPORT_DATA = Path("app") / "report-data.json"
DEPLOY_REMOTE = "sites"
DEPLOY_BRANCH = "main"

BUILD_TIMEOUT_SECONDS = 900
GIT_TIMEOUT_SECONDS = 180
# Credential Manager may still answer from its store — it just may not open a
# dialog to ask. Disabling the helper entirely would lock out saved logins too.
NO_CREDENTIAL_PROMPT = ("-c", "credential.interactive=false")
# The deploy can take a moment to go live after the push returns.
VERIFY_ATTEMPTS = 4
VERIFY_INTERVAL_SECONDS = 6.0

_OBSERVED_AT = re.compile(r'data-observed-at="([^"]+)"')

MANUAL_STEPS = (
    "리포트를 손으로 배포한 뒤 확인하세요:\n"
    f"  1) cd {SITE_DIR}\n"
    "  2) npm run build\n"
    "  3) 평소 쓰시는 배포 UI로 올리기\n"
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


def deploy_site(site_dir: Path = SITE_DIR, *, message: str | None = None) -> None:
    """Commit the report data and push it to the hosting remote.

    Every credential prompt is disabled. `GIT_TERMINAL_PROMPT` alone is not
    enough: Git Credential Manager answers with a GUI dialog that a scheduled
    scan can sit behind forever, so the helper is told never to ask. A saved
    login still works; only the dialog is off.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        try:
            return _run(
                ["git", *NO_CREDENTIAL_PROMPT, *args],
                site_dir,
                env,
                GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise ManualPublishRequired(
                f"git {args[0]}이(가) {GIT_TIMEOUT_SECONDS}초 안에 끝나지 않았습니다."
                + "\n\n"
                + MANUAL_STEPS
            ) from None

    git("add", str(REPORT_DATA))
    if git("diff", "--cached", "--quiet").returncode != 0:
        commit = git(
            "commit", "-m", message or "Publish latest property report results"
        )
        if commit.returncode != 0:
            raise ManualPublishRequired(
                "리포트 데이터를 커밋하지 못했습니다:\n"
                + _tail(commit.stderr or commit.stdout)
                + "\n\n"
                + MANUAL_STEPS
            )

    push = git("push", DEPLOY_REMOTE, f"HEAD:{DEPLOY_BRANCH}")
    if push.returncode != 0:
        raise ManualPublishRequired(
            f"{DEPLOY_REMOTE} 원격으로 push하지 못했습니다:\n"
            + _tail(push.stderr or push.stdout)
            + "\n\n"
            + MANUAL_STEPS
        )


def _fetch(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "real-estate-finder"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def live_observed_at(report_url: str, timeout: float = 20.0) -> str | None:
    """The `observedAt` the deployed page is actually serving, if it exposes one."""
    try:
        html = _fetch(report_url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    match = _OBSERVED_AT.search(html)
    return match.group(1) if match else None


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


def publish_report(
    expected_observed_at: str, report_url: str, *, site_dir: Path = SITE_DIR
) -> bool:
    """Build, deploy, and verify. True only when the live page shows this scan."""
    build_site(site_dir)
    deploy_site(site_dir)
    return is_live(expected_observed_at, report_url, attempts=VERIFY_ATTEMPTS)
