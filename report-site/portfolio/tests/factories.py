"""테스트가 공유하는 최소 픽스처.

실제 H-able 파일 계약은 아직 확정되지 않았으므로, 여기서는 수집기가 넘기기로
한 *정규화된* 형태만 만든다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from hashlib import sha256

from portfolio.models import (
    AssetClass,
    ImportRun,
    Instrument,
    InvestmentAccount,
    PositionSnapshot,
)


def make_account(account_id: str = "kb-brokerage", **kwargs) -> InvestmentAccount:
    return InvestmentAccount.objects.create(
        id=account_id,
        alias=kwargs.pop("alias", account_id),
        account_type=kwargs.pop("account_type", "brokerage"),
        **kwargs,
    )


def make_asset_class(class_id: str, name: str, benchmark: str = "", order: int = 10):
    return AssetClass.objects.create(
        id=class_id, name=name, benchmark_category=benchmark, display_order=order
    )


def make_instrument(code: str, asset_class: AssetClass, **kwargs) -> Instrument:
    return Instrument.objects.create(
        code=code, name=kwargs.pop("name", code), asset_class=asset_class, **kwargs
    )


def hash_of(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def balance_payload(
    account: str,
    as_of: str,
    rows: list[dict],
    *,
    file_hash: str | None = None,
    cash_flows: list[dict] | None = None,
) -> dict:
    return {
        "account": account,
        "as_of": as_of,
        "document_type": "balance",
        "file_hash": file_hash or hash_of(f"{account}:{as_of}"),
        "source_name": f"0345_{as_of}.csv",
        "positions": rows,
        "cash_flows": cash_flows or [],
    }


def position(code: str, value: str, **kwargs) -> dict:
    return {
        "code": code,
        "name": kwargs.pop("name", code),
        "quantity": kwargs.pop("quantity", "1"),
        "market_value": value,
        "market_value_krw": kwargs.pop("market_value_krw", value),
        **kwargs,
    }


def record_balance(
    account: InvestmentAccount,
    instrument: Instrument,
    as_of: date,
    value: str,
) -> PositionSnapshot:
    """API를 거치지 않고 완전 스냅샷 한 줄을 만든다(성과 계산 테스트용)."""
    run, _ = ImportRun.objects.get_or_create(
        account=account,
        document_type="balance",
        as_of=as_of,
        defaults={"file_hash": hash_of(f"{account.pk}{as_of}"), "row_count": 1},
    )
    return PositionSnapshot.objects.create(
        as_of=as_of,
        account=account,
        instrument=instrument,
        import_run=run,
        quantity=Decimal("1"),
        market_value=Decimal(value),
        market_value_krw=Decimal(value),
    )
