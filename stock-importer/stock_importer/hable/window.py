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
SC_MINIMIZE = 0xF020
WM_MDIACTIVATE = 0x0222
# H-able은 최소화됐을 때 ShowWindow(SW_RESTORE)에 반응하지 않는다. 실측으로
# WM_SYSCOMMAND/SC_RESTORE만 먹혔다.
RESTORE_WAIT_SECONDS = 3.0

# 자동 로그아웃 안내창을 알아보는 글자. 이게 떠 있으면 화면의 숫자는 낡은 것이다.
LOGGED_OUT_HINTS = ("자동 로그아", "로그아웃 되었", "다시 로그인")

WM_CLOSE = 0x0010
# 화면번호 입력창. 기본메뉴바 안의 표준 `Edit` 하나다 - H-able의 다른 컨트롤은
# 전부 직접 그린 `AfxWnd120`이라, 이 클래스가 그대로 손잡이가 된다.
MENU_BAR = "기본메뉴바"
EDIT_CLASS = "Edit"
# 조회 화면(MDI 자식)의 클래스는 전부 이걸로 시작한다. 제목만으로 고르면
# **화면번호를 넣은 입력창이 제 이름을 갖게 되어** 화면으로 잡힌다 - 실제로
# 자동 열기를 붙이자마자 `1285`라고 적힌 입력창을 화면으로 착각했다.
SCREEN_CLASS_PREFIX = "Afx:"
WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_RETURN = 0x0D
# 번호를 넣고 화면이 뜰 때까지. 서버를 한 번 다녀오므로 즉시 열리지 않는다.
SCREEN_OPEN_TIMEOUT = 12.0
# 로그인할 때마다 뜨는 안내 화면들. 대상 화면을 덮으면 클릭이 그쪽으로 간다.
# 제목으로만 고른다 - 사용자가 열어 둔 조회 화면을 함부로 닫지 않기 위해서다.
NOTICE_SCREEN_WORDS = ("공지", "이벤트", "안내", "알림")
# 광고·공지 팝업은 창 안에 WebView2로 웹 내용을 띄운다. 제목은 직접 그려서
# GetWindowText로는 안 잡히므로, 이 구조를 보고 알아본다. 저장 대화상자 같은
# 기능 창은 WebView2를 품지 않는다.
WEB_CONTENT_CLASS = "Chrome_RenderWidgetHostHWND"


class HableError(RuntimeError):
    """H-able 창을 못 찾았거나 상태가 수집할 수 없는 상태일 때."""


class AccountPasswordRequired(HableError):
    """계좌 조회 인증이 필요하다. 좌표 오류와 구분한다."""


class HableNotRunning(HableError):
    """프로그램 자체가 떠 있지 않다."""


class ScreenNotOpen(HableError):
    """프로그램은 떠 있는데 그 화면이 열려 있지 않다."""


class LoggedOut(HableError):
    """세션이 끊겼다. 화면에 남은 숫자는 낡은 값이다."""


class BlockedByDialog(HableError):
    """모달 대화상자가 H-able 본창을 막고 있다.

    좌표나 화면 상태 문제와 구분한다 - 이 상태에서는 화면 열기도 클릭도 되지
    않으므로 다른 진단을 더 해 봐야 소용이 없다.
    """


ACCOUNT_PASSWORD_HELP = (
    "H-able 계좌 비밀번호 입력/저장이 필요합니다.\n"
    "H-able 환경설정 → 보안설정 → 계좌설정에서 계좌비밀번호를 저장한 뒤 "
    "[1285] 총자산현황을 조회하세요. 비밀번호는 H-able에만 입력하세요."
)


def raise_for_auth_dialog(handle: int) -> None:
    """인증을 요구하는 안내창이면 그에 맞는 예외를 올린다.

    이 두 창은 **닫아서 될 일이 아니다.** 닫으면 사람이 고쳐야 할 상태를
    감추게 되고, 다음 단계에서 엉뚱한 실패로 나타난다.
    """
    # 입력 컨트롤의 값은 진단 문구에도 포함하지 않는다.
    labels = " ".join(
        window_text(child) for child in descendants(handle)
        if class_name(child) == "Static"
    )
    if any(hint in labels for hint in LOGGED_OUT_HINTS):
        raise LoggedOut("H-able이 로그아웃되었습니다. 다시 로그인한 뒤 실행하세요.")
    if "비밀번호" in labels:
        raise AccountPasswordRequired(ACCOUNT_PASSWORD_HELP)


