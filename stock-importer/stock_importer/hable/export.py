"""1285 툴바의 내보내기 버튼을 눌러 파일로 받아 읽는다.

Ctrl+C도 우클릭 메뉴도 이 그리드에서는 아무것도 내놓지 않았다(실측). 남은 것은
화면 오른쪽 툴바의 내보내기 버튼뿐이다. 버튼이 창이 아니라 그려진 그림이라
좌표로 누를 수밖에 없는데, **좌표는 그리드 판의 오른쪽 끝을 기준으로 잡는다** -
창을 옮기거나 크기를 조금 바꿔도 같은 자리를 누른다.

저장 대화상자는 표준 `#32770`이라 여기서부터는 다시 정직하게 컨트롤을 다룬다.
"""

from __future__ import annotations

import csv
import ctypes
import time
from pathlib import Path

from .extract import BorrowedCursor, ExtractionError, focus, guard_target
from .window import Pane, class_name, descendants, process_id, rect, top_level_windows, window_text

# 1285 창(854x645)에서 실측한 자리. 툴바는 그리드 판의 위쪽 테두리에 붙어 있고
# 오른쪽 끝에서부터 조회·?·설정·인쇄·엑셀 순으로 놓인다.
TOOLBAR_Y_IN_PANE = 33
TOOLBAR_FROM_RIGHT = {
    "excel": 115,
    "print": 91,
    "settings": 68,
    "help": 45,
    "query": 18,
}

SAVE_DIALOG_CLASS = "#32770"
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5


def click_toolbar(main_handle: int, screen_handle: int, pane: Pane, button: str) -> None:
    """그리드 판의 오른쪽 끝을 기준으로 툴바 버튼 하나를 누른다."""
    if button not in TOOLBAR_FROM_RIGHT:
        raise ExtractionError(f"모르는 툴바 버튼입니다: {button}")
    focus(main_handle)
    left, top, _width, _height = rect(screen_handle)
    x = left + pane.x + pane.width - TOOLBAR_FROM_RIGHT[button]
    y = top + pane.y + TOOLBAR_Y_IN_PANE
    guard_target(x, y, process_id(main_handle))
    with BorrowedCursor() as cursor:
        cursor.click(x, y, settle=0.8)


def _controls(handle: int) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for child in descendants(handle):
        grouped.setdefault(class_name(child), []).append(child)
    return grouped


def _looks_like_save_dialog(handle: int) -> bool:
    grouped = _controls(handle)
    if not grouped.get("Edit") and not grouped.get("ComboBoxEx32"):
        return False
    return any(
        "저장" in window_text(button) or "Save" in window_text(button)
        for button in grouped.get("Button", [])
    )


def wait_for_save_dialog(process: int, *, timeout: float = 15.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for handle in top_level_windows():
            if (
                class_name(handle) == SAVE_DIALOG_CLASS
                and process_id(handle) == process
                and _looks_like_save_dialog(handle)
            ):
                return handle
        time.sleep(0.3)
    raise ExtractionError(
        "저장 대화상자가 뜨지 않았습니다. 툴바의 내보내기 버튼 자리가 바뀌었을 수 있습니다.\n"
        "`hable-probe`가 남긴 화면 그림에서 버튼 위치를 다시 재 주세요."
    )


def save_as(dialog: int, destination: Path) -> None:
    """대화상자의 파일 이름 칸에 경로를 넣고 저장을 누른다."""
    grouped = _controls(dialog)
    edits = grouped.get("Edit") or []
    if not edits:
        raise ExtractionError("저장 대화상자에서 파일 이름 칸을 찾지 못했습니다.")
    user32 = ctypes.windll.user32
    destination.parent.mkdir(parents=True, exist_ok=True)
    user32.SendMessageW(edits[0], WM_SETTEXT, 0, ctypes.c_wchar_p(str(destination)))
    for button in grouped.get("Button", []):
        if "저장" in window_text(button) or "Save" in window_text(button):
            user32.SendMessageW(button, BM_CLICK, 0, 0)
            return
    raise ExtractionError("저장 대화상자에서 저장 단추를 찾지 못했습니다.")


def wait_for_export(folder: Path, since: float, *, timeout: float = 25.0) -> Path:
    """저장을 누른 뒤 그 폴더에 새로 생긴 파일을 기다린다.

    정확한 경로를 지정해도 H-able이 제 형식에 맞춰 확장자를 바꿔 붙일 수 있어
    이름을 고집하지 않는다. 크기가 두 번 연속 같을 때만 다 썼다고 본다 - 쓰는
    도중에 읽으면 반쪽짜리 표를 읽는다.
    """
    deadline = time.monotonic() + timeout
    sizes: dict[Path, int] = {}
    while time.monotonic() < deadline:
        fresh = [
            path
            for path in folder.glob("*")
            if path.is_file() and path.stat().st_mtime >= since
        ]
        for path in fresh:
            size = path.stat().st_size
            if size > 0 and sizes.get(path) == size:
                return path
            sizes[path] = size
        time.sleep(0.4)
    raise ExtractionError(f"내보낸 파일이 만들어지지 않았습니다: {folder}")


def read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    """내보낸 파일에서 (헤더, 행들)을 읽는다. CSV/TXT와 XLSX를 받는다."""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt"):
        # H-able이 어떤 인코딩으로 쓰는지 확정되지 않았다. 흔한 순서로 시도한다.
        for encoding in ("cp949", "utf-8-sig", "utf-8"):
            try:
                text = path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
            delimiter = "\t" if "\t" in text.splitlines()[0] else ","
            rows = [
                [cell.strip() for cell in row]
                for row in csv.reader(text.splitlines(), delimiter=delimiter)
                if any(cell.strip() for cell in row)
            ]
            if rows:
                return rows[0], rows[1:]
        raise ExtractionError(f"내보낸 파일의 인코딩을 알 수 없습니다: {path}")

    if suffix in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:  # pragma: no cover - 설치 안내
            raise ExtractionError(
                "XLSX를 읽으려면 openpyxl이 필요합니다. real-estate-finder의 가상환경에 설치하세요."
            ) from exc
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        rows = [
            ["" if cell.value is None else str(cell.value).strip() for cell in row]
            for row in sheet.iter_rows()
            if any(cell.value is not None for cell in row)
        ]
        workbook.close()
        if not rows:
            raise ExtractionError(f"내보낸 파일이 비어 있습니다: {path}")
        return rows[0], rows[1:]

    raise ExtractionError(f"읽을 줄 모르는 파일 형식입니다: {path.name}")


def export_grid(
    main_handle: int, screen_handle: int, pane: Pane, folder: Path, stem: str = "hable-1285"
) -> tuple[list[str], list[list[str]], Path]:
    """엑셀 버튼 → 저장 대화상자 → 파일 읽기까지 한 번에."""
    process = process_id(main_handle)
    folder.mkdir(parents=True, exist_ok=True)
    since = time.time()
    click_toolbar(main_handle, screen_handle, pane, "excel")
    dialog = wait_for_save_dialog(process)
    save_as(dialog, folder / stem)
    exported = wait_for_export(folder, since)
    headers, rows = read_table(exported)
    return headers, rows, exported
