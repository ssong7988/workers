"""1285 그리드에서 값을 꺼내는 방법들과, 화면을 눈으로 확인할 수단.

셀 글자는 Win32로도 UIA로도 읽을 수 없다(자식 창이 아니라 그려진 그림이다).
그래서 H-able 자신의 내보내기 기능을 눌러 그 결과를 받는 수밖에 없다. 어느
방법이 실제로 먹히는지는 화면마다 다르므로 순서대로 시도하고, 되는 것이 없으면
지어내지 않고 멈춘다.

클릭은 전부 **그 화면 창 기준의 상대 좌표**로 계산한다. 창을 옮기거나 해상도가
바뀌어도 같은 자리를 누른다.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import struct
import time
import zlib
from pathlib import Path

from .window import Pane, process_id, rect, visible_popup_menus

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
VK_CONTROL, VK_C, VK_ESCAPE, VK_MENU = 0x11, 0x43, 0x1B, 0x12
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
SRCCOPY = 0x00CC0020


class ExtractionError(RuntimeError):
    """값을 꺼내지 못했을 때."""


# ----------------------------------------------------------------- 클립보드


def read_clipboard() -> str:
    """클립보드의 유니코드 텍스트. 비어 있으면 빈 문자열."""
    if not user32.OpenClipboard(None):
        raise ExtractionError("클립보드를 열지 못했습니다. 다른 프로그램이 잡고 있습니다.")
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.c_wchar_p(pointer).value or ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def clear_clipboard() -> None:
    """복사가 실제로 일어났는지 알려면 먼저 비워야 한다."""
    if not user32.OpenClipboard(None):
        raise ExtractionError("클립보드를 열지 못했습니다.")
    try:
        user32.EmptyClipboard()
    finally:
        user32.CloseClipboard()


# ----------------------------------------------------------------- 입력


def _cursor() -> tuple[int, int]:
    point = w.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


class BorrowedCursor:
    """마우스를 잠깐 빌리고 원래 자리에 돌려놓는다.

    PostMessage로 보낸 마우스 메시지는 이 그리드에 먹히지 않는다(실측). 실제
    커서를 옮기는 수밖에 없으므로, 최소한 쓰던 자리는 돌려준다.
    """

    def __enter__(self) -> "BorrowedCursor":
        self._saved = _cursor()
        return self

    def __exit__(self, *_exc) -> None:
        user32.SetCursorPos(*self._saved)

    @staticmethod
    def click(x: int, y: int, *, right: bool = False, settle: float = 0.4) -> None:
        user32.SetCursorPos(x, y)
        time.sleep(0.2)
        down = MOUSEEVENTF_RIGHTDOWN if right else MOUSEEVENTF_LEFTDOWN
        up = MOUSEEVENTF_RIGHTUP if right else MOUSEEVENTF_LEFTUP
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.1)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(settle)


def press_copy() -> None:
    """Ctrl+C. 포커스가 그리드에 있어야 한다."""
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    time.sleep(0.08)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def close_popup_menus() -> None:
    for handle in visible_popup_menus():
        user32.PostMessageW(handle, 0x0100, VK_ESCAPE, 0)
    time.sleep(0.3)


def read_menu_items(handle: int) -> list[str]:
    """뜬 팝업 메뉴의 항목 이름들. 못 읽으면 빈 목록.

    메뉴는 그려진 그림이 아니라 접근성 트리에 이름이 있다. 여기서 '복사'나
    '엑셀 저장' 같은 항목이 보이면 그 경로를 쓸 수 있다.
    """
    try:
        from pywinauto import Desktop

        window = Desktop(backend="uia").window(handle=handle)
        names = [
            item.window_text().strip()
            for item in window.descendants(control_type="MenuItem")
        ]
        return [name for name in names if name]
    except Exception:
        return []


def point_in(screen_handle: int, pane: Pane, dx: int, dy: int) -> tuple[int, int]:
    """화면 창 기준 상대 좌표를 실제 화면 좌표로."""
    left, top, _width, _height = rect(screen_handle)
    return left + pane.x + dx, top + pane.y + dy


def focus(main_handle: int, *, wait_seconds: float = 2.0) -> bool:
    """H-able을 맨 앞으로 올려 본다. 올렸으면 True.

    실패해도 멈추지 않는다. 클릭이 어디로 가는지를 정하는 것은 포그라운드가
    아니라 그 지점의 z-order이고, 그건 `guard_target()`이 실제로 확인한다.
    Windows는 포그라운드 창을 가진 프로세스가 아니면 `SetForegroundWindow`를
    자주 거절하므로(최소화된 콘솔에서 시작하면 특히), 여기서 실패를 이유로
    수집을 포기하면 될 일도 안 된다.

    스레드 입력을 잠깐 붙였다 떼는 것은 그 거절을 우회하는 표준 방법이다.
    """
    process = process_id(main_handle)
    # Windows는 최근에 입력을 받은 프로세스에만 포그라운드 전환을 허용한다.
    # ALT를 살짝 눌렀다 떼면 그 조건을 만족한다 - 널리 쓰는 우회다.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)
    user32.BringWindowToTop(main_handle)
    user32.SetForegroundWindow(main_handle)

    front = user32.GetForegroundWindow()
    if front and process_id(front) != process:
        our_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        their_thread = user32.GetWindowThreadProcessId(main_handle, None)
        if user32.AttachThreadInput(our_thread, their_thread, True):
            try:
                user32.BringWindowToTop(main_handle)
                user32.SetForegroundWindow(main_handle)
            finally:
                user32.AttachThreadInput(our_thread, their_thread, False)

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        front = user32.GetForegroundWindow()
        if front and process_id(front) == process:
            time.sleep(0.3)
            return True
        time.sleep(0.2)
    return False


def guard_target(x: int, y: int, process: int) -> None:
    """그 점에 실제로 H-able이 있는지 확인한다.

    없는데도 누르면 위에 떠 있는 남의 창을 클릭하게 된다. 한 번 겪었다 -
    캡처에 편집기가 찍혔고 클립보드는 비어 있었다. 눈감고 클릭하지 않는다.
    """
    point = w.POINT(x, y)
    under = user32.WindowFromPoint(point)
    if not under or process_id(under) != process:
        raise ExtractionError(
            f"({x},{y}) 위에 H-able이 없습니다(다른 창이 가리고 있습니다). "
            "H-able 창을 앞으로 꺼내 놓고 다시 실행하세요."
        )


# ----------------------------------------------------------------- 꺼내기


def copy_grid(
    main_handle: int, screen_handle: int, pane: Pane, *, wait_seconds: float = 2.0
) -> str:
    """그리드를 눌러 포커스를 주고 Ctrl+C 한 뒤 클립보드를 읽는다.

    클립보드를 먼저 비우므로, 아무것도 안 돌아오면 복사가 안 된 것이지 예전
    내용을 읽은 것이 아니다.
    """
    clear_clipboard()
    focus(main_handle)
    x, y = point_in(screen_handle, pane, pane.width // 3, min(40, pane.height // 3))
    guard_target(x, y, process_id(main_handle))
    with BorrowedCursor() as cursor:
        cursor.click(x, y)
        press_copy()
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        text = read_clipboard()
        if text.strip():
            return text
        time.sleep(0.2)
    return ""


def open_context_menu(main_handle: int, screen_handle: int, pane: Pane) -> list[int]:
    """그리드에서 우클릭하고 뜬 팝업 메뉴 창들을 돌려준다(없으면 빈 목록)."""
    focus(main_handle)
    x, y = point_in(screen_handle, pane, pane.width // 3, min(40, pane.height // 3))
    guard_target(x, y, process_id(main_handle))
    with BorrowedCursor() as cursor:
        cursor.click(x, y, right=True, settle=1.2)
    return visible_popup_menus()


# ----------------------------------------------------------------- 눈으로 보기


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", w.WORD),
        ("biBitCount", w.WORD),
        ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


def _grab_pixels(left: int, top: int, width: int, height: int) -> bytes:
    """화면의 사각 영역을 32비트 BGRA 바이트로. 위에서 아래 순서다."""
    gdi32 = ctypes.windll.gdi32
    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    header = _BitmapInfoHeader()
    header.biSize = ctypes.sizeof(_BitmapInfoHeader)
    header.biWidth = width
    header.biHeight = -height  # 음수 = 위에서 아래로. 뒤집을 일이 없어진다.
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0  # BI_RGB
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(
        memory_dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0
    )
    try:
        if not bitmap or not bits:
            raise ExtractionError("화면 버퍼를 만들지 못했습니다.")
        old = gdi32.SelectObject(memory_dc, bitmap)
        if not gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, left, top, SRCCOPY):
            raise ExtractionError("화면을 복사하지 못했습니다.")
        gdi32.SelectObject(memory_dc, old)
        return ctypes.string_at(bits, width * height * 4)
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)


def _write_png(path: Path, width: int, height: int, bgra: bytes) -> None:
    """BGRA 바이트를 PNG로 쓴다.

    이미지 라이브러리를 새로 들이지 않으려고 직접 쓴다. PNG는 zlib으로 누른
    스캔라인과 CRC를 붙인 청크 몇 개가 전부다.
    """
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        row = bgra[y * stride : (y + 1) * stride]
        rgb = bytearray(width * 3)
        rgb[0::3] = row[2::4]
        rgb[1::3] = row[1::4]
        rgb[2::3] = row[0::4]
        raw.append(0)  # 필터 없음
        raw += rgb

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        # PNG 서명. 이스케이프 없이 바이트로 적는다.
        bytes([137, 80, 78, 71, 13, 10, 26, 10])
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def capture(main_handle: int, handle: int, destination: Path) -> Path:
    """창을 PNG로 저장한다. 화면 구조를 사람이 확인할 때만 쓴다.

    `PrintWindow`로 창이 스스로를 그리게 해 보았지만 이 앱은 거절한다(MDI 자식도
    최상위 창도 실패). 그래서 화면을 긁는 수밖에 없는데, 그러면 **위에 떠 있는
    다른 창이 찍힌다** - 한 번 겪었다(편집기가 찍혔다). 그래서 긁기 전에 H-able을
    맨 앞으로 올리고, 그 자리에 정말 H-able이 있는지 확인한다.

    저장 위치는 Git에서 제외된 `data/` 아래다 - 계좌번호와 잔고가 찍힌 그림이므로
    저장소에 들어가면 안 된다.
    """
    focus(main_handle)
    left, top, width, height = rect(handle)
    if width <= 0 or height <= 0:
        raise ExtractionError("창 크기를 읽지 못했습니다. 최소화돼 있지 않은지 확인하세요.")
    guard_target(left + width // 2, top + height // 2, process_id(main_handle))
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_png(destination, width, height, _grab_pixels(left, top, width, height))
    return destination
