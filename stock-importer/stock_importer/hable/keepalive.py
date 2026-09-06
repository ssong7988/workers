"""세션이 끊기지 않게 H-able을 주기적으로 깨워 둔다.

자동 로그인이 있는 네이버와 달리 **H-able 로그인은 자동화 대상이 아니다** -
인증서가 필요하고, 그 비밀번호는 이 저장소가 갖지 않기로 한 값이다. 한 번
풀리면 사람이 다시 로그인해야 한다. 그래서 풀리기 전에 막는 쪽이 값이 크다.

깨우는 방법은 조회 버튼 한 번이다. 읽기 전용 요청이고, 표를 읽지도 저장하지도
않는다.

이 파일에는 창을 만지지 않는 판단만 둔다. 그래야 창 없이 시험할 수 있다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# 사람이 자리를 비웠다고 볼 무입력 시간. 짧으면 작업 중에 창이 튀어오르고,
# 길면 깨울 기회를 놓친다.
MIN_IDLE_SECONDS = 180.0
# 사람이 계속 PC를 쓰고 있어도 이만큼 지나면 그때는 깨운다. H-able의 유휴
# 판정이 입력이 아니라 서버 요청 기준이면, 사람이 PC를 쓰는 것과 H-able 세션이
# 살아 있는 것은 별개이기 때문이다.
MAX_DEFER_SECONDS = 1800.0

TOUCH_FILE = "hable-last-touch.json"

STATE_OK = "ok"
STATE_SKIPPED = "skipped"
STATE_BLOCKED = "blocked"
STATE_NOT_RUNNING = "not_running"
STATE_SCREEN_MISSING = "screen_missing"
STATE_LOGGED_OUT = "logged_out"
STATE_PASSWORD_REQUIRED = "password_required"
STATE_FAILED = "failed"

# 수집을 하려면 사람이 손을 대야 하는 상태들. 이때만 실패로 끝내 알림을 부른다.
NEEDS_A_PERSON = (
    STATE_NOT_RUNNING,
    STATE_SCREEN_MISSING,
    STATE_LOGGED_OUT,
    STATE_PASSWORD_REQUIRED,
    STATE_FAILED,
)


@dataclass(frozen=True)
class TouchDecision:
    touch: bool
    reason: str


def decide(
    idle_seconds: float,
    seconds_since_touch: float | None,
    *,
    min_idle: float = MIN_IDLE_SECONDS,
    max_defer: float = MAX_DEFER_SECONDS,
) -> TouchDecision:
    """지금 깨울지 정한다.

    기본은 "사람이 자리를 비웠을 때만". 다만 마지막으로 깨운 지 오래되면 사람이
    쓰는 중이어도 깨운다 - 아무도 H-able을 만지지 않는 채로 하루가 갈 수 있다.
    """
    if idle_seconds >= min_idle:
        return TouchDecision(True, f"사람의 입력이 {int(idle_seconds)}초째 없습니다.")
    if seconds_since_touch is None:
        return TouchDecision(True, "아직 한 번도 깨운 기록이 없습니다.")
    if seconds_since_touch >= max_defer:
        return TouchDecision(
            True, f"마지막으로 깨운 지 {int(seconds_since_touch // 60)}분이 지났습니다."
        )
    return TouchDecision(
        False, f"사람이 쓰는 중입니다 (마지막 입력 {int(idle_seconds)}초 전)."
    )


def exit_code(state: str, *, require_ready: bool) -> int:
    """`hable-keepalive`는 무엇이 나와도 0, `hable-status`는 준비됐을 때만 0.

    깨우기는 못 해도 그만이라 실행을 실패로 만들지 않는다. 반면 수집 직전
    점검은 실패해야 한다 - 그래야 Dagster의 실패 훅이 카카오톡을 보낸다.
    """
    if not require_ready:
        return 0
    return 1 if state in NEEDS_A_PERSON else 0


def _touch_path(data_dir: Path) -> Path:
    return data_dir / TOUCH_FILE


def read_touched_at(data_dir: Path) -> datetime | None:
    """마지막으로 깨운 시각. 기록이 없거나 깨졌으면 None."""
    try:
        raw = json.loads(_touch_path(data_dir).read_text(encoding="utf-8"))
        return datetime.fromisoformat(raw["touched_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_touch(data_dir: Path, *, now: datetime | None = None) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    moment = now or datetime.now(timezone.utc).astimezone()
    _touch_path(data_dir).write_text(
        json.dumps({"touched_at": moment.isoformat(timespec="seconds")}),
        encoding="utf-8",
    )


def seconds_since_touch(data_dir: Path, *, now: datetime | None = None) -> float | None:
    touched_at = read_touched_at(data_dir)
    if touched_at is None:
        return None
    moment = now or datetime.now(timezone.utc).astimezone()
    return max(0.0, (moment - touched_at).total_seconds())
