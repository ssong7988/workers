"""수집 결과를 `/stock/api/import-runs/` 요청 본문으로 조립한다.

`file_hash`가 멱등성의 열쇠다. 원래 계약은 다운로드한 파일의 해시였는데 우리는
파일을 받지 않으므로, **그 계좌에서 읽은 행들 자체의 해시**를 쓴다. 뜻은 같다 -
같은 자료를 다시 넘기면 서버가 아무것도 바꾸지 않는다. 하루에 두 번 돌려도
값이 그대로면 200 `duplicate`로 끝난다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

DOCUMENT_TYPE = "balance"

# 서버가 positions 한 줄에서 받는 열쇠들. `account_number`는 계좌를 고르는 데만
# 쓰고 본문에는 넣지 않는다.
POSITION_KEYS = (
    "code",
    "name",
    "currency",
    "quantity",
    "average_cost",
    "cost_amount",
    "price",
    "market_value",
    "market_value_krw",
    "unrealized_pl",
)


def position_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """행을 서버가 아는 열쇠만 남기고 코드 순으로 정렬한다."""
    trimmed = [{key: row.get(key) for key in POSITION_KEYS} for row in rows]
    return sorted(trimmed, key=lambda row: str(row["code"]))


def rows_hash(account_number: str, rows: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        {"account_number": account_number, "positions": position_rows(rows)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# 서버가 cash_flows 한 줄에서 받는 열쇠들.
FLOW_KEYS = (
    "occurred_on",
    "flow_type",
    "amount",
    "currency",
    "amount_krw",
    "code",
    "name",
    "quantity",
    "unit_price",
    "memo",
    "external_key",
)


def flow_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """서버가 아는 열쇠만 남기고 날짜·키 순으로 정렬한다."""
    trimmed = [{key: row[key] for key in FLOW_KEYS if key in row} for row in rows]
    return sorted(trimmed, key=lambda row: (row["occurred_on"], row["external_key"]))


def build_trade_payload(
    account_number: str,
    as_of: str,
    flows: list[dict[str, Any]],
    *,
    source_name: str = "",
) -> dict[str, Any]:
    """거래내역 한 계좌치.

    `as_of`는 이 자료를 받은 날이다. 개별 행은 각자 `occurred_on`을 갖고 있고,
    서버의 완전 수집일 판정은 잔고(`balance`)만 보므로 이 자료가 그 판정을
    흔들지 않는다.
    """
    rows = flow_rows(flows)
    canonical = json.dumps(
        {"account_number": account_number, "cash_flows": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "account_number": account_number,
        "as_of": as_of,
        "document_type": "trade",
        "status": "success",
        "file_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "source_name": source_name[:200],
        "positions": [],
        "cash_flows": rows,
    }


def build_import_payload(
    account_number: str,
    as_of: str,
    rows: list[dict[str, Any]],
    *,
    source_name: str = "",
) -> dict[str, Any]:
    positions = position_rows(rows)
    return {
        "account_number": account_number,
        "as_of": as_of,
        "document_type": DOCUMENT_TYPE,
        "status": "success",
        "file_hash": rows_hash(account_number, rows),
        "source_name": source_name[:200],
        "positions": positions,
    }
