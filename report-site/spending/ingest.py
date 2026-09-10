"""수집기가 넘긴 명세서 한 통을 받아 저장한다.

명세서는 월 단위 스냅샷이라 **그 달을 통째로 바꾼다.** 재발송본이나 정정본이
와도 거래를 합치지 않고 지운 뒤 다시 넣으므로, 중복 판정 로직이 필요 없고
정정된 금액이 옛 행과 섞이지도 않는다.

행 합계가 명세서 스스로 적어둔 청구총액과 어긋나면 저장하지 않고 거절한다.
부분만 저장된 소비 분석은 없느니만 못하다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from django.db import transaction as db_transaction

from .categorize import categorize, unclassified_category
from .models import (
    PAYMENT_TYPE_LABELS,
    Statement,
    Transaction,
    normalize_merchant,
    validate_billing_month,
)

# 수집기는 명세서에 찍힌 한글 구분을 그대로 넘긴다. 저장은 코드로 한다.
LABEL_TO_PAYMENT_TYPE = {label: code for code, label in PAYMENT_TYPE_LABELS.items()}


class IngestError(ValueError):
    """넘어온 명세서를 저장할 수 없을 때."""


@dataclass
class IngestResult:
    billing_month: str
    created: bool
    transaction_count: int
    total_billed_won: int
    replaced_count: int = 0

    def describe(self) -> str:
        what = "새로 저장" if self.created else f"교체(기존 {self.replaced_count}건)"
        return (
            f"{self.billing_month} {what}: {self.transaction_count}건, "
            f"{self.total_billed_won:,}원"
        )


def _date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise IngestError(f"{field}는 YYYY-MM-DD여야 합니다: {value!r}") from exc


def _int(value, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise IngestError(f"{field}는 정수여야 합니다: {value!r}") from exc


def _payment_type(raw: str) -> str:
    """한글 구분을 코드로. 모르는 구분은 버리지 않고 기타로 받는다."""
    text = (raw or "").strip()
    if text in LABEL_TO_PAYMENT_TYPE:
        return LABEL_TO_PAYMENT_TYPE[text]
    if text in PAYMENT_TYPE_LABELS:
        return text
    return "other"


def _rows(payload: dict) -> list[dict]:
    rows = payload.get("transactions")
    if not isinstance(rows, list):
        raise IngestError("transactions는 배열이어야 합니다.")
    if not rows:
        raise IngestError("거래가 하나도 없습니다.")
    return rows


@db_transaction.atomic
def ingest_statement(payload: dict) -> IngestResult:
    """명세서 한 통을 저장하고 그 달을 통째로 교체한다."""
    billing_month = str(payload.get("billing_month", "")).strip()
    try:
        validate_billing_month(billing_month)
    except Exception as exc:
        raise IngestError(f"청구월이 올바르지 않습니다: {billing_month!r}") from exc

    total = _int(payload.get("total_billed_won"), "total_billed_won")
    rows = _rows(payload)

    parsed_total = sum(_int(row.get("billed_won"), "billed_won") for row in rows)
    if parsed_total != total:
        raise IngestError(
            "행 합계가 명세서의 청구총액과 다릅니다. 저장하지 않았습니다. "
            f"(행 {parsed_total:,}원, 청구총액 {total:,}원, 차이 {parsed_total - total:,}원)"
        )

    statement, created = Statement.objects.update_or_create(
        billing_month=billing_month,
        defaults={
            "payment_date": _date(payload.get("payment_date"), "payment_date"),
            "total_billed_won": total,
            "source_ref": str(payload.get("source_ref", ""))[:200],
            "parsed_at": _parsed_at(payload.get("parsed_at")),
        },
    )

    replaced = statement.transactions.count()
    statement.transactions.all().delete()

    unclassified = unclassified_category()
    saved = [
        Transaction(
            statement=statement,
            used_at=_date(row.get("used_at"), "used_at") or date.fromisoformat(f"{billing_month}-01"),
            merchant=str(row.get("merchant", ""))[:200],
            merchant_norm=normalize_merchant(str(row.get("merchant", "")))[:200],
            billed_won=_int(row.get("billed_won"), "billed_won"),
            total_won=_int(row.get("total_won", row.get("billed_won")), "total_won"),
            payment_type=_payment_type(row.get("payment_type", "")),
            installment_seq=_int(row.get("installment_seq", 0), "installment_seq"),
            installment_months=_int(row.get("installment_months", 0), "installment_months"),
            card_last4=str(row.get("card_last4", ""))[:4],
            category=unclassified,
        )
        for row in rows
    ]
    Transaction.objects.bulk_create(saved)

    # 저장 직후 분류한다. 규칙이 나중에 바뀌면 recategorize_all이 다시 매긴다.
    categorize(list(statement.transactions.select_related("category")))

    return IngestResult(
        billing_month=billing_month,
        created=created,
        transaction_count=len(saved),
        total_billed_won=total,
        replaced_count=replaced,
    )


def _parsed_at(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    from django.utils import timezone

    if timezone.is_naive(moment):
        return timezone.make_aware(moment, timezone.get_current_timezone())
    return moment
