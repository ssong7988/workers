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
import re
import time
import warnings
from pathlib import Path

from .extract import (
    BorrowedCursor,
    ExtractionError,
    MenuItem,
    click_menu_item,
    close_popup_menus,
    focus,
    ensure_clickable,
    open_context_menu,
    read_menu_items,
)
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
PROCESS_TERMINATE = 0x0001
WM_CLOSE = 0x0010


# 우클릭 메뉴에서 무엇을 고를지. 가벼운 것이 먼저다 - CSV와 TXT는 텍스트 파일
# 하나만 남기고 Excel 프로그램을 열지 않는다. 엑셀은 마지막이다.
EXPORT_PREFERENCE = (
    ("csv", ("csv",)),
    ("txt", ("txt", "텍스트", "text")),
    ("excel", ("excel", "엑셀", "xls")),
)


def pick_export_item(names: list[str]) -> str | None:
    """메뉴 항목 이름들 중 내보내기에 쓸 것 하나를 고른다.

    '저장'이나 '내보내기'가 붙은 항목만 후보로 본다 - '복사'나 '인쇄'를 잘못
    누르면 엉뚱한 일이 벌어진다.
    """
    candidates = [
        name
        for name in names
        if any(word in name for word in ("저장", "내보내기", "Save", "Export"))
    ]
    for _kind, needles in EXPORT_PREFERENCE:
        for name in candidates:
            lowered = name.lower()
            if any(needle in lowered for needle in needles):
                return name
    return None


def export_via_menu(
    main_handle: int, screen_handle: int, pane: Pane, folder: Path, stem: str
) -> tuple[list[str], list[list[str]], str] | None:
    """우클릭 메뉴로 내보낸다. 메뉴를 못 읽거나 쓸 항목이 없으면 None.

    이 길이 되면 Excel은 열리지 않는다.
    """
    menus = open_context_menu(main_handle, screen_handle, pane)
    if not menus:
        return None
    items: list[MenuItem] = []
    for handle in menus:
        items.extend(read_menu_items(handle))
    names = [item.name for item in items]
    chosen = pick_export_item(names)
    if chosen is None:
        close_popup_menus()
        return None
    target = next(item for item in items if item.name == chosen)
    if not click_menu_item(target):
        close_popup_menus()
        return None

    since = time.time()
    process = process_id(main_handle)
    try:
        dialog = wait_for_save_dialog(process, timeout=10.0)
    except ExtractionError:
        close_popup_menus()
        return None
    save_as(dialog, folder / stem)
    exported = wait_for_export(folder, since)
    headers, rows = read_table(exported)
    return headers, rows, f"우클릭 메뉴 '{chosen}' ({exported.name})"


def click_toolbar(main_handle: int, screen_handle: int, pane: Pane, button: str) -> None:
    """그리드 판의 오른쪽 끝을 기준으로 툴바 버튼 하나를 누른다."""
    if button not in TOOLBAR_FROM_RIGHT:
        raise ExtractionError(f"모르는 툴바 버튼입니다: {button}")
    focus(main_handle)
    left, top, _width, _height = rect(screen_handle)
    x = left + pane.x + pane.width - TOOLBAR_FROM_RIGHT[button]
    y = top + pane.y + TOOLBAR_Y_IN_PANE
    ensure_clickable(main_handle, screen_handle, x, y)
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


