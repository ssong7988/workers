"""H-able [0354] 계좌별 수익률 추이에서 최근 1년을 읽는다."""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from . import window
from .collector import HableCollector
from .extract import VK_DOWN, VK_RETURN, VK_UP, focus, press_key, unpin
from .trade_screen import _fill_date, click_point_settled

SCREEN = "0354"
ACCOUNT_FIELD = (120, 83)
SINCE_FIELD = (36, 119)
ONE_MONTH_BUTTON = (242, 119)
QUERY_BUTTON = (629, 119)
PRINT_BUTTON = (662, 119)
REPORT_FILE = Path(r"C:\KB증권\hable\temp\rpt035400000.dat")
ACCOUNT_ORDER = Path(__file__).resolve().parents[2] / "config" / "account-order.json"


def _close_preview(existing: set[int]) -> None:
    for handle in window.top_level_windows():
        if handle not in existing and window.window_text(handle) == "Report Viewer":
            window.user32.PostMessageW(handle, window.WM_CLOSE, 0, 0)
    time.sleep(0.4)


def set_period(main: int, screen: int, start: date, end: date) -> None:
    """종료일을 오늘로 맞춘 뒤 시작일을 확장한다. 결과 날짜는 내보낸 표에서 검증한다."""
    if end != date.today():
        raise ValueError("[0354] 종료일은 오늘이어야 합니다.")
    # H-able 기간 버튼이 종료일을 오늘로 맞춘다. 그 뒤 시작일만 1년 전으로 확장한다.
    click_point_settled(main, screen, ONE_MONTH_BUTTON, 0.5)
    _fill_date(main, screen, SINCE_FIELD, start.strftime("%Y%m%d"))


def validate_period(rows: list[dict], start: date, end: date) -> None:
    days = sorted(date.fromisoformat(row["as_of"]) for row in rows)
    if not days or len(days) != len(set(days)):
        raise RuntimeError(f"[{SCREEN}] 날짜가 없거나 중복됐습니다.")
    if days[0] != start or not end - timedelta(days=7) <= days[-1] <= end:
        raise RuntimeError(f"[{SCREEN}] 요청한 1년 범위와 다르거나 최신 자료가 아닙니다: {days[0]} ~ {days[-1]}")
    if any((right - left).days != 1 for left, right in zip(days, days[1:])):
        raise RuntimeError(f"[{SCREEN}] 일간 기록 중간에 누락 날짜가 있습니다.")


def _number(value: str) -> Decimal:
    return Decimal(value.replace(",", "").strip() or "0")


def _read_report() -> list[dict]:
    body = REPORT_FILE.read_text(encoding="cp949").split("//EOR//", 1)[0]
    result = []
    for raw in body.split("_@R@_"):
        columns = raw.strip().split("_@C@_")
        if len(columns) < 8 or not columns[0].strip():
            continue
        result.append(
            {
                "as_of": columns[0].replace("/", "-"),
                "market_value": str(_number(columns[1]) * 1000),
                "deposit": str(_number(columns[3]) * 1000),
                "withdrawal": str(_number(columns[4]) * 1000),
                "investment_pl": str(_number(columns[5]) * 1000),
                "daily_return": str(_number(columns[6]) / 100),
                "cumulative_return": str(_number(columns[7]) / 100),
            }
        )
    return result


def collect_history(data_dir: Path) -> dict:
    """등록된 다섯 계좌만 순회하여 H-able 원본 일별 수익률을 반환한다."""
    order = json.loads(ACCOUNT_ORDER.read_text(encoding="utf-8"))["accounts"]
    existing = set(window.top_level_windows())
    main = window.main_window()
    try:
        window.ensure_restored(main)
        focus(main)
        main, screen = HableCollector(data_dir, screen=SCREEN)._open_screen()
        today = date.today()
        try:
            start = today.replace(year=today.year - 1)
        except ValueError:
            start = today.replace(year=today.year - 1, day=28)
        set_period(main, screen, start, today)
        accounts = []
        for raw_index, masked_number in sorted(order.items(), key=lambda item: int(item[0])):
            index = int(raw_index)
            click_point_settled(main, screen, ACCOUNT_FIELD, 0.4)
            press_key(VK_DOWN, settle=0.5)
            press_key(VK_UP, times=12, settle=0.08)
            if index:
                press_key(VK_DOWN, times=index, settle=0.08)
            press_key(VK_RETURN, settle=0.8)
            click_point_settled(main, screen, QUERY_BUTTON, 3.5)
            window.ensure_query_ready(main, screen)
            before = REPORT_FILE.stat().st_mtime_ns if REPORT_FILE.exists() else 0
            click_point_settled(main, screen, PRINT_BUTTON, 1.5)
            if not REPORT_FILE.exists() or REPORT_FILE.stat().st_mtime_ns == before:
                raise RuntimeError(f"[{SCREEN}] 인쇄용 성과 표가 갱신되지 않았습니다.")
            rows = _read_report()
            if not rows:
                raise RuntimeError(f"[{SCREEN}] {masked_number} 계좌의 성과 표가 비었습니다.")
            validate_period(rows, start, today)
            accounts.append({"account_number": masked_number, "rows": rows})
            _close_preview(existing)
        return {"source_name": "H-able 0354 계좌별수익률추이", "accounts": accounts}
    finally:
        _close_preview(existing)
        unpin(main)