def ensure_query_ready(main: int, screen: int) -> None:
    """인증 팝업을 가림창으로 오인하거나 닫지 않는다. 읽기만 수행한다."""
    for handle in notice_dialogs(process_id(main)):
        raise_for_auth_dialog(handle)
    # 계좌 비밀번호가 아닌 모달은 여기서 그 창을 지목한다. 예전에는 무슨 창이
    # 막고 있는지 말하지 못한 채 비밀번호 안내만 덧붙여 엉뚱한 곳을 보게 했다.
    ensure_not_blocked(main)
    if not user32.IsWindowEnabled(screen):
        raise HableError(
            "H-able 대화상자가 조회 화면을 비활성화했습니다. 열린 대화상자를 확인하세요.\n"
            + ACCOUNT_PASSWORD_HELP
        )


def describe_dialog(handle: int) -> str:
    """대화상자를 사람이 알아볼 수 있게 한 줄로.

    제목이 있으면 제목, 없으면 컨트롤 글자, 그것도 없으면 크기와 위치를 쓴다.
    KB의 필수 안내 팝업처럼 **제목 표시줄을 직접 그리는 창은 `GetWindowText`가
    빈 문자열을 돌려주므로** 제목만으로는 아무것도 말할 수 없다. 그럴 때 자리
    라도 알려 주면 사용자가 화면에서 어느 창인지 찾을 수 있다.
    """
    title = window_text(handle).strip()
    if title:
        return title
    labels = " ".join(dialog_labels(handle)).strip()
    if labels:
        return labels[:60]
    left, top, width, height = rect(handle)
    return f"제목 없는 대화상자 ({width}x{height} @ {left},{top})"


def blocking_dialogs(main: int) -> list[int]:
    """본창을 막고 있는 모달 대화상자들. 막혀 있지 않으면 빈 목록.

    **판단 근거는 제목이 아니라 본창이 비활성이라는 사실이다.** 제목과 본문을
    직접 그리는 팝업은 글자를 하나도 내놓지 않아 이름으로는 걸러지지 않는다.
    본창의 `IsWindowEnabled == False`는 그런 창에도 예외 없이 나타난다.
    """
    if user32.IsWindowEnabled(main):
        return []
    return notice_dialogs(process_id(main))


def ensure_not_blocked(main: int) -> None:
    """모달 대화상자가 떠 있으면 그 창을 지목하고 멈춘다.

    여기서는 닫지 않는다 - 닫는 것은 `dismiss_blocking_dialogs()`의 일이고,
    이 함수는 조회 도중처럼 "우리 동작에 대한 응답일 수 있는" 자리에서 쓴다.
    """
    if user32.IsWindowEnabled(main):
        return
    names = ", ".join(describe_dialog(handle) for handle in blocking_dialogs(main))
    raise BlockedByDialog(
        "H-able 본창이 대화상자에 막혀 있습니다"
        + (f": {names}" if names else " (대화상자를 찾지 못했습니다)")
        + ".\n"
        "이 상태에서는 화면 열기도 클릭도 되지 않습니다. 그 창을 직접 확인해 "
        "닫거나 확인한 뒤 다시 시도하세요."
    )


def dismiss_blocking_dialogs(main: int, *, rounds: int = 3) -> list[str]:
    """본창을 막고 있는 모달을 닫는다. 닫은 것들의 설명을 돌려준다.

    **`WM_CLOSE`만 보낸다. 버튼 좌표를 누르지 않는다.** 이것이 이 함수의 안전
    근거다 - `WM_CLOSE`는 제목줄의 X, 즉 사용자가 `닫기`를 누른 것과 같고,
    무엇에도 동의하지 않는다. 설령 이 창이 주문 확인이었다 해도 결과는 취소이지
    체결이 아니다. 반대로 `필수 안내 확인` 같은 버튼을 좌표로 누르는 것은 우리가
    사용자를 대신해 무언가를 확인해 주는 일이라 하지 않는다.

    KB의 필수 고지 팝업은 매일 로그인 뒤에 다시 뜬다. 사람이 없는 18:30 수집을
    그때마다 실패시키지 않으려면 이걸 우리가 치워야 한다.

    닫히지 않으면 - 닫기를 막아 둔 창이라면 - `BlockedByDialog`로 멈춘다.
    """
    closed: list[str] = []
    for _round in range(rounds):
        blocking = blocking_dialogs(main)
        if not blocking:
            break
        for handle in blocking:
            # 로그인·계좌 비밀번호 안내는 닫지 않는다. 사람이 고쳐야 하는
            # 상태이고, 닫으면 그 사실이 사라진 채 다음 단계에서 다른 얼굴로
            # 실패한다.
            raise_for_auth_dialog(handle)
        for handle in blocking:
            closed.append(describe_dialog(handle))
            user32.PostMessageW(handle, WM_CLOSE, 0, 0)
        time.sleep(0.8)
    ensure_not_blocked(main)
    return closed


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


