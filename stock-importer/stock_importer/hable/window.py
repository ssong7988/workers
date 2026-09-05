"""H-able 데스크톱 창을 찾고 상태를 확인하는 부분.

전부 stdlib `ctypes`다. H-able은 32비트, 우리 Python은 64비트라 구조체를 건네는
메시지(HDM_GETITEM 같은 것)는 레이아웃이 어긋난다. 그래서 여기서는 **구조체를
주고받지 않는 메시지와 창 정보만** 쓴다.

화면은 MDI 자식이고 제목이 화면번호로 시작한다(`1285 총자산현황`). 그래서 창
제목이 화면을 집는 안정적인 손잡이다 - 좌표로 찾지 않는다. 창 안에서의 위치는
그 창의 클라이언트 좌표로만 계산하므로 해상도나 창 위치가 바뀌어도 견딘다.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import time
from ctypes import POINTER, byref, c_ubyte, c_void_p
from dataclasses import dataclass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32
_ENUM_PROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

user32.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, w.WPARAM, w.LPARAM]
user32.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, w.WPARAM, w.LPARAM]
user32.FindWindowW.restype = w.HWND

MAIN_WINDOW_CLASS = "Hable"
ASSET_SCREEN = "1285"
NOTICE_CLASS = "#32770"
POPUP_MENU_CLASS = "#32768"

WM_SYSCOMMAND = 0x0112
SC_RESTORE = 0xF120
# H-able은 최소화됐을 때 ShowWindow(SW_RESTORE)에 반응하지 않는다. 실측으로
# WM_SYSCOMMAND/SC_RESTORE만 먹혔다.
RESTORE_WAIT_SECONDS = 3.0

# 자동 로그아웃 안내창을 알아보는 글자. 이게 떠 있으면 화면의 숫자는 낡은 것이다.
LOGGED_OUT_HINTS = ("자동 로그아", "로그아웃 되었", "다시 로그인")

WM_CLOSE = 0x0010
# 로그인할 때마다 뜨는 안내 화면들. 대상 화면을 덮으면 클릭이 그쪽으로 간다.
# 제목으로만 고른다 - 사용자가 열어 둔 조회 화면을 함부로 닫지 않기 위해서다.
NOTICE_SCREEN_WORDS = ("공지", "이벤트", "안내", "알림")
# 광고·공지 팝업은 창 안에 WebView2로 웹 내용을 띄운다. 제목은 직접 그려서
# GetWindowText로는 안 잡히므로, 이 구조를 보고 알아본다. 저장 대화상자 같은
# 기능 창은 WebView2를 품지 않는다.
WEB_CONTENT_CLASS = "Chrome_RenderWidgetHostHWND"


class HableError(RuntimeError):
    """H-able 창을 못 찾았거나 상태가 수집할 수 없는 상태일 때."""


@dataclass(frozen=True)
class Pane:
    """화면 안의 사각 영역 하나. 좌표는 그 화면 창 기준의 상대값이다."""

    handle: int
    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


def class_name(handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(handle, buffer, 256)
    return buffer.value


def window_text(handle: int) -> str:
    length = user32.GetWindowTextLengthW(handle)
    buffer = ctypes.create_unicode_buffer(length + 2)
    user32.GetWindowTextW(handle, buffer, length + 2)
    return buffer.value


def rect(handle: int) -> tuple[int, int, int, int]:
    """화면 좌표의 (left, top, width, height)."""
    box = w.RECT()
    user32.GetWindowRect(handle, ctypes.byref(box))
    return box.left, box.top, box.right - box.left, box.bottom - box.top


def descendants(handle: int) -> list[int]:
    found: list[int] = []
    user32.EnumChildWindows(handle, _ENUM_PROC(lambda h, _l: found.append(h) or True), 0)
    return found


def top_level_windows() -> list[int]:
    found: list[int] = []
    user32.EnumWindows(_ENUM_PROC(lambda h, _l: found.append(h) or True), 0)
    return found


def process_id(handle: int) -> int:
    value = w.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(value))
    return value.value


def main_window() -> int:
    handle = user32.FindWindowW(MAIN_WINDOW_CLASS, None)
    if not handle:
        raise HableError(
            "H-able이 실행돼 있지 않습니다.\n"
            "C:\\KB증권\\hable\\hablerun.exe 를 실행해 로그인한 뒤 다시 시도하세요."
        )
    return handle


def ensure_restored(handle: int) -> bool:
    """최소화돼 있으면 복원한다. 복원을 실제로 했으면 True."""
    if not user32.IsIconic(handle):
        return False
    user32.PostMessageW(handle, WM_SYSCOMMAND, SC_RESTORE, 0)
    deadline = time.monotonic() + RESTORE_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not user32.IsIconic(handle):
            return True
        time.sleep(0.2)
    raise HableError(
        "H-able 창이 최소화돼 있는데 복원되지 않았습니다. 작업표시줄에서 직접 열어 주세요."
    )


def find_screen(main: int, number: str = ASSET_SCREEN) -> int:
    """화면번호로 시작하는 MDI 자식 창을 찾는다."""
    for handle in descendants(main):
        if window_text(handle).startswith(number):
            return handle
    raise HableError(
        f"H-able에서 [{number}] 화면을 찾지 못했습니다.\n"
        f"화면번호 입력창에 {number}를 넣어 화면을 열어 둔 뒤 다시 시도하세요."
    )


def panes(screen: int, *, min_width: int = 380, min_height: int = 150) -> list[Pane]:
    """화면 안의 큰 사각 영역들을 넓은 순으로. 그리드를 여기서 고른다."""
    left, top, _width, _height = rect(screen)
    found: list[Pane] = []
    for handle in descendants(screen):
        if class_name(handle) != "AfxWnd120" or not user32.IsWindowVisible(handle):
            continue
        x, y, width, height = rect(handle)
        if width >= min_width and height >= min_height:
            found.append(Pane(handle, x - left, y - top, width, height))
    found.sort(key=lambda pane: -pane.area)
    return found


def notice_dialogs(process: int) -> list[int]:
    """H-able이 띄운 안내창들. 툴바를 가리기도 하고 로그아웃을 알리기도 한다."""
    return [
        handle
        for handle in top_level_windows()
        if class_name(handle) == NOTICE_CLASS
        and user32.IsWindowVisible(handle)
        and process_id(handle) == process
    ]


def visible_popup_menus() -> list[int]:
    return [
        handle
        for handle in top_level_windows()
        if class_name(handle) == POPUP_MENU_CLASS and user32.IsWindowVisible(handle)
    ]


def dialog_labels(handle: int) -> list[str]:
    """안내창 안에서 글자를 가진 컨트롤들. 본문은 대개 그려지므로 버튼만 잡힌다."""
    labels = []
    for child in descendants(handle):
        text = window_text(child).strip()
        if text:
            labels.append(text)
    return labels


# ------------------------------------------------------------------ 권한

# Windows UIPI는 **낮은 권한 프로세스가 높은 권한 창에 보내는 입력과 메시지를
# 전부 버린다.** 오류도 나지 않고 그냥 아무 일도 일어나지 않는다. H-able은
# 관리자 권한으로 도는 경우가 있어서, 이걸 먼저 확인하지 않으면 클릭이 안 먹는
# 것을 좌표가 틀린 것으로 오해하게 된다 - 실제로 그렇게 한참을 헤맸다.
#
# 읽기는 막히지 않는다. 창 제목(WM_GETTEXT)과 위치·구조는 그대로 보인다.
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INTEGRITY_NAMES = {
    0x0000: "Untrusted",
    0x1000: "Low",
    0x2000: "Medium",
    0x2100: "Medium+",
    0x3000: "High(관리자 권한)",
    0x4000: "System",
}

kernel32.GetCurrentProcess.restype = w.HANDLE
kernel32.OpenProcess.restype = w.HANDLE
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
advapi32.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, POINTER(w.HANDLE)]
advapi32.GetTokenInformation.argtypes = [
    w.HANDLE, ctypes.c_int, c_void_p, w.DWORD, POINTER(w.DWORD)
]
advapi32.GetSidSubAuthorityCount.restype = POINTER(c_ubyte)
advapi32.GetSidSubAuthorityCount.argtypes = [c_void_p]
advapi32.GetSidSubAuthority.restype = POINTER(w.DWORD)
advapi32.GetSidSubAuthority.argtypes = [c_void_p, w.DWORD]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", c_void_p), ("Attributes", w.DWORD)]


def _integrity_of(process_handle: int) -> int | None:
    token = w.HANDLE()
    if not advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, byref(token)):
        return None
    size = w.DWORD()
    advapi32.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, None, 0, byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    if not advapi32.GetTokenInformation(
        token, TOKEN_INTEGRITY_LEVEL, buffer, size, byref(size)
    ):
        return None
    label = ctypes.cast(buffer, POINTER(_SidAndAttributes)).contents
    count = advapi32.GetSidSubAuthorityCount(label.Sid).contents.value
    return advapi32.GetSidSubAuthority(label.Sid, count - 1).contents.value


def integrity_levels(main: int) -> tuple[int | None, int | None]:
    """(우리, H-able)의 무결성 수준. 못 읽으면 None."""
    ours = _integrity_of(kernel32.GetCurrentProcess())
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, process_id(main)
    )
    theirs = _integrity_of(handle) if handle else None
    return ours, theirs


def ensure_input_allowed(main: int) -> None:
    """우리가 H-able에 입력을 보낼 수 있는지 먼저 확인한다.

    보낼 수 없으면 클릭도 키보드도 창 메시지도 조용히 사라진다. 그 상태로
    진행하면 원인을 엉뚱한 데서 찾게 되므로 여기서 멈춘다.
    """
    ours, theirs = integrity_levels(main)
    if ours is None or theirs is None or ours >= theirs:
        return
    raise HableError(
        "H-able이 우리보다 높은 권한으로 실행 중이라 클릭과 키 입력이 차단됩니다"
        f"(H-able {INTEGRITY_NAMES.get(theirs, hex(theirs))}, "
        f"수집기 {INTEGRITY_NAMES.get(ours, hex(ours))}).\n"
        "Windows UIPI는 낮은 권한에서 높은 권한 창으로 가는 입력을 오류 없이 버립니다.\n"
        "둘 중 하나로 맞추세요:\n"
        "  - H-able을 관리자 권한 없이 실행한다(권장 - 수집기가 계속 일반 권한으로 돈다).\n"
        "    hablerun.exe 속성 → 호환성 → '관리자 권한으로 이 프로그램 실행'을 끈다.\n"
        "  - 또는 이 수집기를 관리자 권한 콘솔에서 실행한다."
    )


def covering_screens(main: int, screen: int) -> dict[int, str]:
    """대상 화면의 주요 지점을 덮고 있는 형제 MDI 화면들을 {핸들: 제목}으로."""
    parent = user32.GetParent(screen)
    left, top, width, height = rect(screen)
    points = (
        (left + width // 2, top + height // 2),
        (left + width // 2, top + int(height * 0.75)),
        (left + width - 40, top + int(height * 0.66)),
    )
    found: dict[int, str] = {}
    for x, y in points:
        under = user32.WindowFromPoint(w.POINT(x, y))
        if not under or under == screen or user32.IsChild(screen, under):
            continue
        node = under
        while node and user32.GetParent(node) != parent:
            node = user32.GetParent(node)
        if node and node != screen:
            found[node] = window_text(node)
    return found


def clear_notice_screens(main: int, screen: int, *, rounds: int = 4) -> list[str]:
    """대상 화면을 덮은 로그인 안내 화면들을 닫는다. 닫은 제목들을 돌려준다.

    안내가 아닌 화면이 덮고 있으면 닫지 않고 그대로 알린다 - 사용자가 보려고
    열어 둔 조회 화면을 우리가 치울 일은 아니다.
    """
    closed: list[str] = []
    for _round in range(rounds):
        covering = covering_screens(main, screen)
        if not covering:
            return closed
        notices = {
            handle: title
            for handle, title in covering.items()
            if any(word in title for word in NOTICE_SCREEN_WORDS)
        }
        if not notices:
            names = ", ".join(sorted(covering.values())) or "이름 없는 창"
            raise HableError(
                f"[{window_text(screen)}] 화면이 다른 화면에 가려 있습니다: {names}\n"
                "안내 화면이 아니라 함부로 닫지 않았습니다. 직접 닫거나 앞으로 꺼내 주세요."
            )
        for handle, title in notices.items():
            user32.PostMessageW(handle, WM_CLOSE, 0, 0)
            closed.append(title)
        time.sleep(0.8)
    remaining = covering_screens(main, screen)
    if remaining:
        raise HableError(
            "안내 화면을 닫았는데도 대상 화면이 가려 있습니다: "
            + ", ".join(sorted(remaining.values()))
        )
    return closed


def _intersects(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def hosts_web_content(handle: int) -> bool:
    return any(class_name(child) == WEB_CONTENT_CLASS for child in descendants(handle))


def covering_dialogs(main: int, screen: int) -> dict[int, str]:
    """대상 화면을 덮은 H-able의 최상위 팝업들을 {핸들: 설명}으로.

    MDI 자식이 아니라 별도 최상위 창이라 `clear_notice_screens()`가 놓친다.
    광고 팝업이 딱 이 모양이다 - always-on-top이라 z-order를 아무리 올려도
    그 아래로 안 내려간다. 닫는 수밖에 없다.
    """
    process = process_id(main)
    box = rect(screen)
    found: dict[int, str] = {}
    for handle in top_level_windows():
        if handle == main or not user32.IsWindowVisible(handle):
            continue
        if process_id(handle) != process:
            continue
        if not _intersects(box, rect(handle)):
            continue
        labels = " ".join(dialog_labels(handle))
        if hosts_web_content(handle):
            found[handle] = f"웹 팝업 {rect(handle)}"
        elif any(word in labels for word in NOTICE_SCREEN_WORDS):
            found[handle] = labels[:60]
    return found


def clear_covering_dialogs(main: int, screen: int, *, rounds: int = 3) -> list[str]:
    """그 팝업들을 닫는다. 닫은 것들의 설명을 돌려준다."""
    closed: list[str] = []
    for _round in range(rounds):
        covering = covering_dialogs(main, screen)
        if not covering:
            break
        for handle, description in covering.items():
            user32.PostMessageW(handle, WM_CLOSE, 0, 0)
            closed.append(description)
        time.sleep(0.8)
    return closed
