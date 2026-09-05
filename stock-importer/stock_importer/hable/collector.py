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
from . import window
from .export import click_toolbar, export_grid
from .extract import (
    ExtractionError,
    capture,
    close_popup_menus,
    copy_grid,
    open_context_menu,
    read_menu_items,
)


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class HableCollector:
    """열려 있는 1285 화면 하나를 읽는다."""

    SCREEN = window.ASSET_SCREEN
    # 조회를 누른 뒤 표가 채워질 때까지. 계좌 다섯 개를 한 번에 부른다.
    QUERY_WAIT_SECONDS = 4.0

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    # ------------------------------------------------------------------ 상태

    def _open_screen(self) -> tuple[int, int]:
        main = window.main_window()
        window.ensure_input_allowed(main)
        if window.ensure_restored(main):
            print("H-able 창이 최소화돼 있어 복원했습니다.")
        screen = window.find_screen(main, self.SCREEN)
        closed = window.clear_notice_screens(main, screen)
        if closed:
            print("로그인 안내 화면을 닫았습니다: " + ", ".join(closed))
        return main, screen

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
        click_toolbar(main, screen, grid, "query")
        time.sleep(self.QUERY_WAIT_SECONDS)

        clipboard = copy_grid(main, screen, grid)
        if clipboard.strip():
            headers, rows = parse_delimited_table(clipboard)
            if rows:
                return headers, rows, "클립보드 복사"
        headers, rows, exported = export_grid(main, screen, grid, self.data_dir / "hable")
        if not rows:
            raise ExtractionError(
                f"내보낸 파일에 행이 없습니다: {exported}\n"
                "[1285]에서 조회가 된 상태인지 확인하세요."
            )
        return headers, rows, f"엑셀 내보내기({exported.name})"

    # ------------------------------------------------------------------ 공개

    def probe(self) -> dict[str, Any]:
        """화면 구조를 그대로 적어 둔다. 아무것도 바꾸지 않는다.

        여기서 나온 것으로 어느 방법(복사/우클릭/내보내기)이 먹히는지 정한다.
        """
        main, screen = self._open_screen()
        left, top, width, height = window.rect(screen)
        process = window.process_id(main)

        dialogs = [
            {"handle": hex(handle), "rect": window.rect(handle), "labels": window.dialog_labels(handle)}
            for handle in window.notice_dialogs(process)
        ]
        found = window.panes(screen)
        grid = self._grid_pane(screen)

        click_toolbar(main, screen, grid, "query")
        time.sleep(self.QUERY_WAIT_SECONDS)
        shot = capture(main, screen, self.data_dir / "hable-1285.png")
        clipboard = copy_grid(main, screen, grid)
        menus = open_context_menu(main, screen, grid)
        close_popup_menus()

        headers, rows = parse_delimited_table(clipboard)

        # 엑셀 내보내기도 실제로 눌러 본다. 어느 방법이 먹히는지가 이 명령의
        # 존재 이유다. 실패해도 probe 자체는 끝까지 간다.
        export: dict[str, Any] = {"tried": True}
        try:
            export_headers, export_rows, exported = export_grid(
                main, screen, grid, self.data_dir / "hable"
            )
            export.update(
                file=str(exported),
                headers=export_headers,
                columns=map_columns(export_headers),
                missing_fields=missing_fields(map_columns(export_headers)),
                row_count=len(export_rows),
                first_rows=export_rows[:3],
            )
        except (ExtractionError, OSError) as error:
            export.update(error=str(error))

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
            "context_menu_items": [item for handle in menus for item in read_menu_items(handle)],
            "clipboard_characters": len(clipboard),
            "clipboard_headers": headers,
            "clipboard_columns": map_columns(headers),
            "clipboard_missing_fields": missing_fields(map_columns(headers)),
            "clipboard_row_count": len(rows),
            "clipboard_first_rows": rows[:3],
            "excel_export": export,
            "screenshot": str(shot),
        }

    def collect_holdings(self) -> dict[str, Any]:
        """1285에서 보유 종목을 읽어 계좌별로 묶는다."""
        main, screen = self._open_screen()

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
            "source_name": f"H-able [{self.SCREEN}] 총자산현황",
            "read_with": method,
            "headers": headers,
            "rows_read": len(rows),
            "rows_skipped": skipped,
            "accounts": group_by_account(positions),
        }
