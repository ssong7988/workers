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
from dataclasses import dataclass
from pathlib import Path

from .window import Pane, process_id, rect, visible_popup_menus

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
VK_CONTROL, VK_C, VK_ESCAPE, VK_MENU = 0x11, 0x43, 0x1B, 0x12
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
MN_GETHMENU = 0x01E1
MF_BYPOSITION = 0x0400
OBJID_CLIENT = 0xFFFFFFFC
GA_ROOT = 2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
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


@dataclass(frozen=True)
class MenuItem:
    """팝업 메뉴의 항목 하나. 좌표를 알면 이름 대신 그 자리를 누르면 된다."""

    name: str
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0

    @property
    def clickable(self) -> bool:
        return self.width > 0 and self.height > 0

    @property
    def centre(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2


def _menu_items_via_win32(handle: int) -> list[MenuItem]:
    """`MN_GETHMENU`로 HMENU를 얻어 항목 이름을 읽는다.

    HMENU는 만든 프로세스의 것이라 남의 메뉴에서는 실패하는 편이다. 성공하면
    제일 싸므로 먼저 해 본다.
    """
    menu = user32.SendMessageW(handle, MN_GETHMENU, 0, 0)
    if not menu:
        return []
    count = user32.GetMenuItemCount(menu)
    if count <= 0:
        return []
    items: list[MenuItem] = []
    for index in range(count):
        length = user32.GetMenuStringW(menu, index, None, 0, MF_BYPOSITION)
        if length <= 0:
            continue
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetMenuStringW(menu, index, buffer, length + 1, MF_BYPOSITION)
        name = buffer.value.strip()
        if name:
            items.append(MenuItem(name=name))
    return items


def _menu_items_via_msaa(handle: int) -> list[MenuItem]:
    """MSAA로 읽는다. 메뉴는 MSAA가 가장 잘 지원하는 객체다.

    좌표까지 나오므로 이름으로 찾은 항목을 그 자리에서 바로 누를 수 있다.
    """
    try:
        import comtypes.client
        from comtypes import COMError
        from comtypes.automation import VARIANT
    except ImportError:  # pragma: no cover - 설치 안내
        return []
    try:
        comtypes.client.GetModule("oleacc.dll")
        from comtypes.gen.Accessibility import IAccessible
    except Exception:
        return []

    oleacc = ctypes.oledll.oleacc
    accessible = ctypes.POINTER(IAccessible)()
    guid = comtypes.GUID("{618736E0-3C3D-11CF-810C-00AA00389B71}")  # IID_IAccessible
    try:
        oleacc.AccessibleObjectFromWindow(
            handle, OBJID_CLIENT, ctypes.byref(guid), ctypes.byref(accessible)
        )
    except OSError:
        return []

    items: list[MenuItem] = []
    try:
        count = accessible.accChildCount
    except COMError:
        return []
    for index in range(1, count + 1):
        child = VARIANT()
        child.vt = 3  # VT_I4
        child.value = index
        try:
            name = accessible.accName(child)
        except COMError:
            continue
        if not name or not name.strip():
            continue  # 구분선은 이름이 없다
        left = top = width = height = 0
        try:
            left, top, width, height = accessible.accLocation(child)
        except COMError:
            pass
        items.append(
            MenuItem(name=name.strip(), left=left, top=top, width=width, height=height)
        )
    return items


def read_menu_items(handle: int) -> list[MenuItem]:
    """뜬 팝업 메뉴의 항목들. 못 읽으면 빈 목록.

    여기서 '복사'나 'CSV 저장' 같은 항목이 보이면 Excel을 열지 않고도 표를
    꺼낼 수 있다. 그게 이 함수가 있는 이유다.
    """
    for reader in (_menu_items_via_msaa, _menu_items_via_win32):
        try:
            items = reader(handle)
        except Exception:
            continue
        if items:
            return items
    return []


def click_menu_item(item: MenuItem) -> bool:
    """메뉴 항목을 그 자리에서 누른다. 좌표를 모르면 누르지 않는다."""
    if not item.clickable:
        return False
    x, y = item.centre
    with BorrowedCursor() as cursor:
        cursor.click(x, y, settle=1.0)
    return True


def point_in(screen_handle: int, pane: Pane, dx: int, dy: int) -> tuple[int, int]:
    """화면 창 기준 상대 좌표를 실제 화면 좌표로."""
    left, top, _width, _height = rect(screen_handle)
    return left + pane.x + dx, top + pane.y + dy


def focus(main_handle: int, *, wait_seconds: float = 2.0) -> bool:
    """H-able을 클릭이 닿는 자리로 올린다. 활성화까지 됐으면 True.

    **매번 z-order를 다시 올린다.** 항상 위에 뜨는 창(광고 오버레이 같은 것)이
    있으면 한 번 올려둔 것으로는 부족하다 - topmost끼리는 나중에 올린 쪽이
    위로 가므로, 누르기 직전에 다시 올려야 우리 클릭이 닿는다.

    활성화(`SetForegroundWindow`)는 실패해도 넘어간다. Windows는 포그라운드 창을
    가진 프로세스가 아니면 자주 거절하고(작업 스케줄러가 띄운 프로세스는 특히),
    클릭이 어디로 갈지 정하는 것은 활성 창이 아니라 z-order다.
    """
    process = process_id(main_handle)
    pin_to_top(main_handle)

    # 최근에 입력을 받은 프로세스에만 포그라운드 전환이 허용된다. ALT를 살짝
    # 눌렀다 떼면 그 조건을 만족한다 - 널리 쓰는 우회다.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)
    user32.SetForegroundWindow(main_handle)

    front = user32.GetForegroundWindow()
    if front and process_id(front) != process:
        our_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        their_thread = user32.GetWindowThreadProcessId(main_handle, None)
        if user32.AttachThreadInput(our_thread, their_thread, True):
            try:
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
    time.sleep(0.3)
    return False


def belongs_to_screen(handle: int, screen: int) -> bool:
    """그 창이 대상 화면(1285) 안의 것인지."""
    return bool(handle) and (handle == screen or bool(user32.IsChild(screen, handle)))


def ensure_clickable(main_handle: int, screen_handle: int, x: int, y: int) -> None:
    """그 점이 대상 화면의 것이 될 때까지 가리는 것을 치우고 올린다.

    **'H-able의 창인가'로는 부족하다.** H-able은 자기 화면을 여러 개 겹쳐 띄우고,
    로그인할 때마다 이벤트·공지 화면이 대상 화면 위를 덮는다. 그것도 H-able의
    창이라 프로세스만 보면 통과해 버리고, 클릭은 툴바가 아니라 이벤트 화면으로
    간다. 실제로 그렇게 한참 헛돌았다.
    """
    from .window import clear_covering_dialogs, clear_notice_screens

    for attempt in range(3):
        if belongs_to_screen(user32.WindowFromPoint(w.POINT(x, y)), screen_handle):
            return
        if attempt == 0:
            clear_covering_dialogs(main_handle, screen_handle)
            clear_notice_screens(main_handle, screen_handle, rounds=2)
        pin_to_top(main_handle)
        user32.BringWindowToTop(screen_handle)
        time.sleep(0.5 * (attempt + 1))

    under = user32.WindowFromPoint(w.POINT(x, y))
    raise ExtractionError(
        f"({x},{y})가 [{window_title(screen_handle)}]의 자리가 아닙니다. "
        f"덮고 있는 창: {describe_window(under)}\n"
        "그 창을 닫거나 최소화한 뒤 다시 실행하세요."
    )


def window_title(handle: int) -> str:
    from .window import window_text

    return window_text(handle)


def pin_to_top(handle: int) -> None:
    """창을 다른 창들 위로 올린다(활성화는 하지 않는다).

    `SetForegroundWindow`는 포그라운드 창을 가진 프로세스가 아니면 Windows가
    자주 거절한다 - 작업 스케줄러가 띄운 프로세스는 특히 그렇다. 그런데 클릭이
    어디로 갈지 정하는 것은 활성 창이 아니라 z-order다. 그래서 활성화를 포기하고
    z-order만 올린다. 이건 거절당하지 않는다.

    끝나면 `unpin()`으로 되돌린다. 사용자 화면에 H-able이 계속 맨 위로 떠 있으면
    곤란하다.
    """
    user32.SetWindowPos(
        handle, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )


def unpin(handle: int) -> None:
    user32.SetWindowPos(
        handle, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )


def describe_window(handle: int) -> str:
    """가림 원인을 사람이 알아볼 수 있게 적는다."""
    if not handle:
        return "(창 없음)"
    from .window import class_name, process_id, window_text

    pid = process_id(handle)
    name = ""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = w.HANDLE
        kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        process = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if process:
            size = w.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                name = Path(buffer.value).name
    except Exception:
        pass
    return f"{name or 'pid ' + str(pid)} [{class_name(handle)}] {window_text(handle)[:40]!r}"


def owned_by(handle: int, process: int) -> bool:
    """그 창이 결국 누구 것인지. 최상위 창까지 올라가 판단한다.

    H-able의 광고 팝업은 안에 WebView2를 띄우는데, 그 자식 창은 별도 프로세스
    (msedgewebview2.exe) 소유다. 자식만 보면 남의 창으로 오해한다.
    """
    if not handle:
        return False
    from .window import process_id

    if process_id(handle) == process:
        return True
    root = user32.GetAncestor(handle, GA_ROOT)
    return bool(root) and process_id(root) == process


def guard_target(x: int, y: int, process: int) -> None:
    """그 점에 실제로 H-able이 있는지 확인한다.

    없는데도 누르면 위에 떠 있는 남의 창을 클릭하게 된다. 한 번 겪었다 -
    캡처에 편집기가 찍혔고 클립보드는 비어 있었다. 눈감고 클릭하지 않는다.
    무엇이 가리는지 이름까지 적어야 사람이 치울 수 있다.
    """
    from .window import process_id

    under = user32.WindowFromPoint(w.POINT(x, y))
    if not owned_by(under, process):
        raise ExtractionError(
            f"({x},{y}) 위에 H-able이 아니라 다른 창이 있습니다: {describe_window(under)}"
            "\n그 창을 치우거나 최소화한 뒤 다시 실행하세요."
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
    ensure_clickable(main_handle, screen_handle, x, y)
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
    ensure_clickable(main_handle, screen_handle, x, y)
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
    ensure_clickable(main_handle, handle, left + width // 2, top + height // 2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_png(destination, width, height, _grab_pixels(left, top, width, height))
    return destination
