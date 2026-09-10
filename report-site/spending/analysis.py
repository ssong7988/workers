"""화면과 카카오 요약이 쓰는 집계.

전부 순수 계산이라 브라우저도 네트워크도 필요 없다. 금액은 모두 청구 기준
(`Transaction.billed_won`)이므로 한 달 합계가 통장에서 빠진 돈과 일치한다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Count, Q, Sum

from .models import (
    UNCLASSIFIED_CATEGORY_ID,
    SpendingGroup,
    Statement,
    Transaction,
)

AVERAGE_WINDOW = 6
TOP_MERCHANTS = 15
INSTALMENT_PROJECTION_MONTHS = 12


def counted(statement: Statement):
    """집계에 넣을 거래.

    제외 표시된 줄은 여기서 빠진다. 대신 결제해 주고 돌려받는 돈 같은 것이라
    내 소비가 아니다. 명세서와의 금액 대조는 `Statement.parsed_total_won`이
    따로 들고 있으므로, 여기서 빼도 그 검증은 깨지지 않는다.
    """
    return statement.transactions.filter(excluded=False)


def next_month(month: str) -> str:
    year, number = (int(part) for part in month.split("-"))
    return f"{year + 1}-01" if number == 12 else f"{year}-{number + 1:02d}"


def _share(part: int, whole: int) -> float:
    """0원인 달에서 비중은 무한대가 아니라 정의되지 않는다."""
    return round(part / whole, 4) if whole else 0.0


def _percent_change(current: int, previous: int) -> float | None:
    """비교할 직전 달이 없으면 숫자를 지어내지 않는다."""
    if not previous:
        return None
    return round((current - previous) / abs(previous), 4)


@dataclass
class MonthTotal:
    month: str
    total: int
    count: int
    delta: int | None = None
    percent: float | None = None


def monthly_totals() -> list[MonthTotal]:
    """청구월별 합계. 오래된 달이 먼저다.

    증감은 직전 달이 **정말로 바로 앞 달일 때만** 채운다. 명세서가 빠진 구간을
    건너뛰고 비교하면 없는 추세를 지어내게 된다.
    """
    rows = (
        Statement.objects.annotate(
            # 제외한 줄은 월별 합계에도 들어가지 않는다.
            billed=Sum(
                "transactions__billed_won", filter=Q(transactions__excluded=False)
            ),
            rows=Count("transactions", filter=Q(transactions__excluded=False)),
        )
        .order_by("billing_month")
        .values("billing_month", "billed", "rows")
    )
    results: list[MonthTotal] = []
    for index, row in enumerate(rows):
        entry = MonthTotal(
            month=row["billing_month"],
            total=row["billed"] or 0,
            count=row["rows"] or 0,
        )
        if index:
            previous = results[index - 1]
            if next_month(previous.month) == entry.month:
                entry.delta = entry.total - previous.total
                entry.percent = _percent_change(entry.total, previous.total)
        results.append(entry)
    return results


def trailing_average(totals: list[MonthTotal], window: int = AVERAGE_WINDOW) -> int:
    if not totals:
        return 0
    recent = totals[-window:]
    return round(sum(item.total for item in recent) / len(recent))


def category_rows(statement: Statement, previous: Statement | None) -> list[dict]:
    """카테고리별 합계와 직전 달 대비.

    이번 달 사라진 카테고리도 0원으로 남긴다. 어떤 카테고리가 통째로 없어진
    것이야말로 볼 가치가 있는 변화다.
    """
    now = _category_totals(statement)
    before = _category_totals(previous) if previous else {}
    # 값이 (금액, 이름) 쌍이라 금액만 더한다.
    whole = sum(total for total, _ in now.values())

    rows = []
    for key in set(now) | set(before):
        total, name = now.get(key, (0, before.get(key, (0, key))[1]))
        prior = before.get(key, (0, name))[0]
        rows.append(
            {
                "id": key,
                "name": name,
                "total": total,
                "share": _share(total, whole),
                "previous": prior,
                "delta": total - prior,
                "percent": _percent_change(total, prior),
                "unclassified": key == UNCLASSIFIED_CATEGORY_ID,
            }
        )
    rows.sort(key=lambda row: -row["total"])
    return rows


def _category_totals(statement: Statement | None) -> dict[str, tuple[int, str]]:
    if statement is None:
        return {}
    rows = (
        counted(statement).values("category_id", "category__name")
        .annotate(total=Sum("billed_won"))
        .order_by()
    )
    return {
        row["category_id"]: (row["total"] or 0, row["category__name"])
        for row in rows
    }


def group_rows(statement: Statement, previous: Statement | None = None) -> list[dict]:
    """대분류별 합계와 비중.

    카테고리 열여섯 개로는 한 달의 성격이 안 보인다. 이 표가 답하는 질문은
    하나다 - 줄일 수 없는 돈이 얼마고 내가 조절하는 돈이 얼마인가.

    합계가 0인 대분류도 남긴다. 이번 달에 안 쓴 것 자체가 비교할 값이고,
    조각 색이 달마다 자리를 바꾸지 않게 하려면 순서가 고정돼야 한다.
    """
    now = _group_totals(statement)
    before = _group_totals(previous) if previous else {}
    whole = sum(now.values())

    rows = []
    for group in SpendingGroup.objects.all():
        total = now.get(group.pk, 0)
        prior = before.get(group.pk, 0)
        rows.append(
            {
                "id": group.pk,
                "name": group.name,
                "note": group.note,
                "color": group.color,
                "total": total,
                "share": _share(total, whole),
                "previous": prior,
                "delta": total - prior,
                "percent": _percent_change(total, prior),
            }
        )
    return rows


def _group_totals(statement: Statement | None) -> dict[str, int]:
    if statement is None:
        return {}
    rows = (
        counted(statement).values("category__group_id")
        .annotate(total=Sum("billed_won"))
        .order_by()
    )
    return {
        row["category__group_id"]: row["total"] or 0
        for row in rows
        if row["category__group_id"]
    }


def group_series(months: int = 12) -> dict:
    """최근 달들의 대분류 구성. 성격이 어떻게 변해 왔는지 본다."""
    statements = list(Statement.objects.order_by("billing_month"))[-months:]
    groups = list(SpendingGroup.objects.all())
    series = []
    for statement in statements:
        totals = _group_totals(statement)
        whole = sum(totals.values())
        series.append(
            {
                "month": statement.billing_month,
                "total": whole,
                "parts": [
                    {
                        "id": group.pk,
                        "name": group.name,
                        "color": group.color,
                        "total": totals.get(group.pk, 0),
                        "share": _share(totals.get(group.pk, 0), whole),
                    }
                    for group in groups
                ],
            }
        )
    return {"groups": groups, "months": series}


def payment_type_rows(statement: Statement) -> list[dict]:
    rows = (
        counted(statement).values("payment_type")
        .annotate(total=Sum("billed_won"))
        .order_by()
    )
    whole = sum(row["total"] or 0 for row in rows)
    from .models import PAYMENT_TYPE_LABELS

    return sorted(
        (
            {
                "type": row["payment_type"],
                "name": PAYMENT_TYPE_LABELS.get(row["payment_type"], row["payment_type"]),
                "total": row["total"] or 0,
                "share": _share(row["total"] or 0, whole),
            }
            for row in rows
        ),
        key=lambda row: -row["total"],
    )


def installment_outlook(statement: Statement) -> dict:
    """이 명세서의 할부가 앞으로 더 청구할 금액.

    **최신 명세서만 읽는다.** 모든 명세서가 진행 중인 할부를 그 달 회차로 다시
    싣기 때문에, 여러 달을 합치면 같은 구매를 몇 번이고 세게 된다.
    """
    active = [
        item
        for item in counted(statement)
        if item.is_installment and item.remaining_installments > 0
    ]
    projection: dict[str, int] = defaultdict(int)
    rows = []
    for item in sorted(active, key=lambda t: -t.billed_won):
        rows.append(
            {
                "merchant": item.merchant,
                "total_won": item.total_won,
                "per_month": item.billed_won,
                "sequence": item.installment_seq,
                "months": item.installment_months,
                "remaining": item.remaining_installments,
                "remaining_won": item.billed_won * item.remaining_installments,
            }
        )
        month = statement.billing_month
        for _ in range(min(item.remaining_installments, INSTALMENT_PROJECTION_MONTHS)):
            month = next_month(month)
            projection[month] += item.billed_won

    return {
        "active": rows,
        "future_total": sum(row["remaining_won"] for row in rows),
        "by_month": [{"month": m, "total": t} for m, t in sorted(projection.items())],
    }


def top_merchants(statement: Statement, limit: int = TOP_MERCHANTS) -> list[dict]:
    rows = (
        counted(statement).values("merchant_norm")
        .annotate(total=Sum("billed_won"), count=Count("id"))
        .order_by("-total")[:limit]
    )
    names = {
        item.merchant_norm: item.merchant
        for item in counted(statement)
    }
    return [
        {
            "merchant": names.get(row["merchant_norm"], row["merchant_norm"]),
            "total": row["total"] or 0,
            "count": row["count"],
            "average": round((row["total"] or 0) / row["count"]) if row["count"] else 0,
        }
        for row in rows
    ]


def unclassified_merchants(limit: int = 30) -> list[dict]:
    """규칙을 만들 차례를 정해주는 목록. 합계가 큰 순이다."""
    rows = (
        Transaction.objects.filter(
        category_id=UNCLASSIFIED_CATEGORY_ID, excluded=False
    )
        .values("merchant_norm")
        .annotate(total=Sum("billed_won"), count=Count("id"))
        .order_by("-total")[:limit]
    )
    names = {
        item.merchant_norm: item.merchant
        for item in Transaction.objects.filter(
        category_id=UNCLASSIFIED_CATEGORY_ID, excluded=False
    )
    }
    return [
        {
            "merchant": names.get(row["merchant_norm"], row["merchant_norm"]),
            "keyword": row["merchant_norm"],
            "total": row["total"] or 0,
            "count": row["count"],
        }
        for row in rows
    ]


@dataclass
class MonthView:
    statement: Statement
    previous: Statement | None
    totals: list[MonthTotal] = field(default_factory=list)

    @property
    def total(self) -> int:
        """화면과 요약이 쓰는 합계. 제외한 줄은 빠진다."""
        return self.statement.analysed_total_won


def latest_statement() -> Statement | None:
    return Statement.objects.order_by("-billing_month").first()


def month_view(billing_month: str | None = None) -> MonthView | None:
    """한 청구월과, 비교 대상이 될 자격이 있는 직전 달."""
    statement = (
        Statement.objects.filter(billing_month=billing_month).first()
        if billing_month
        else latest_statement()
    )
    if statement is None:
        return None
    previous = (
        Statement.objects.filter(billing_month__lt=statement.billing_month)
        .order_by("-billing_month")
        .first()
    )
    if previous and next_month(previous.billing_month) != statement.billing_month:
        previous = None
    return MonthView(statement=statement, previous=previous, totals=monthly_totals())