def find_main_window() -> int:
    """H-able 메인 창 핸들. 실행 중이 아니면 0. 예외를 올리지 않는다."""
    return user32.FindWindowW(MAIN_WINDOW_CLASS, None)


def main_window() -> int:
    handle = find_main_window()
    if not handle:
        raise HableNotRunning(
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


def activate_screen(screen: int) -> None:
    """MDI 자식 화면을 맨 앞으로 올린다.

    화면 여러 개가 겹쳐 있으면 뒤에 있는 화면의 좌표를 눌러도 앞 화면이 받는다.
    최상위 창을 올리는 `pin_to_top`으로는 이걸 못 고친다 - MDI 안쪽의 순서는
    부모인 MDI 클라이언트가 쥐고 있기 때문이다.
    """
    parent = user32.GetParent(screen)
    if parent:
        user32.PostMessageW(parent, WM_MDIACTIVATE, screen, 0)
    user32.BringWindowToTop(screen)
    time.sleep(0.4)


def is_minimized(handle: int) -> bool:
    return bool(user32.IsIconic(handle))


def minimize(handle: int) -> None:
    """다시 내려놓는다. 복원과 같은 경로(`WM_SYSCOMMAND`)를 쓴다."""
    user32.PostMessageW(handle, WM_SYSCOMMAND, SC_MINIMIZE, 0)


def is_screen(handle: int, number: str) -> bool:
    """그 창이 화면번호로 열린 조회 화면인지."""
    return class_name(handle).startswith(SCREEN_CLASS_PREFIX) and window_text(
        handle
    ).startswith(number)


def find_screen(main: int, number: str = ASSET_SCREEN) -> int:
    """화면번호로 시작하는 MDI 자식 창을 찾는다."""
    for handle in descendants(main):
        if is_screen(handle, number):
            return handle
    # 화면이 없는 진짜 이유가 "본창이 모달에 막혀 있어서"일 수 있다. 그때
    # 화면을 열라고 안내하면 열 수 없는 화면을 열려고 하게 된다. 막힌 쪽이
    # 먼저 풀려야 하므로 그것부터 말한다.
    ensure_not_blocked(main)
    raise ScreenNotOpen(
        f"H-able에서 [{number}] 화면을 찾지 못했습니다.\n"
        f"화면번호 입력창에 {number}를 넣어 화면을 열어 둔 뒤 다시 시도하세요."
    )


def screen_number_box(main: int) -> int | None:
    """화면번호를 넣는 입력창. 못 찾으면 None."""
    for bar in descendants(main):
        if window_text(bar) != MENU_BAR:
            continue
        for child in descendants(bar):
            if class_name(child) == EDIT_CLASS and user32.IsWindowVisible(child):
                return child
    return None


def window_at(x: int, y: int) -> int:
    point = w.POINT(x, y)
    user32.WindowFromPoint.argtypes = [w.POINT]
    user32.WindowFromPoint.restype = w.HWND
    return user32.WindowFromPoint(point)


def ensure_point_hits_hable(main: int, point: tuple[int, int], *, wait: float = 3.0) -> None:
    """그 자리를 눌렀을 때 H-able이 받는지 먼저 확인한다.

    실제 커서로 누르므로 **맨 위에 있는 창이 클릭을 가져간다.** H-able이 다른
    창에 가려 있으면 그 창이 클릭과 뒤이은 타이핑을 받는다 - 화면번호가 남의
    편집기에 찍히는 일이다. 실제로 그렇게 될 뻔했다.
    """
    process = process_id(main)
    deadline = time.monotonic() + wait
    while True:
        target = window_at(*point)
        if target and process_id(target) == process:
            return
        if time.monotonic() >= deadline:
            from .extract import describe_window

            raise HableError(
                f"화면번호 칸 자리({point[0]},{point[1]})를 다른 창이 덮고 있어 "
                f"누르지 않았습니다: {describe_window(target)}\n"
                "H-able을 가리는 창을 치우거나 최소화한 뒤 다시 시도하세요."
            )
        time.sleep(0.2)


def open_screen(main: int, number: str = ASSET_SCREEN) -> int:
    """화면번호를 입력해 그 화면을 연다. 열린 화면 핸들을 돌려준다.

    사람 없이 도는 수집이 "화면이 닫혀 있어서" 실패하지 않게 한다. H-able은
    화면을 스스로 닫기도 하고(`화면 종료 안내`), 재로그인 뒤에는 처음부터 안
    열려 있다.

    **조회 화면을 여는 것뿐이다.** 번호를 넣고 Enter를 누르는 것이 전부이며,
    주문이나 설정에 손대지 않는다.
    """
    box = screen_number_box(main)
    if box is None:
        raise ScreenNotOpen(
            f"H-able에서 [{number}] 화면이 닫혀 있는데 화면번호 입력창을 찾지 "
            f"못했습니다.\n화면번호 입력창에 {number}를 넣어 직접 열어 주세요."
        )
    # 이 칸은 메시지를 받지 않는다(실측). `SetWindowTextW`로 글자는 바뀌지만
    # 프로그램이 입력으로 인지하지 않아 Enter가 먹지 않고, `WM_CHAR`는 아예
    # 무시된다. 이 프로그램의 다른 입력칸과 같아서 **진짜 클릭과 진짜 키 입력만**
    # 받는다 - 수집기가 툴바를 누르는 방식 그대로다.
    from .extract import BorrowedCursor, pin_to_top, press_key, type_digits, unpin

    left, top, width, height = rect(box)
    point = (left + width // 2, top + height // 2)
    pin_to_top(main)
    try:
        ensure_point_hits_hable(main, point)
        # 남은 글자에 이어 붙지 않게 먼저 비운다. Ctrl+A/Delete는 이 콤보에서
        # 듣지 않아 실측으로 `1285114`가 됐다.
        user32.SetWindowTextW(box, "")
        with BorrowedCursor() as cursor:
            cursor.click(*point)
            type_digits(number)
        # 엉뚱한 번호를 넣고 Enter를 누르지 않도록 칸을 다시 읽어 본다.
        # **읽히지 않으면 그냥 진행한다** - 클릭해서 넣은 글자는 화면에 보이는데
        # `GetWindowText`는 빈 문자열을 준다(실측). 이 프로그램은 글자를 직접
        # 그리는 곳이 많다. 잘못 열려도 아래 대기 루프가 실패로 끝낼 뿐이다.
        typed = window_text(box).strip()
        if typed and typed != number:
            raise ScreenNotOpen(
                f"화면번호 칸에 {number}를 넣으려 했는데 {typed!r}가 "
                f"들어갔습니다.\nEnter를 누르지 않았습니다."
            )
        press_key(VK_RETURN, settle=1.0)
    finally:
        unpin(main)
    deadline = time.monotonic() + SCREEN_OPEN_TIMEOUT
    while time.monotonic() < deadline:
        for handle in descendants(main):
            if is_screen(handle, number):
                return handle
        time.sleep(0.4)
    raise ScreenNotOpen(
        f"화면번호 {number}를 입력했는데 화면이 열리지 않았습니다.\n"
        "로그인 상태와 H-able 응답을 확인해 주세요."
    )


def ensure_screen_open(main: int, number: str = ASSET_SCREEN) -> int:
    """그 화면을 찾고, 닫혀 있으면 열어서 돌려준다."""
    for handle in descendants(main):
        if is_screen(handle, number):
            return handle
    # 화면이 없는 진짜 이유가 모달일 수 있다. 그때는 여는 것도 불가능하다.
    ensure_not_blocked(main)
    return open_screen(main, number)


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
