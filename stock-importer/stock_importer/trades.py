"""[0112] 거래내역조회의 표를 현금흐름 행으로 바꾼다.

이 화면은 [1285]와 생김새가 다르다. **거래 하나가 두 줄**이다 - 윗줄에 날짜와
거래종류와 금액이, 아랫줄에 종목명과 단가와 수수료가 온다. 헤더도 두 줄이다.
그래서 표를 그대로 행으로 읽으면 절반이 빈 줄로 보인다.

여기 있는 것은 전부 순수 함수다. 창 없이 시험할 수 있어야 한다.

**모르는 거래종류를 만나면 멈춘다.** 조용히 건너뛰면 손익이 조용히 틀린다.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from .parsing import RowError, instrument_code, normalize_label, parse_decimal

# 윗줄 헤더에서 찾을 것들.
MAIN_COLUMNS: dict[str, tuple[str, ...]] = {
    "date": ("거래일자",),
    "kind": ("거래종류",),
    "quantity": ("수량",),
    "gross": ("거래금액",),
    "settled": ("정산금액",),
    "trade_tax": ("거래세등", "거래세"),
    "income_tax": ("소득세",),
    "transfer_tax": ("양도세",),
}
# 아랫줄 헤더에서 찾을 것들.
DETAIL_COLUMNS: dict[str, tuple[str, ...]] = {
    "name": ("종목명",),
    "price": ("단가",),
    "fee": ("수수료",),
    "local_tax": ("지방소득세",),
    "cash": ("예수금",),
}
REQUIRED = ("date", "kind", "settled")

# 거래종류 → 현금흐름 구분과 현금 부호.
#
# `대체입금`은 은행에서 넘어오는 월 납입이다(2026-09-06 사용자 확인). 그래서
# 외부 입금이고 수익률의 분모를 움직인다. 계좌 사이 이동이었다면 내부로 잡아야
# 한다 - 둘을 바꾸면 수익률이 조용히 틀린다.
#
# `일괄대체 입고`는 주식만 들어오고 현금이 움직이지 않는다. 그래도 기록해야
# 나중에 팔 때 취득원가를 안다.
FLOW_KINDS: dict[str, tuple[str, int]] = {
    "대체입금": ("deposit", +1),
    "대체출금": ("withdrawal", -1),
    "예탁금이용료입금": ("interest", +1),
    "배당금입금": ("dividend", +1),
    "주식장내매수": ("buy", -1),
    "주식장내매도": ("sell", +1),
    "일괄대체입고": ("transfer_in", 0),
    "일괄대체출고": ("transfer_out", 0),
    "현금자산이자(퇴직연금)입금": ("interest", +1),
}

# 기록하지 않는 거래종류와 그 이유.
#
# `매매제한(출고포함)등록`은 담보·의무보유 같은 사유로 주식을 묶어 두는 것이다.
# 유가잔고에서는 빠지지만 **소유권이 바뀌지 않는다** - [1285]에도 그대로 남아
# 있다. 현금도 손익도 움직이지 않으므로 현금흐름으로 만들지 않는다. 이것을
# 출고로 기록하면 나중에 팔 때 취득원가가 사라져 손익이 틀린다.
IGNORED_KINDS: dict[str, str] = {
    "매매제한(출고포함)등록출고": "소유권이 그대로라 현금도 손익도 없다",
    "매매제한(출고포함)해제입고": "위의 되돌림",
}


def _find(headers: list[str], wanted: dict[str, tuple[str, ...]]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, header in enumerate(headers):
        label = normalize_label(header)
        for field, aliases in wanted.items():
            if field in found:
                continue
            if any(alias in label for alias in aliases):
                found[field] = index
                break
    return found


def trade_columns(headers: list[str], second_row: list[str]) -> dict[str, int]:
    """두 줄짜리 헤더에서 필요한 칸의 위치를 찾는다.

    자리를 세지 않고 이름으로 찾는다. 컬럼이 하나 늘거나 순서가 바뀌어도
    조용히 엉뚱한 값을 읽지 않게 하려는 것이다.
    """
    columns = _find(headers, MAIN_COLUMNS)
    columns.update(_find(second_row, DETAIL_COLUMNS))
    missing = [field for field in REQUIRED if field not in columns]
    if missing:
        raise RowError(
            f"거래내역 표에서 찾지 못한 칸: {', '.join(missing)}\n"
            f"윗줄 헤더: {headers}\n아랫줄 헤더: {second_row}"
        )
    return columns


def pair_rows(rows: list[list[str]]) -> list[tuple[list[str], list[str]]]:
    """거래 하나를 이루는 두 줄을 짝지어 돌려준다.

    첫 줄은 아랫줄 헤더이므로 뺀다. 날짜가 있는 줄이 윗줄이다 - 짝이 어긋나면
    지어내지 않고 그 줄부터 다시 맞춘다.
    """
    body = rows[1:] if rows else []
    paired: list[tuple[list[str], list[str]]] = []
    index = 0
    while index < len(body):
        main = body[index]
        detail = body[index + 1] if index + 1 < len(body) else []
        paired.append((main, detail))
        index += 2
    return paired


def _cell(row: list[str], columns: dict[str, int], field: str) -> str:
    position = columns.get(field)
    if position is None or position >= len(row):
        return ""
    return row[position].strip()


def _as_date(text: str) -> str:
    """`2025/10/30` 또는 `20251030`을 `2025-10-30`으로."""
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) != 8:
        raise RowError(f"거래일자를 읽지 못했습니다: {text!r}")
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def plain(value: Decimal) -> str:
    """`409380.0`이 아니라 `409380`으로. 지수 표기도 풀어서 낸다."""
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


def _amount(text: str) -> Decimal:
    value = parse_decimal(text)
    return Decimal("0") if value is None else value


def external_key(account_number: str, record: dict[str, Any], seen: dict[str, int]) -> str:
    """같은 기간을 다시 조회해도 같은 행이 같은 키를 갖게 한다.

    화면이 거래번호를 주지 않으므로 내용으로 키를 만든다. 같은 날 같은 내용의
    거래가 두 번 있을 수 있으므로 그 안에서만 순번을 붙인다.
    """
    seed = "|".join(
        [
            account_number,
            record["occurred_on"],
            record["flow_type"],
            str(record["amount"]),
            record.get("code") or "",
            str(record.get("quantity") or ""),
        ]
    )
    order = seen.get(seed, 0)
    seen[seed] = order + 1
    digest = hashlib.sha256(f"{seed}|{order}".encode("utf-8")).hexdigest()[:24]
    return f"0112-{digest}"


def rows_to_cash_flows(
    headers: list[str], rows: list[list[str]], account_number: str
) -> list[dict[str, Any]]:
    """내보낸 표 하나를 현금흐름 행 목록으로."""
    if not rows:
        return []
    columns = trade_columns(headers, rows[0])
    seen: dict[str, int] = {}
    flows: list[dict[str, Any]] = []
    for main, detail in pair_rows(rows):
        raw_date = _cell(main, columns, "date")
        if not raw_date:
            continue
        kind = _cell(main, columns, "kind")
        label = normalize_label(kind)
        if label in IGNORED_KINDS:
            continue
        if label not in FLOW_KINDS:
            raise RowError(
                f"모르는 거래종류입니다: {kind!r}\n"
                "손익이 조용히 틀리지 않도록 멈춥니다. "
                "`FLOW_KINDS`에 이 종류를 어떻게 볼지 적어 주세요."
            )
        flow_type, sign = FLOW_KINDS[label]
        settled = _amount(_cell(main, columns, "settled"))
        name = _cell(detail, columns, "name")
        quantity = parse_decimal(_cell(main, columns, "quantity"))
        price = parse_decimal(_cell(detail, columns, "price"))

        record: dict[str, Any] = {
            "occurred_on": _as_date(raw_date),
            "flow_type": flow_type,
            "amount": plain(settled * sign),
            "currency": "KRW",
            "memo": kind[:200],
        }
        if name:
            record["code"] = instrument_code(name)
            record["name"] = name
        if quantity is not None and quantity != 0:
            record["quantity"] = plain(quantity)
        if price is not None and price != 0:
            record["unit_price"] = plain(price)
        record["external_key"] = external_key(account_number, record, seen)
        flows.append(record)
    return flows


def cell_fingerprint(cell: str) -> str:
    """숫자는 표기 차이를 지운 값으로.

    같은 표를 두 번 내보내도 방법에 따라 `3,613`으로 나올 때가 있고
    `3613.0`으로 나올 때가 있다(UIA 셀이냐 COM 값이냐의 차이). 이걸 그대로
    견주면 같은 행이 새 행으로 보여 페이징이 끝나지 않는다.
    """
    text = cell.replace(",", "").strip()
    if not text:
        return ""
    try:
        return plain(Decimal(text))
    except (ArithmeticError, ValueError):
        return text


def row_fingerprint(row: list[str]) -> tuple[str, ...]:
    return tuple(cell_fingerprint(cell) for cell in row)


def dedupe_rows(rows: list[list[str]]) -> list[list[str]]:
    """같은 행을 한 번만 남긴다. 순서는 지킨다."""
    seen: set[tuple[str, ...]] = set()
    kept: list[list[str]] = []
    for row in rows:
        mark = row_fingerprint(row)
        if mark in seen:
            continue
        seen.add(mark)
        kept.append(row)
    return kept


def unknown_kinds(headers: list[str], rows: list[list[str]]) -> list[str]:
    """표에 있는 거래종류 중 우리가 모르는 것들.

    한 건씩 걸려 멈추는 대신 한 번에 다 보여주려고 따로 둔다.
    """
    if not rows:
        return []
    columns = trade_columns(headers, rows[0])
    found: list[str] = []
    for main, _detail in pair_rows(rows):
        if not _cell(main, columns, "date"):
            continue
        kind = _cell(main, columns, "kind")
        label = normalize_label(kind)
        if label in FLOW_KINDS or label in IGNORED_KINDS:
            continue
        if kind not in found:
            found.append(kind)
    return found


def summarize(flows: list[dict[str, Any]]) -> dict[str, int]:
    """구분별 건수. 무엇을 읽었는지 사람이 눈으로 대조할 수 있게."""
    counts: dict[str, int] = {}
    for flow in flows:
        counts[flow["flow_type"]] = counts.get(flow["flow_type"], 0) + 1
    return dict(sorted(counts.items()))
