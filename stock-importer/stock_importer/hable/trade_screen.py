"""[0112] 거래내역조회를 계좌별로 몰아 읽는다.

[1285]와 달리 이 화면은 계좌를 하나씩 골라야 하고, 결과가 길면 `다음`을 눌러
이어서 받아야 한다. 계좌 콤보는 `***-***-***-01`로 마스킹돼 있어 화면만으로는
어느 계좌인지 알 수 없다. 대신 [1285]를 읽는 동안 손에 들어온 **계좌번호 원문을
콤보에 직접 입력한다.** 그 원문은 메모리에만 있고 로그·파일·화면 어디에도
남기지 않는다.

좌표는 2026-09-06에 화면에서 실측한 값이다. 창 좌상단 기준 상대 좌표이므로
창을 옮겨도 같은 자리를 누른다.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..trades import row_fingerprint
from . import window
from .export import click_point, export_grid
from .extract import (
    VK_DOWN,
    VK_RETURN,
    VK_UP,
    BorrowedCursor,
    ExtractionError,
    clear_field,
    ensure_clickable,
    focus,
    press_key,
    type_digits,
    type_text,
)

TRADE_SCREEN = "0112"

# 창 좌상단 기준. (엑셀·조회·다음은 버튼 가운데)
ACCOUNT_FIELD = (56, 37)
# 목록에 들어 있는 계좌 수보다 넉넉하게. 맨 위로 올리는 데만 쓴다.
ACCOUNT_SLOTS = 12
# 날짜 칸은 연·월·일 세 자리로 나뉘어 있다. 가운데를 누르면 월 자리부터
# 입력돼 `2026-29-06` 같은 것이 만들어진다(실제로 그렇게 실패했다).
# **연도 자리**를 눌러야 여덟 자리가 순서대로 들어간다.
SINCE_FIELD = (398, 37)
UNTIL_FIELD = (505, 37)
EXCEL_BUTTON = (849, 37)
QUERY_BUTTON = (879, 37)
NEXT_BUTTON = (917, 37)

# 조회를 누른 뒤 표가 채워질 때까지.
QUERY_WAIT_SECONDS = 3.0
# `다음`을 누를 수 있는 최대 횟수. 끝을 못 알아채고 도는 것을 막는 안전장치다.
MAX_PAGES = 30


def _click(main: int, screen: int, point: tuple[int, int], *, settle: float = 0.8) -> None:
    click_point_settled(main, screen, point, settle)


def click_point_settled(
    main: int, screen: int, point: tuple[int, int], settle: float
) -> None:
    focus(main)
    left, top, _width, _height = window.rect(screen)
    x, y = left + point[0], top + point[1]
    ensure_clickable(main, screen, x, y)
    with BorrowedCursor() as cursor:
        cursor.click(x, y, settle=settle)


def _fill(main: int, screen: int, point: tuple[int, int], text: str) -> None:
    _click(main, screen, point, settle=0.5)
    clear_field()
    type_text(text)


def _fill_date(main: int, screen: int, point: tuple[int, int], digits: str) -> None:
    """날짜 칸에 여덟 자리를 넣는다.

    유니코드 입력은 이 컨트롤에 통하지 않는다 - `20260906`을 그렇게 넣었더니
    `18000101`이 됐다. 진짜 키코드로 눌러야 한다.
    """
    _click(main, screen, point, settle=0.5)
    type_digits(digits)


def set_period(main: int, screen: int, since: str, until: str) -> None:
    """조회기간을 넣고, 실제로 들어갔는지 확인한다.

    기간이 조용히 어긋나면 수집한 손익도 조용히 어긋난다. 확인 없이 넘어가지
    않는다.
    """
    wanted = {"since": since.replace("-", ""), "until": until.replace("-", "")}
    current = field_values(screen)
    if current.get("since") == wanted["since"] and current.get("until") == wanted["until"]:
        return
    _fill_date(main, screen, SINCE_FIELD, wanted["since"])
    _fill_date(main, screen, UNTIL_FIELD, wanted["until"])
    time.sleep(0.4)
    got = field_values(screen)
    if got.get("since") != wanted["since"] or got.get("until") != wanted["until"]:
        raise ExtractionError(
            "조회기간이 화면에 제대로 들어가지 않았습니다.\n"
            f"  넣으려던 값: {wanted['since']} ~ {wanted['until']}\n"
            f"  화면의 값:   {got.get('since')} ~ {got.get('until')}"
        )


def select_account(main: int, screen: int, index: int) -> None:
    """계좌 목록의 `index`번째를 고른다.

    번호를 타이핑하는 방법은 **조용히 실패한다** - 다섯 계좌를 도는 동안 화면이
    한 번도 바뀌지 않은 채 같은 자료를 다섯 번 내놓았다(2026-09-06). 그래서
    드롭다운을 열고 순번으로 고른다.

    목록의 글자는 그려진 것이라 프로그램이 읽을 수 없다. 어느 순번이 어느
    계좌인지는 사람이 한 번 정해 준다.
    """
    # 순서가 중요하다. 칸을 누르고 Down을 한 번 치면 목록이 열린다. 화살표를
    # 누르거나 Home을 먼저 보내면 열리지 않아 **아무 일도 일어나지 않는다** -
    # 그런데도 조회는 되므로 같은 계좌를 다시 읽고 성공한 것처럼 보인다.
    _click(main, screen, ACCOUNT_FIELD, settle=0.8)
    press_key(VK_DOWN, settle=0.8)
    # 목록 안에서의 이동은 지금 위치 기준이다. 위로 충분히 올려 맨 처음에
    # 세운 다음 순번만큼 내려간다.
    press_key(VK_UP, times=ACCOUNT_SLOTS, settle=0.12)
    if index:
        press_key(VK_DOWN, times=index, settle=0.12)
    press_key(VK_RETURN, settle=QUERY_WAIT_SECONDS)
    window.ensure_query_ready(main, screen)


def query(main: int, screen: int) -> None:
    _click(main, screen, QUERY_BUTTON, settle=QUERY_WAIT_SECONDS)
    window.ensure_query_ready(main, screen)


def grid_pane(screen: int) -> window.Pane:
    panes = window.panes(screen)
    if not panes:
        raise ExtractionError(f"[{TRADE_SCREEN}] 화면에서 표 영역을 찾지 못했습니다.")
    return max(panes, key=lambda pane: pane.width * pane.height)


def _export(main: int, screen: int, folder: Path) -> tuple[list[str], list[list[str]], str]:
    return export_grid(
        main,
        screen,
        grid_pane(screen),
        folder,
        f"hable-{TRADE_SCREEN}",
        excel_at=EXCEL_BUTTON,
    )


def read_all_pages(
    main: int, screen: int, folder: Path
) -> tuple[list[str], list[list[str]], str, int]:
    """`다음`을 눌러 가며 끝까지 읽는다.

    화면 아래의 "조회가 계속됩니다" 문구는 그려진 것이라 읽을 수 없다. 그래서
    내보낸 표를 견줘 판단한다 - 새 줄이 하나도 늘지 않으면 끝이다. `다음`이
    이어붙이든 갈아치우든 이 방법은 통한다.
    """
    headers, rows, how = _export(main, screen, folder)
    if not rows:
        return headers, rows, how, 1

    collected = list(rows)
    # 표기 차이를 지우고 견준다. `3,613`과 `3613.0`을 다른 행으로 보면 페이징이
    # 끝나지 않고 같은 내용이 쌓인다(실제로 그렇게 쌓였다).
    known = {row_fingerprint(row) for row in rows}
    pages = 1
    for _ in range(MAX_PAGES - 1):
        _click(main, screen, NEXT_BUTTON, settle=QUERY_WAIT_SECONDS)
        window.ensure_query_ready(main, screen)
        _headers, more, _how = _export(main, screen, folder)
        fresh = [row for row in more if row_fingerprint(row) not in known]
        if not fresh:
            break
        pages += 1
        collected.extend(fresh)
        known.update(row_fingerprint(row) for row in fresh)
        time.sleep(0.3)
    return headers, collected, how, pages


def collect_account(
    main: int, screen: int, index: int, since: str, until: str, folder: Path
) -> tuple[list[str], list[list[str]], str, int]:
    """계좌 하나의 기간 거래내역을 끝까지 읽는다.

    기간을 먼저 맞춘다. 계좌를 고르면 엔터가 곧바로 조회를 걸기 때문에, 기간이
    틀린 채로 고르면 "조회 기간의 날짜 형식이 맞지 않습니다" 대화상자가 떠서
    화면 전체가 막힌다(실제로 그렇게 막혔다).
    """
    set_period(main, screen, since, until)
    select_account(main, screen, index)
    query(main, screen)
    return read_all_pages(main, screen, folder)


def field_values(screen: int) -> dict[str, Any]:
    """화면이 지금 들고 있는 조회기간. 넣은 값이 들어갔는지 확인하는 용도다."""
    left, top, _width, _height = window.rect(screen)
    values: dict[str, Any] = {}
    for handle in window.descendants(screen):
        x_left, y_top, width, height = window.rect(handle)
        x, y = x_left - left, y_top - top
        if y != 27 or height != 20:
            continue
        text = window.window_text(handle).strip()
        if width == 90 and text.isdigit():
            values["since" if x < 450 else "until"] = text
    return values
