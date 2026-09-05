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
from dataclasses import dataclass

user32 = ctypes.windll.user32
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
