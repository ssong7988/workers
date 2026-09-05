"""화면에서 읽은 글자를 서버가 받는 값으로 바꾸는 순수 함수들.

브라우저가 없어도 전부 시험할 수 있도록 여기에 모았다. 판정은 하나도 하지
않는다 - 손익률도 비중도 서버가 다시 계산하므로, 여기서는 화면의 숫자를 그대로
옮기고 계좌번호를 가리는 일까지만 한다.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation


class RowError(ValueError):
    """행 하나를 값으로 바꾸지 못했을 때."""


# 화면 헤더 → 우리가 쓰는 이름. 화면이 열 이름을 조금 바꿔도 견디도록 별칭을
# 함께 둔다. 여기 없는 열(손익률·등락률·구분 등)은 그냥 무시한다.
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("종목명", "상품명", "종목", "종목/상품명", "펀드명"),
    "code": ("종목코드", "단축코드", "종목번호", "티커", "symbol"),
    "quantity": ("보유수량", "잔고수량", "수량", "보유좌수", "좌수"),
    "market_value": ("평가금액", "평가액", "평가금액(외화)"),
    "market_value_krw": ("원화평가금액", "평가금액(원화)", "원화평가액", "원화환산금액"),
    "unrealized_pl": ("평가손익", "평가손익금액", "손익금액"),
    "price": ("현재가", "기준가", "현재가격"),
    "average_cost": ("평균매수단가", "평균단가", "매입단가", "매입평균단가"),
    "cost_amount": ("총매수금액", "매입금액", "매수금액", "총매입금액"),
    "currency": ("통화", "통화코드"),
    "account_number": ("계좌번호", "계좌"),
}

# 표를 찾을 때 화면에서 앵커로 삼을 글자들. 하나라도 아니면 그 표가 아니다.
REQUIRED_FIELDS = ("name", "quantity", "market_value", "account_number")

_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_SORT_MARKS = "▲▼△▽↑↓⇅⇵ⓘ"


def normalize_label(text: str) -> str:
    """헤더 글자에서 정렬 화살표와 공백을 걷어낸다."""
    cleaned = unicodedata.normalize("NFKC", text or "")
    for mark in _SORT_MARKS:
        cleaned = cleaned.replace(mark, "")
    return "".join(cleaned.split())


def map_columns(headers: list[str]) -> dict[str, int]:
    """헤더 목록을 {우리가 쓰는 이름: 열 번호}로 바꾼다.

    같은 이름이 두 번 나오면 먼저 나온 열을 쓴다. 화면이 열을 늘려도 우리가
    아는 열만 집어간다.
    """
    columns: dict[str, int] = {}
    for index, raw in enumerate(headers):
        label = normalize_label(raw)
        if not label:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if field in columns:
                continue
            if any(label == normalize_label(alias) for alias in aliases):
                columns[field] = index
                break
    return columns


def missing_fields(columns: dict[str, int]) -> list[str]:
    return [field for field in REQUIRED_FIELDS if field not in columns]


# 종목명 칸에는 'ETF' 같은 배지가 이름과 따로 그려져 별개의 조각으로 잡힌다.
_BADGE_RE = re.compile(r"^[A-Z]{2,4}$")


def flatten_cell(fragments: list[str], *, is_name: bool = False) -> str:
    """한 칸에 들어온 글자 조각들을 하나로 합친다."""
    parts = [" ".join(fragment.split()) for fragment in fragments if fragment and fragment.strip()]
    if not parts:
        return ""
    if is_name and len(parts) > 1:
        kept = [part for part in parts if not _BADGE_RE.fullmatch(part)]
        if kept:
            parts = kept
    return " ".join(parts)


def flatten_row(columns: dict[str, int], cells: list[list[str]]) -> list[str]:
    name_index = columns.get("name")
    return [
        flatten_cell(cell, is_name=index == name_index) for index, cell in enumerate(cells)
    ]


def parse_delimited_table(text: str) -> tuple[list[str], list[list[str]]]:
    """복사한 표 글자를 (헤더, 행들)로 나눈다.

    H-able이 클립보드에 넣는 것은 탭으로 나뉜 줄들이다. 탭이 없으면 두 칸 이상의
    공백으로 나뉜 고정폭 표일 수 있어 그쪽도 받는다. 헤더는 첫 번째 줄로 보되,
    열 수가 가장 흔한 줄들만 본문으로 삼는다 - 제목이나 합계 줄이 섞여 들어오는
    것을 막는다.
    """
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return [], []
    delimiter = "\t" if any("\t" in line for line in lines) else None
    if delimiter:
        split = [line.split("\t") for line in lines]
    else:
        split = [re.split(r"\s{2,}", line.strip()) for line in lines]
    split = [[cell.strip() for cell in row] for row in split]

    widths = [len(row) for row in split]
    common = max(set(widths), key=widths.count)
    if common < 2:
        return [], []
    kept = [row for row in split if len(row) == common]
    return kept[0], kept[1:]


def parse_decimal(text: str | None) -> Decimal | None:
    """`-1,610,670원` → Decimal('-1610670'). 빈 칸과 `-`는 None."""
    if text is None:
        return None
    cleaned = unicodedata.normalize("NFKC", text).replace(",", "").strip()
    if not cleaned:
        return None
    match = _NUMBER_RE.search(cleaned)
    if match is None:
        return None
    try:
        return Decimal(match.group())
    except InvalidOperation:  # pragma: no cover - 정규식이 이미 걸러낸다
        return None


def parse_required_decimal(text: str | None, what: str) -> Decimal:
    value = parse_decimal(text)
    if value is None:
        raise RowError(f"{what}을(를) 숫자로 읽지 못했습니다: {text!r}")
    return value


def mask_account_number(text: str) -> str:
    """`338-263-400 01` → `338-***-400 01`, `338-711-781-01` → `338-***-781-01`.

    계좌를 서로 구분할 수 있을 만큼만 남기고 가린다. 원본 계좌번호는 어디에도
    저장하지 않는다.

    **두 번째 덩어리 하나만 가린다.** 웹은 세 덩어리(`338-263-400 01`)지만
    H-able은 네 덩어리(`338-711-781-01`)로 준다. 가운데를 전부 가리면 네 덩어리
    형식에서 `338-***-***-01`이 되어, 앞자리가 같은 실제 계좌 둘이 한 값으로
    뭉개진다. 세 번째 덩어리를 남기면 둘 다 구분된다.
    """
    raw = " ".join(unicodedata.normalize("NFKC", text or "").split())
    if not raw:
        return ""
    head, _, tail = raw.partition(" ")
    groups = head.split("-")
    if len(groups) >= 3:
        masked = "-".join(
            ["*" * len(group) if index == 1 else group for index, group in enumerate(groups)]
        )
    else:
        digits = re.sub(r"\D", "", head)
        if len(digits) > 6:
            masked = f"{digits[:3]}{'*' * (len(digits) - 6)}{digits[-3:]}"
        else:
            masked = head
    return f"{masked} {tail}".strip()


def instrument_code(name: str, code_text: str = "") -> str:
    """화면에 종목코드가 있으면 그것을, 없으면 종목명 슬러그를 쓴다.

    슬러그로 내려가는 것은 차선이다. 나중에 코드가 보이는 화면을 찾으면 그쪽을
    쓰고, 이 함수가 만든 코드는 admin에서 한 번 정리하면 된다.
    """
    code = (code_text or "").strip()
    if code and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", code):
        return code
    slug = unicodedata.normalize("NFKC", name or "").strip().lower()
    slug = re.sub(r"[^\w]+", "-", slug, flags=re.UNICODE)
    slug = re.sub(r"-{2,}", "-", slug).strip("-_")
    if not slug:
        raise RowError(f"종목코드를 만들 수 없습니다: {name!r}")
    return slug[:40]


def row_to_position(columns: dict[str, int], cells: list[str]) -> dict:
    """표의 한 줄을 `/stock/api/import-runs/`의 positions 한 줄로 바꾼다.

    돌려주는 dict에는 서버가 안 받는 `account_number`가 하나 더 들어 있다.
    계좌별로 묶는 데 쓰고 POST 직전에 빼낸다.
    """

    def cell(field: str) -> str:
        index = columns.get(field)
        if index is None or index >= len(cells):
            return ""
        return (cells[index] or "").strip()

    name = cell("name")
    if not name:
        raise RowError("종목명이 비어 있습니다.")
    account_number = mask_account_number(cell("account_number"))
    if not account_number:
        raise RowError(f"{name}: 계좌번호가 비어 있습니다.")

    currency = (cell("currency") or "KRW").upper()[:3]
    market_value = parse_required_decimal(cell("market_value"), f"{name}의 평가금액")
    krw = parse_decimal(cell("market_value_krw"))
    if krw is None:
        if currency != "KRW":
            # 환율을 지어내지 않는다. 원화평가액이 있는 화면을 찾아야 한다.
            raise RowError(f"{name}: 외화 종목인데 원화평가금액 열이 없습니다.")
        krw = market_value

    return {
        "account_number": account_number,
        "code": instrument_code(name, cell("code")),
        "name": name,
        "currency": currency,
        "quantity": str(parse_required_decimal(cell("quantity"), f"{name}의 보유수량")),
        "average_cost": _optional(cell("average_cost")),
        "cost_amount": _optional(cell("cost_amount")),
        "price": _optional(cell("price")),
        "market_value": str(market_value),
        "market_value_krw": str(krw),
        "unrealized_pl": _optional(cell("unrealized_pl")),
    }


def _optional(text: str) -> str | None:
    value = parse_decimal(text)
    return None if value is None else str(value)


def group_by_account(rows: list[dict]) -> dict[str, list[dict]]:
    """계좌번호로 묶는다. 한 계좌 안에 같은 종목이 두 번 나오면 멈춘다.

    조용히 합치면 평균단가가 거짓이 되고, 서버의 (날짜·계좌·종목) 유일 조건도
    깨진다. 실제로 그런 화면을 만나면 그때 규칙을 정하는 편이 낫다.
    """
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        account_number = row["account_number"]
        bucket = grouped.setdefault(account_number, [])
        if any(existing["code"] == row["code"] for existing in bucket):
            raise RowError(
                f"{account_number} 계좌에 '{row['name']}'이(가) 두 줄 있습니다. "
                "합치지 않고 멈춥니다 - 화면을 확인하세요."
            )
        bucket.append(row)
    return grouped
