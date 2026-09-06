"""H-able [1285] 총자산현황에서 계좌별 잔고를 읽는다.

약속은 웹 수집기와 같다 - **로그인은 사람이 하고, 프로그램은 이미 로그인된
화면에 보이는 것만 읽는다.** 인증서 비밀번호·계좌 비밀번호·OTP를 저장하지도
입력하지도 않는다. 계좌 비밀번호는 사용자가 H-able 설정에 저장해 두고, 우리는
조회된 화면을 읽기만 한다.

1285를 고른 이유: `전체` 선택 하나로 다섯 계좌가 한 표에 다 나온다. 계좌를
순회할 필요가 없다.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..parsing import (
    RowError,
    group_by_account,
    map_columns,
    missing_fields,
    parse_delimited_table,
    row_to_position,
)
from . import keepalive, window
from .export import click_toolbar, export_grid
from .extract import (
    ExtractionError,
    capture,
    idle_seconds,
    pin_to_top,
    close_popup_menus,
    copy_grid,
    open_context_menu,
    read_menu_items,
    unpin,
)


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _first_line(exc: Exception) -> str:
    """안내문의 첫 줄만. 뒷줄은 사람이 할 일을 적은 여러 줄짜리다."""
    return str(exc).splitlines()[0]


class HableCollector:
    """열려 있는 1285 화면 하나를 읽는다."""

    # 기본은 총자산현황. 거래내역([0112]) 같은 다른 화면도 같은 방법으로
    # 읽으므로 화면번호는 상수가 아니라 인자다.
    SCREEN = window.ASSET_SCREEN
    # 조회를 누른 뒤 표가 채워질 때까지. 계좌 다섯 개를 한 번에 부른다.
    QUERY_WAIT_SECONDS = 4.0

    def __init__(self, data_dir: Path, screen: str | None = None) -> None:
        self.data_dir = data_dir
        self.screen = screen or self.SCREEN

    # ------------------------------------------------------------------ 상태

    def _open_screen(self) -> tuple[int, int]:
        main = window.main_window()
        window.ensure_input_allowed(main)
        if window.ensure_restored(main):
            print("H-able 창이 최소화돼 있어 복원했습니다.")
        # 클릭이 닿으려면 H-able이 z-order 위에 있어야 한다. 활성화는 자주
        # 거절당하지만 z-order를 올리는 것은 거절되지 않는다. 끝나면 되돌린다.
        screen = window.find_screen(main, self.screen)
        window.ensure_query_ready(main, screen)
        pin_to_top(main)
        # 광고·공지 팝업이 always-on-top이라 z-order로는 못 이긴다. 먼저 치운다.
        try:
            popups = window.clear_covering_dialogs(main, screen)
            if popups:
                print("가리고 있던 팝업을 닫았습니다: " + ", ".join(popups))
            closed = window.clear_notice_screens(main, screen)
            if closed:
                print("로그인 안내 화면을 닫았습니다: " + ", ".join(closed))
        except BaseException:
            unpin(main)
            raise
        return main, screen

    def _query(self, main: int, screen: int, grid: window.Pane) -> None:
        window.ensure_query_ready(main, screen)
        click_toolbar(main, screen, grid, "query")
        deadline = time.monotonic() + self.QUERY_WAIT_SECONDS
        while True:
            window.ensure_query_ready(main, screen)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    @staticmethod
    def _logged_out_notice(main: int) -> str:
        """자동 로그아웃 안내창이 떠 있으면 그 문구를 돌려준다.

        이게 떠 있으면 화면의 숫자는 로그아웃되기 전의 낡은 값이다. 낡은 값을
        오늘 잔고로 저장하면 조용히 틀린다.
        """
        process = window.process_id(main)
        for handle in window.notice_dialogs(process):
            labels = " ".join(window.dialog_labels(handle))
            if any(hint in labels for hint in window.LOGGED_OUT_HINTS):
                return labels
        return ""

    def _grid_pane(self, screen: int) -> window.Pane:
        """잔고 그리드로 보이는 영역. 화면 아래쪽의 가장 넓은 판이다."""
        candidates = window.panes(screen)
        if not candidates:
            raise ExtractionError("1285 화면 안에서 표 영역을 찾지 못했습니다.")
        _left, _top, _width, height = window.rect(screen)
        lower = [pane for pane in candidates if pane.y > height // 2]
        return max(lower or candidates, key=lambda pane: pane.width)

    def _read_table(
        self, main: int, screen: int, grid: window.Pane
    ) -> tuple[list[str], list[list[str]], str]:
        """되는 방법으로 표를 읽는다. 되는 것이 없으면 지어내지 않고 멈춘다.

        복사가 먼저다 - 파일이 안 남아 계좌번호와 잔고가 디스크에 떨어지지 않는다.
        이 그리드에서는 실측상 복사가 아무것도 내놓지 않아 대개 내보내기로 간다.
        """
        # 화면에 남아 있는 값은 언제 조회한 것인지 알 수 없다. 오늘 잔고를
        # 읽으려면 우리가 직접 조회를 눌러야 한다.
        self._query(main, screen, grid)

        clipboard = copy_grid(main, screen, grid)
        if clipboard.strip():
            headers, rows = parse_delimited_table(clipboard)
            if rows:
                return headers, rows, "클립보드 복사"
        headers, rows, how = export_grid(main, screen, grid, self.data_dir / "hable")
        if not rows:
            raise ExtractionError(
                "내보낸 표에 행이 없습니다. [1285]에서 조회가 된 상태인지 확인하세요."
            )
        return headers, rows, how

    # ------------------------------------------------------------------ 공개

    def keep_awake(self) -> dict[str, Any]:
        """세션이 끊기지 않게 조회를 한 번 누른다.

        예외를 올리지 않는다. 깨우지 못하는 것은 알릴 일이지 실행을 실패로
        만들 일이 아니다 - H-able을 꺼 둔 날에도 매시 경고가 오면 곤란하다.
        """
        decision = keepalive.decide(
            idle_seconds(), keepalive.seconds_since_touch(self.data_dir)
        )
        if not decision.touch:
            return {"state": keepalive.STATE_SKIPPED, "detail": decision.reason}
        return self._touch(decision.reason)

    def check_ready(self) -> dict[str, Any]:
        """지금 수집할 수 있는 상태인지 본다. 유휴 여부는 따지지 않는다.

        수집 직전 점검용이다. 사람이 손을 대야 하는 상태면 부르는 쪽이 그것을
        실패로 바꿔 알림을 부른다(`keepalive.exit_code`).
        """
        return self._touch("수집 전 점검입니다.")

    def _touch(self, reason: str) -> dict[str, Any]:
        """조회를 한 번 누른다. 표를 읽지도 저장하지도 않는다.

        상태를 문자열로 짐작하지 않으려고 예외 타입으로 가른다. 어느 것이든
        창을 맨 위로 올린 것은 반드시 되돌린다.
        """
        handle = window.find_main_window()
        if not handle:
            return {
                "state": keepalive.STATE_NOT_RUNNING,
                "detail": "H-able이 실행 중이 아닙니다.",
            }
        # 클릭하려면 창을 복원해야 하는데, 이건 매시 도는 작업이다. 사용자가
        # 내려둔 창을 올려놓은 채로 두면 한 시간마다 화면이 바뀐다.
        was_minimized = window.is_minimized(handle)
        try:
            main, screen = self._open_screen()
        except window.AccountPasswordRequired as exc:
            return {"state": keepalive.STATE_PASSWORD_REQUIRED, "detail": _first_line(exc)}
        except window.LoggedOut as exc:
            return {"state": keepalive.STATE_LOGGED_OUT, "detail": _first_line(exc)}
        except window.HableNotRunning as exc:
            return {"state": keepalive.STATE_NOT_RUNNING, "detail": _first_line(exc)}
        except window.ScreenNotOpen as exc:
            return {"state": keepalive.STATE_SCREEN_MISSING, "detail": _first_line(exc)}
        except (window.HableError, ExtractionError) as exc:
            return {"state": keepalive.STATE_FAILED, "detail": _first_line(exc)}

        try:
            notice = self._logged_out_notice(main)
            if notice:
                return {"state": keepalive.STATE_LOGGED_OUT, "detail": notice}
            self._query(main, screen, self._grid_pane(screen))
        except window.AccountPasswordRequired as exc:
            return {"state": keepalive.STATE_PASSWORD_REQUIRED, "detail": _first_line(exc)}
        except window.LoggedOut as exc:
            return {"state": keepalive.STATE_LOGGED_OUT, "detail": _first_line(exc)}
        except (window.HableError, ExtractionError) as exc:
            return {"state": keepalive.STATE_FAILED, "detail": _first_line(exc)}
        finally:
            unpin(main)
            if was_minimized:
                window.minimize(main)

        keepalive.record_touch(self.data_dir)
        return {"state": keepalive.STATE_OK, "detail": f"조회를 눌렀습니다. {reason}"}

    def probe(self, *, query: bool = True) -> dict[str, Any]:
        """화면 구조를 그대로 적어 둔다.

        여기서 나온 것으로 어느 방법(복사/우클릭/내보내기)이 먹히는지 정한다.

        `query=False`면 조회 버튼도 우클릭도 하지 않고 창 구조만 읽는다.
        툴바 좌표는 1285에서 재서 얻은 값이라, 처음 보는 화면에서는 엉뚱한
        컨트롤을 누를 수 있다. 모르는 화면은 먼저 보기만 한다.
        """
        main, screen = self._open_screen()
        try:
            return self._probe(main, screen, query=query)
        finally:
            # 클릭을 닿게 하려고 창을 맨 위로 올렸다. 사용자 화면에 그대로
            # 두면 곤란하니 무슨 일이 있어도 되돌린다.
            unpin(main)

    def _probe(self, main: int, screen: int, *, query: bool = True) -> dict[str, Any]:
        left, top, width, height = window.rect(screen)
        process = window.process_id(main)

        dialogs = [
            {"handle": hex(handle), "rect": window.rect(handle), "labels": window.dialog_labels(handle)}
            for handle in window.notice_dialogs(process)
        ]
        found = window.panes(screen)
        grid = self._grid_pane(screen)
        clipboard = ""
        menus: list[int] = []
        export: dict[str, Any] = {"tried": False}
        if query:
            self._query(main, screen, grid)
        # 조회 뒤에 찍는다. 인증에 막힌 화면의 숫자는 낡은 값이라 남길 이유가 없다.
        shot = capture(main, screen, self.data_dir / f"hable-{self.screen}.png")
        if query:
            clipboard = copy_grid(main, screen, grid)
            menus = open_context_menu(main, screen, grid)
            close_popup_menus()

            # 엑셀 내보내기도 실제로 눌러 본다. 어느 방법이 먹히는지가 이 명령의
            # 존재 이유다. 실패해도 probe 자체는 끝까지 간다.
            export = {"tried": True}
            try:
                export_headers, export_rows, how = export_grid(
                    main, screen, grid, self.data_dir / "hable"
                )
                export.update(
                    how=how,
                    headers=export_headers,
                    columns=map_columns(export_headers),
                    missing_fields=missing_fields(map_columns(export_headers)),
                    row_count=len(export_rows),
                    first_rows=export_rows[:3],
                )
            except (ExtractionError, OSError) as error:
                export.update(error=str(error))

        headers, rows = parse_delimited_table(clipboard)

        return {
            "observed_at": iso_now(),
            "screen": {"title": window.window_text(screen), "rect": [left, top, width, height]},
            "logged_out_notice": self._logged_out_notice(main),
            "notice_dialogs": dialogs,
            "panes": [
                {"handle": hex(p.handle), "x": p.x, "y": p.y, "width": p.width, "height": p.height}
                for p in found
            ],
            "grid_pane": {"handle": hex(grid.handle), "x": grid.x, "y": grid.y,
                          "width": grid.width, "height": grid.height},
            "context_menu_windows": [hex(handle) for handle in menus],
            "context_menu_items": [
                item.name for handle in menus for item in read_menu_items(handle)
            ],
            "controls": self._controls(screen),
            "clipboard_characters": len(clipboard),
            "clipboard_headers": headers,
            "clipboard_columns": map_columns(headers),
            "clipboard_missing_fields": missing_fields(map_columns(headers)),
            "clipboard_row_count": len(rows),
            "clipboard_first_rows": rows[:3],
            "excel_export": export,
            "screenshot": str(shot),
        }

    @staticmethod
    def _controls(screen: int) -> list[dict[str, Any]]:
        """화면 안의 표준 컨트롤 목록.

        계좌 콤보, 조회기간 입력칸, 조회·다음 버튼이 어디 있는지 알아야
        거래내역처럼 조건을 넣고 여러 번 조회하는 화면을 다룰 수 있다.
        그린 셀(`AfxWnd120`)은 수가 많고 알아볼 것이 없어 뺀다.
        """
        rows = []
        for handle in window.descendants(screen):
            name = window.class_name(handle)
            if name == "AfxWnd120":
                continue
            rows.append(
                {
                    "handle": hex(handle),
                    "class": name,
                    "text": window.window_text(handle)[:60],
                    "rect": window.rect(handle),
                }
            )
        return rows

    def collect_holdings(self) -> dict[str, Any]:
        """1285에서 보유 종목을 읽어 계좌별로 묶는다."""
        main, screen = self._open_screen()
        try:
            return self._collect(main, screen)
        finally:
            unpin(main)

    def _collect(self, main: int, screen: int) -> dict[str, Any]:
        notice = self._logged_out_notice(main)
        if notice:
            raise ExtractionError(
                "H-able이 자동 로그아웃된 상태입니다. 화면의 숫자는 낡은 값이라 저장하지 않습니다.\n"
                f"안내창: {notice}\n"
                "다시 로그인하고 [1285]를 조회한 뒤 실행하세요."
            )

        grid = self._grid_pane(screen)
        headers, rows, method = self._read_table(main, screen, grid)
        print(f"표를 {method}(으)로 읽었습니다: {len(rows)}행")

        columns = map_columns(headers)
        absent = missing_fields(columns)
        if absent:
            raise ExtractionError(
                f"읽은 표에서 {', '.join(absent)} 열을 찾지 못했습니다.\n"
                f"읽은 헤더: {headers}"
            )

        positions: list[dict] = []
        skipped = 0
        for cells in rows:
            try:
                positions.append(row_to_position(columns, cells))
            except RowError as exc:
                # 합계 줄처럼 종목이 아닌 줄이 섞인다. 값이 아예 없는 줄만 조용히
                # 넘기고, 그 외에는 왜 건너뛰었는지 남긴다.
                if any(cell.strip() for cell in cells):
                    print(f"  건너뜀 - {exc}")
                skipped += 1

        if not positions:
            raise ExtractionError("보유 종목을 한 건도 읽지 못했습니다.")

        return {
            "observed_at": iso_now(),
            "as_of": date.today().isoformat(),
            "source_name": f"H-able [{self.screen}] 총자산현황",
            "read_with": method,
            "headers": headers,
            "rows_read": len(rows),
            "rows_skipped": skipped,
            "accounts": group_by_account(positions),
        }
