"""소비 화면의 표기를 한 곳에서 정한다.

`portfolio/display.py`와 같은 역할이다. 금액이 화면마다 다른 모양으로 찍히면
같은 수치인지 알아보기 어렵다.
"""

from __future__ import annotations


def won_text(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}원"


def signed_won_text(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:+,}원"


def man_text(value: int | None) -> str:
    """만원 단위 축약. 억 전환은 진짜 1억을 넘을 때만 한다.

    1,000만에서 억으로 넘기면 1,500만원짜리 달이 `0.1억`으로 찍혀 자릿수를
    잘못 읽게 된다.
    """
    if value is None:
        return "—"
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    man = abs(value) / 10_000
    if man >= 10_000:
        return f"{sign}{man / 10_000:,.2f}억"
    if man >= 100:
        return f"{sign}{man:,.0f}만"
    return f"{sign}{man:,.1f}만"


def percent_text(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}%"


def signed_percent_text(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.{digits}f}%"


def month_text(billing_month: str) -> str:
    """`2026-09`를 `2026년 9월`로."""
    try:
        year, month = billing_month.split("-")
        return f"{int(year)}년 {int(month)}월"
    except (ValueError, AttributeError):
        return billing_month
