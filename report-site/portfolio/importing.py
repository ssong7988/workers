"""수집기가 넘긴 정규화 원본을 받아들이는 곳.

여기서 지키는 두 가지 불변 조건이 나머지 전부를 떠받친다.

멱등성: 같은 파일(같은 해시)을 다시 넘기면 아무것도 바뀌지 않는다. 같은 날
같은 자료를 다시 받으면(재다운로드) 그 자료가 만든 행만 교체하고, 다른 자료가
만든 행은 건드리지 않는다. 겹치는 거래기간을 다시 넘겨도 현금흐름은
`external_key`로 중복되지 않는다.

완결성: 필수 계좌 하나라도 그날 잔고를 못 받으면 그 날짜는 완전 스냅샷이
아니다. `latest_complete_date()`가 그 판정을 혼자 가지고 있고, 공개 화면과
성과 계산은 이 함수가 돌려준 날짜만 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import IntegrityError, transaction

from .models import (
    UNCLASSIFIED_ASSET_CLASS_ID,
    AssetClass,
    CashFlow,
    DOCUMENT_TYPES,
    EXTERNAL_FLOW_TYPES,
    FLOW_TYPES,
    IMPORT_STATUSES,
    ImportRun,
    Instrument,
    InvestmentAccount,
    PositionSnapshot,
)


DOCUMENT_TYPE_KEYS = {key for key, _ in DOCUMENT_TYPES}
FLOW_TYPE_KEYS = {key for key, _ in FLOW_TYPES}
IMPORT_STATUS_KEYS = {key for key, _ in IMPORT_STATUSES}
# 잔고와 예수금만 보유 스냅샷을 만든다. 거래·입출금은 현금흐름만 만든다.
POSITION_DOCUMENT_TYPES = frozenset({"balance", "cash"})


class PortfolioImportError(ValueError):
    """수집 자료가 계약을 어겼을 때. 호출자가 400으로 되돌린다."""


@dataclass(frozen=True)
class ImportResult:
    run: ImportRun
    created: bool
    duplicate: bool
    position_count: int
    cash_flow_count: int
    new_instruments: list[str]


def _required(payload: dict[str, Any], key: str) -> Any:
    if key not in payload or payload[key] in (None, ""):
        raise PortfolioImportError(f"{key}이(가) 필요합니다.")
    return payload[key]


def _as_date(value: Any, key: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PortfolioImportError(f"{key}은(는) YYYY-MM-DD 형식이어야 합니다.") from exc


def _as_decimal(value: Any, key: str, *, allow_none: bool = False) -> Decimal | None:
    if value is None or value == "":
        if allow_none:
            return None
        raise PortfolioImportError(f"{key}이(가) 필요합니다.")
    try:
        return Decimal(str(value))
    except (TypeError, InvalidOperation) as exc:
        raise PortfolioImportError(f"{key}은(는) 숫자여야 합니다.") from exc


def _unclassified() -> AssetClass:
    asset_class, _ = AssetClass.objects.get_or_create(
        pk=UNCLASSIFIED_ASSET_CLASS_ID,
        defaults={"name": "미분류", "display_order": 999},
    )
    return asset_class


def _resolve_instrument(row: dict[str, Any], new_codes: list[str]) -> Instrument:
    """종목을 찾고, 처음 보는 것이면 미분류로 만든다.

    임의로 분류하지 않는 것이 요점이다. 미분류로 남겨두면 화면이 제외 금액을
    명시하므로 누락이 조용히 넘어가지 않는다.
    """
    code = str(_required(row, "code")).strip()
    instrument = Instrument.objects.filter(pk=code).first()
    if instrument is not None:
        return instrument
    instrument = Instrument.objects.create(
        code=code,
        name=str(row.get("name") or code).strip(),
        currency=str(row.get("currency") or "KRW").upper()[:3],
        asset_class=_unclassified(),
        is_cash=bool(row.get("is_cash", False)),
    )
    new_codes.append(code)
    return instrument


def _position_values(
    row: dict[str, Any], instrument: Instrument
) -> dict[str, Any]:
    currency = str(row.get("currency") or instrument.currency or "KRW").upper()[:3]
    market_value = _as_decimal(row.get("market_value"), "market_value")
    # 원화평가액은 해외 종목에서만 별도 값이다. 원화 종목은 평가금액과 같고,
    # 해외 종목인데 비어 있으면 여기서 환율을 지어내지 않고 거절한다.
    krw = _as_decimal(row.get("market_value_krw"), "market_value_krw", allow_none=True)
    if krw is None:
        if currency != "KRW":
            raise PortfolioImportError(
                f"{instrument.pk}: 외화 종목에는 market_value_krw가 필요합니다."
            )
        krw = market_value
    return {
        "quantity": _as_decimal(row.get("quantity"), "quantity"),
        "average_cost": _as_decimal(row.get("average_cost"), "average_cost", allow_none=True),
        "cost_amount": _as_decimal(row.get("cost_amount"), "cost_amount", allow_none=True),
        "price": _as_decimal(row.get("price"), "price", allow_none=True),
        "market_value": market_value,
        "unrealized_pl": _as_decimal(
            row.get("unrealized_pl"), "unrealized_pl", allow_none=True
        ),
        "currency": currency,
        "market_value_krw": krw,
    }


def _cash_flow_values(
    row: dict[str, Any], new_codes: list[str]
) -> tuple[str, dict[str, Any]]:
    flow_type = str(_required(row, "flow_type"))
    if flow_type not in FLOW_TYPE_KEYS:
        raise PortfolioImportError(f"알 수 없는 flow_type입니다: {flow_type}")
    external_key = str(_required(row, "external_key")).strip()[:100]
    currency = str(row.get("currency") or "KRW").upper()[:3]
    amount = _as_decimal(row.get("amount"), "amount")
    amount_krw = _as_decimal(row.get("amount_krw"), "amount_krw", allow_none=True)
    if amount_krw is None:
        if currency != "KRW":
            raise PortfolioImportError("외화 현금흐름에는 amount_krw가 필요합니다.")
        amount_krw = amount
    instrument = None
    if row.get("code"):
        instrument = _resolve_instrument(row, new_codes)
    is_external = row.get("is_external")
    if is_external is None:
        is_external = flow_type in EXTERNAL_FLOW_TYPES
    elif not isinstance(is_external, bool):
        raise PortfolioImportError("is_external은 boolean이어야 합니다.")
    return external_key, {
        "occurred_on": _as_date(_required(row, "occurred_on"), "occurred_on"),
        "instrument": instrument,
        "flow_type": flow_type,
        "amount": amount,
        "quantity": _as_decimal(row.get("quantity"), "quantity", allow_none=True),
        "unit_price": _as_decimal(row.get("unit_price"), "unit_price", allow_none=True),
        "currency": currency,
        "amount_krw": amount_krw,
        "is_external": is_external,
        "memo": str(row.get("memo") or "")[:200],
    }


def _resolve_account(payload: dict[str, Any]) -> InvestmentAccount:
    """`account` 또는 `account_number`로 계좌를 찾는다.

    수집기는 화면에서 계좌 ID가 아니라 계좌번호를 본다. 어느 번호가 ISA인지
    아는 것은 사람이므로, 그 연결은 admin의 `masked_number`에 두고 여기서는
    조회만 한다. 모르는 번호를 임의로 붙이지 않고 그대로 돌려보낸다.
    """
    account_id = str(payload.get("account") or "").strip()
    number = str(payload.get("account_number") or "").strip()
    if account_id:
        account = InvestmentAccount.objects.filter(pk=account_id).first()
        if account is None:
            raise PortfolioImportError(f"등록되지 않은 계좌입니다: {account_id}")
    elif number:
        matches = list(InvestmentAccount.objects.filter(masked_number=number))
        if not matches:
            raise PortfolioImportError(
                f"등록되지 않은 계좌번호입니다: {number}. "
                "admin의 투자 계좌에서 이 번호를 마스킹 계좌번호로 넣으세요."
            )
        if len(matches) > 1:
            raise PortfolioImportError(
                f"같은 계좌번호를 쓰는 계좌가 둘 이상입니다: {number}"
            )
        account = matches[0]
    else:
        raise PortfolioImportError("account 또는 account_number가 필요합니다.")
    if not account.active:
        raise PortfolioImportError(f"사용하지 않는 계좌입니다: {account.pk}")
    return account


@transaction.atomic
def record_import_run(payload: dict[str, Any]) -> ImportResult:
    """계좌 하나·자료 하나를 저장하고 그 결과를 돌려준다."""
    account = _resolve_account(payload)

    document_type = str(_required(payload, "document_type"))
    if document_type not in DOCUMENT_TYPE_KEYS:
        raise PortfolioImportError(f"알 수 없는 document_type입니다: {document_type}")
    status = str(payload.get("status") or "success")
    if status not in IMPORT_STATUS_KEYS:
        raise PortfolioImportError(f"알 수 없는 status입니다: {status}")

    as_of = _as_date(_required(payload, "as_of"), "as_of")
    file_hash = str(_required(payload, "file_hash")).strip().lower()
    if len(file_hash) != 64 or any(c not in "0123456789abcdef" for c in file_hash):
        raise PortfolioImportError("file_hash는 64자리 SHA-256 16진 문자열이어야 합니다.")

    positions = payload.get("positions", [])
    cash_flows = payload.get("cash_flows", [])
    for name, rows in (("positions", positions), ("cash_flows", cash_flows)):
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise PortfolioImportError(f"{name}는 JSON 객체의 배열이어야 합니다.")
    if positions and document_type not in POSITION_DOCUMENT_TYPES:
        raise PortfolioImportError("positions는 잔고 또는 예수금 자료에만 넣을 수 있습니다.")

    # 같은 파일을 다시 넘긴 경우. 이미 반영돼 있으므로 아무것도 하지 않는다.
    existing = ImportRun.objects.filter(
        account=account, document_type=document_type, file_hash=file_hash
    ).first()
    if existing is not None:
        return ImportResult(
            run=existing,
            created=False,
            duplicate=True,
            position_count=existing.positions.count(),
            cash_flow_count=existing.cash_flows.count(),
            new_instruments=[],
        )

    run, created = ImportRun.objects.update_or_create(
        account=account,
        document_type=document_type,
        as_of=as_of,
        defaults={
            "file_hash": file_hash,
            "source_name": str(payload.get("source_name") or "")[:200],
            "row_count": len(positions) + len(cash_flows),
            "status": status,
            "error": str(payload.get("error") or ""),
        },
    )
    # 같은 날 이 자료를 다시 받은 경우, 이 자료가 만든 보유 행만 지운다.
    # 다른 자료(예수금 등)가 만든 행은 그대로 둔다.
    run.positions.all().delete()

    new_codes: list[str] = []
    try:
        for row in positions:
            instrument = _resolve_instrument(row, new_codes)
            PositionSnapshot.objects.create(
                as_of=as_of,
                account=account,
                instrument=instrument,
                import_run=run,
                **_position_values(row, instrument),
            )

        for row in cash_flows:
            external_key, values = _cash_flow_values(row, new_codes)
            CashFlow.objects.update_or_create(
                account=account,
                external_key=external_key,
                defaults={"import_run": run, **values},
            )
    except IntegrityError as exc:
        # 같은 날짜에 다른 자료가 이미 쓴 종목을 이 자료가 다시 보낸 경우다.
        # 조용히 합치지 않고 계약 위반으로 돌려보낸다.
        raise PortfolioImportError(f"중복되는 행이 있습니다: {exc}") from exc

    return ImportResult(
        run=run,
        created=created,
        duplicate=False,
        position_count=len(positions),
        cash_flow_count=len(cash_flows),
        new_instruments=new_codes,
    )


def required_account_ids() -> set[str]:
    return set(
        InvestmentAccount.objects.filter(active=True, required=True).values_list(
            "pk", flat=True
        )
    )


def complete_dates() -> list[date]:
    """필수 계좌 전부가 잔고를 성공적으로 넘긴 날짜를 오래된 순으로 돌려준다."""
    required = required_account_ids()
    if not required:
        return []
    by_date: dict[date, set[str]] = {}
    rows = ImportRun.objects.filter(document_type="balance", status="success").values_list(
        "as_of", "account_id"
    )
    for as_of, account_id in rows:
        by_date.setdefault(as_of, set()).add(account_id)
    return sorted(day for day, accounts in by_date.items() if required <= accounts)


def latest_complete_date() -> date | None:
    days = complete_dates()
    return days[-1] if days else None


def account_status(as_of: date | None) -> list[dict[str, Any]]:
    """계좌별로 그날 잔고를 받았는지, 못 받았으면 무엇이 문제인지."""
    accounts = InvestmentAccount.objects.filter(active=True)
    runs = {
        run.account_id: run
        for run in ImportRun.objects.filter(as_of=as_of, document_type="balance")
    } if as_of else {}
    rows = []
    for account in accounts:
        run = runs.get(account.pk)
        rows.append(
            {
                "account": account.pk,
                "alias": account.alias,
                "account_type": account.get_account_type_display(),
                "required": account.required,
                "masked_number": account.masked_number,
                "status": run.status if run else "missing",
                "error": run.error if run else "",
                "row_count": run.row_count if run else 0,
            }
        )
    return rows