def read_open_workbook(*, close: bool = True) -> tuple[list[str], list[list[str]]] | None:
    """H-able이 Excel을 직접 열었다면 그 표를 읽고 Excel을 닫는다.

    이 화면의 내보내기 버튼은 저장 대화상자 대신 Excel을 띄우기도 한다. 그때는
    파일을 찾아 헤맬 것 없이 열려 있는 통합 문서를 그대로 읽는 편이 정확하다.
    다 읽으면 저장하지 않고 닫는다 - 우리가 연 것이니 우리가 치운다.
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError:  # pragma: no cover - 설치 안내
        return None

    pythoncom.CoInitialize()
    try:
        try:
            excel = win32com.client.GetActiveObject("Excel.Application")
        except Exception:
            return None
        try:
            workbook = excel.ActiveWorkbook
            if workbook is None:
                return None
            values = workbook.ActiveSheet.UsedRange.Value
        except Exception:
            return None

        rows = [
            ["" if cell is None else str(cell).strip() for cell in row]
            for row in (values or ())
            if any(cell is not None for cell in row)
        ]
        if close:
            try:
                workbook.Close(SaveChanges=False)
                if excel.Workbooks.Count == 0:
                    excel.Quit()
            except Exception:
                pass
        if not rows:
            return None
        return rows[0], rows[1:]
    finally:
        pythoncom.CoUninitialize()


_CELL_ADDRESS = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


def _column_number(letters: str) -> int:
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - ord("A") + 1
    return value


def table_from_uia_cells(cells: list[tuple[str, str]]) -> tuple[list[str], list[list[str]]]:
    """Excel UIA 셀 `(주소, 값)`을 직사각형 표로 되돌린다."""
    found: dict[tuple[int, int], str] = {}
    max_row = max_column = 0
    for address, value in cells:
        match = _CELL_ADDRESS.fullmatch(address)
        if not match:
            continue
        column = _column_number(match.group(1))
        row = int(match.group(2))
        found[row, column] = value
        max_row = max(max_row, row)
        max_column = max(max_column, column)
    if max_row < 1 or max_column < 1:
        return [], []
    matrix = [
        [found.get((row, column), "").strip() for column in range(1, max_column + 1)]
        for row in range(1, max_row + 1)
    ]
    return matrix[0], [row for row in matrix[1:] if any(row)]


def _excel_roots() -> list[int]:
    return [
        handle for handle in top_level_windows()
        if class_name(handle) == "XLMAIN" and ctypes.windll.user32.IsWindowVisible(handle)
    ]


def read_workbook_via_uia(handle: int) -> tuple[list[str], list[list[str]]] | None:
    """COM을 인증 마법사가 막을 때 Excel의 UIA 셀 값으로 읽는다."""
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Revert to STA COM threading mode")
            from pywinauto import Desktop
    except ImportError:  # pragma: no cover - 설치 안내
        return None
    try:
        workbook = Desktop(backend="uia").window(handle=handle)
        cells = []
        for item in workbook.descendants(control_type="DataItem"):
            address = item.element_info.name or ""
            try:
                value = item.iface_value.CurrentValue or ""
            except Exception:
                continue
            cells.append((address, str(value)))
        headers, rows = table_from_uia_cells(cells)
        return (headers, rows) if headers and rows else None
    except Exception:
        return None


def _close_generated_excel(handle: int, old_processes: set[int]) -> None:
    """이번 내보내기가 새로 만든 Excel만 닫는다."""
    pid = process_id(handle)
    if not pid or pid in old_processes:
        return
    user32 = ctypes.windll.user32
    user32.PostMessageW(handle, WM_CLOSE, 0, 0)
    time.sleep(0.5)
    # 미인증 Office는 종료 요청도 인증 마법사에서 막는다. 이 PID는 내보내기
    # 직전에는 없었고 우리가 만든 통합 문서 하나뿐이므로 남아 있으면 종료한다.
    if any(process_id(root) == pid for root in _excel_roots()):
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
        process = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if process:
            try:
                kernel32.TerminateProcess(process, 0)
            finally:
                kernel32.CloseHandle(process)


def click_point(main_handle: int, screen_handle: int, dx: int, dy: int) -> None:
    """화면 좌상단 기준 상대 좌표를 누른다.

    툴바가 그리드 판에 붙어 있지 않은 화면([0112] 거래내역조회처럼)은
    `click_toolbar`의 "판 오른쪽 끝에서 몇 픽셀" 계산이 통하지 않는다.
    그런 화면은 실측한 좌표를 그대로 넘긴다.
    """
    focus(main_handle)
    left, top, _width, _height = rect(screen_handle)
    x, y = left + dx, top + dy
    ensure_clickable(main_handle, screen_handle, x, y)
    with BorrowedCursor() as cursor:
        cursor.click(x, y, settle=0.8)


def export_grid(
    main_handle: int,
    screen_handle: int,
    pane: Pane,
    folder: Path,
    stem: str = "hable-1285",
    excel_at: tuple[int, int] | None = None,
) -> tuple[list[str], list[list[str]], str]:
    """표를 파일로 꺼낸다. 가벼운 방법부터 차례로 시도한다.

    1. 우클릭 메뉴의 CSV/TXT 저장 - 텍스트 파일 하나만 남고 Excel이 열리지 않는다.
    2. 툴바 엑셀 버튼 → 저장 대화상자 - 파일만 생기고 Excel은 열리지 않는다.
    3. 그래도 Excel이 열렸다면 그 통합 문서를 읽고 저장하지 않고 닫는다.

    되는 것이 없으면 지어내지 않고 멈춘다.
    """
    folder.mkdir(parents=True, exist_ok=True)
    process = process_id(main_handle)
    existing_excel = set(_excel_roots())
    existing_excel_processes = {process_id(handle) for handle in existing_excel}

    through_menu = export_via_menu(main_handle, screen_handle, pane, folder, stem)
    if through_menu is not None:
        return through_menu

    since = time.time()
    if excel_at is None:
        click_toolbar(main_handle, screen_handle, pane, "excel")
    else:
        click_point(main_handle, screen_handle, *excel_at)

    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        for handle in top_level_windows():
            if (
                class_name(handle) == SAVE_DIALOG_CLASS
                and process_id(handle) == process
                and _looks_like_save_dialog(handle)
            ):
                save_as(handle, folder / stem)
                exported = wait_for_export(folder, since)
                headers, rows = read_table(exported)
                return headers, rows, f"툴바 엑셀 저장({exported.name})"
        opened = read_open_workbook()
        if opened is not None:
            headers, rows = opened
            return headers, rows, "Excel 통합 문서(읽고 닫음)"
        for handle in _excel_roots():
            if handle in existing_excel:
                continue
            opened = read_workbook_via_uia(handle)
            if opened is not None:
                headers, rows = opened
                _close_generated_excel(handle, existing_excel_processes)
                return headers, rows, "Excel 접근성 셀(읽고 닫음)"
        time.sleep(0.5)

    raise ExtractionError(
        "내보내기를 세 방법으로 시도했지만 아무것도 나오지 않았습니다.\n"
        "  1) 우클릭 메뉴의 저장 항목  2) 툴바 엑셀 버튼 → 저장 대화상자  3) 열린 Excel\n"
        "`hable-probe`가 남긴 화면 그림에서 버튼 위치를 다시 재 주세요."
    )
