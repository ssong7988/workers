"""금액·비율 표기를 한 곳에 모아둔 곳.

부동산 쪽에서 `properties/report.py`가 그랬듯, 카카오 메시지와 웹 화면이
같은 숫자를 다르게 적는 일이 없도록 표기는 여기서만 만든다.

DB에는 원 단위를 그대로 보존하고 반올림은 여기서만 한다. 화면 기본 단위는
만원이며, 반올림해서 사라진 잔액은 감추지 않고 따로 표시한다.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


MAN = Decimal("10000")
EOK = Decimal("100000000")
ZERO = Decimal("0")


def round_to_man(value: Decimal) -> Decimal:
    """만원 단위로 반올림한 원 금액."""
    return (value / MAN).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * MAN


def man_won_text(value: Decimal) -> str:
    """만원 단위 표기. 억을 넘으면 억과 만원으로 끊는다."""
    rounded = round_to_man(value)
    sign = "-" if rounded < ZERO else ""
    amount = abs(rounded)
    if amount >= EOK:
        eok, remainder = divmod(amount, EOK)
        man = remainder / MAN
        if man == ZERO:
            return f"{sign}{eok:,.0f}억원"
        return f"{sign}{eok:,.0f}억 {man:,.0f}만원"
    return f"{sign}{amount / MAN:,.0f}만원"


def signed_man_won_text(value: Decimal) -> str:
    """리밸런싱처럼 부호가 뜻을 가지는 금액. 양수에 +를 붙인다."""
    text = man_won_text(value)
    return f"+{text}" if value > ZERO else text


def percent_text(ratio: Decimal | None, digits: int = 1) -> str:
    """0~1 비율을 백분율 문자열로. `None`은 값이 없다는 뜻이다."""
    if ratio is None:
        return "-"
    return f"{ratio * 100:.{digits}f}%"


def signed_percent_text(ratio: Decimal | None, digits: int = 2) -> str:
    if ratio is None:
        return "-"
    sign = "+" if ratio > ZERO else ""
    return f"{sign}{ratio * 100:.{digits}f}%"


def percent_point_text(points: Decimal | None, digits: int = 1) -> str:
    """비중 차이처럼 이미 %p 단위인 값."""
    if points is None:
        return "-"
    sign = "+" if points > ZERO else ""
    return f"{sign}{points:.{digits}f}%p"
