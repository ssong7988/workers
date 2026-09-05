"""KB 전용 Edge를 띄우는 부분. **재워 둔 웹 경로에 속한다.**

`real-estate-finder/real_estate_finder/runtime.py`와 같은 구조지만 포트와
프로필이 다르다. 네이버 스캔과 주식 수집이 겹쳐 돌아도 서로 창을 빼앗지
않아야 하고, 두 로그인 세션이 한 프로필에 섞이지도 않아야 한다.

두 수집기는 서로를 import하지 않는다. 서로 독립적으로 돌아가는 것이 요점이라
60줄을 공유하려고 의존성을 만들지 않는다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_EDGE_CDP = "http://127.0.0.1:9223"
EDGE_DEBUG_PORT = 9223
EDGE_PROFILE_NAME = "kbsec-edge"


def debug_endpoint_ready(endpoint: str, *, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(
            f"{endpoint.rstrip('/')}/json/version", timeout=timeout
        ) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def find_edge_executable() -> Path:
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
    endpoint: str = DEFAULT_EDGE_CDP,
    *,
    start_url: str = "",
    wait_seconds: float = 30.0,
) -> None:
    """전용 프로필 Edge가 없으면 띄운다. 이미 있으면 그대로 쓴다."""
    if not endpoint:
        print("CDP 주소가 비어 있어 Playwright 전용 프로필을 사용합니다.")
        return
    if debug_endpoint_ready(endpoint):
        print(f"KB 전용 Edge를 찾았습니다 ({endpoint}).")
        return
    if endpoint.rstrip("/") != DEFAULT_EDGE_CDP:
        raise RuntimeError(f"디버깅 엔드포인트가 응답하지 않습니다: {endpoint}")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA를 찾지 못해 Edge 전용 프로필 경로를 만들 수 없습니다.")
    profile = Path(local_app_data) / EDGE_PROFILE_NAME
    edge = find_edge_executable()
    print(f"KB 전용 프로필로 Edge를 시작합니다: {profile}")
    command = [
        str(edge),
        f"--remote-debugging-port={EDGE_DEBUG_PORT}",
        f"--user-data-dir={profile}",
    ]
    if start_url:
        command.append(start_url)
    subprocess.Popen(command)

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if debug_endpoint_ready(endpoint, timeout=1.0):
            print("KB 전용 Edge의 디버깅 포트가 준비됐습니다.")
            return
        time.sleep(0.7)
    raise RuntimeError(
        "Edge를 시작했지만 디버깅 포트가 열리지 않았습니다. "
        f"{profile} 프로필로 열린 Edge 창을 모두 닫고 다시 실행하세요."
    )
