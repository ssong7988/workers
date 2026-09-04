"""Operating-system preparation for a collector run.

The collector itself only needs an Edge DevTools endpoint. This module owns
the small Windows-specific part that makes that endpoint available, so both a
human CLI run and Dagster can call the same Python workflow without routing
the job through PowerShell.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_EDGE_CDP = "http://127.0.0.1:9222"
EDGE_PROFILE_NAME = "naver-land-edge"


def debug_endpoint_ready(endpoint: str, *, timeout: float = 3.0) -> bool:
    """Return whether an Edge/Chromium DevTools endpoint is answering."""
    try:
        with urllib.request.urlopen(
            f"{endpoint.rstrip('/')}/json/version", timeout=timeout
        ) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def find_edge_executable() -> Path:
    """Find Microsoft Edge using the same locations as the old PS1 runner."""
    candidates = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(variable)
        if root:
            candidates.append(
                Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    command = shutil.which("msedge.exe")
    if command:
        return Path(command)
    raise RuntimeError("Microsoft Edge를 찾지 못했습니다. msedge.exe 설치 경로를 확인하세요.")


def ensure_edge_debugging(
    endpoint: str = DEFAULT_EDGE_CDP, *, wait_seconds: float = 30.0
) -> None:
    """Start the dedicated Edge profile when the local endpoint is absent."""
    if not endpoint:
        print("CDP 주소가 비어 있어 Playwright persistent profile을 사용합니다.")
        return
    if debug_endpoint_ready(endpoint):
        print(f"디버깅 엔드포인트에서 Edge를 찾았습니다 ({endpoint}).")
        return
    if endpoint.rstrip("/") != DEFAULT_EDGE_CDP:
        raise RuntimeError(f"디버깅 엔드포인트가 응답하지 않습니다: {endpoint}")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA를 찾지 못해 Edge 전용 프로필 경로를 만들 수 없습니다.")
    profile = Path(local_app_data) / EDGE_PROFILE_NAME
    edge = find_edge_executable()
    print(f"전용 프로필로 Edge를 시작합니다: {profile}")
    subprocess.Popen(
        [
            str(edge),
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile}",
        ]
    )

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if debug_endpoint_ready(endpoint, timeout=1.0):
            print("Edge 디버깅 엔드포인트가 준비됐습니다.")
            return
        time.sleep(0.7)
    raise RuntimeError(
        "Edge를 시작했지만 디버깅 포트가 열리지 않았습니다. "
        "열린 Edge 창을 모두 닫고 다시 실행하세요."
    )
