"""Aggregate stored statements into the numbers the dashboard shows.

Everything here is a pure function over `Statement` objects — no browser, no
network, no file access — so the arithmetic can be tested directly.

All totals are on the billing basis: `Transaction.billed_won`, what that month's
statement actually charged. An instalment contributes only its instalment for the
month, so a month's total matches what left the account.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .categorize import RuleSet
from .models import UNCATEGORIZED, AnalysisConfig, Statement, Transaction, iso_now


AVERAGE_WINDOW = 6
INSTALMENT_PROJECTION_MONTHS = 12


def next_month(month: str) -> str:
    year, number = (int(part) for part in month.split("-"))
    return f"{year + 1}-01" if number == 12 else f"{year}-{number + 1:02d}"


def month_of(value: date) -> str:
    return f"{value.year}-{value.month:02d}"


def _share(part: int, whole: int) -> float:
    """Share of a total, guarding the zero-total month.

    A month can legitimately total zero — every purchase cancelled, or a
    statement with only reversals — and a share is undefined there rather than
    infinite.
    """
    return round(part / whole, 4) if whole else 0.0


def _percent_change(current: int, previous: int) -> float | None:
    """None rather than a fake number when there is no previous month to compare."""
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

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "total": self.total,
            "count": self.count,
            "delta": self.delta,
            "percent": self.percent,
        }


def monthly_totals(statements: list[Statement]) -> list[MonthTotal]:
    """Billed total per month, oldest first, with month-over-month change.

    The change is only filled in where the previous month is genuinely the one
    before — a gap in the statements leaves it empty rather than comparing
    across the hole.
    """
    ordered = sorted(statements, key=lambda item: item.billing_month)
    results: list[MonthTotal] = []
    for index, statement in enumerate(ordered):
        entry = MonthTotal(
            month=statement.billing_month,
            total=statement.parsed_total_won,
            count=len(statement.transactions),
        )
        if index:
            previous = ordered[index - 1]
            if next_month(previous.billing_month) == statement.billing_month:
                entry.delta = entry.total - previous.parsed_total_won
                entry.percent = _percent_change(entry.total, previous.parsed_total_won)
        results.append(entry)
    return results


def trailing_average(totals: list[MonthTotal], window: int = AVERAGE_WINDOW) -> int:
    if not totals:
        return 0
    recent = totals[-window:]
    return round(sum(item.total for item in recent) / len(recent))


def category_totals(transactions: list[Transaction]) -> dict[str, int]:
    sums: dict[str, int] = defaultdict(int)
    for transaction in transactions:
        sums[transaction.category or UNCATEGORIZED] += transaction.billed_won
    return dict(sums)


def category_breakdown(
    current: list[Transaction], previous: list[Transaction] | None = None
) -> list[dict]:
    """Category totals for a month, with the previous month's for comparison.

    Categories that vanished this month are still listed, at zero, because a
    category dropping to nothing is exactly the change worth seeing.
    """
    now = category_totals(current)
    before = category_totals(previous or [])
    whole = sum(now.values())
    rows = []
    for category in sorted(set(now) | set(before), key=lambda name: -now.get(name, 0)):
        total = now.get(category, 0)
        prior = before.get(category, 0)
        rows.append(
            {
                "category": category,
                "total": total,
                "share": _share(total, whole),
                "previous": prior,
                "delta": total - prior,
                "percent": _percent_change(total, prior),
            }
        )
    return rows


def category_series(statements: list[Statement]) -> dict[str, dict[str, int]]:
    """Per-category totals across every month, for the trend charts."""
    series: dict[str, dict[str, int]] = defaultdict(dict)
    for statement in sorted(statements, key=lambda item: item.billing_month):
        for category, total in category_totals(statement.transactions).items():
            series[category][statement.billing_month] = total
    return {name: dict(months) for name, months in series.items()}


def payment_type_mix(transactions: list[Transaction]) -> list[dict]:
    sums: dict[str, int] = defaultdict(int)
    for transaction in transactions:
        sums[transaction.payment_type or "기타"] += transaction.billed_won
    whole = sum(sums.values())
    return [
        {"type": name, "total": total, "share": _share(total, whole)}
        for name, total in sorted(sums.items(), key=lambda pair: -pair[1])
    ]


def installment_outlook(statement: Statement) -> dict:
    """What the instalments on this statement will still cost in future months.

    Only the latest statement is read. Every statement re-lists its active
    instalments at that month's sequence number, so summing across months would
    count the same purchase many times over.
    """
    active = [
        item
        for item in statement.transactions
        if item.is_installment and item.remaining_installments > 0
    ]
    rows = []
    projection: dict[str, int] = defaultdict(int)
    for transaction in sorted(active, key=lambda item: -item.billed_won):
        rows.append(
            {
                "merchant": transaction.merchant,
                "totalWon": transaction.total_won,
                "perMonth": transaction.billed_won,
                "sequence": transaction.installment_seq,
                "months": transaction.installment_months,
                "remaining": transaction.remaining_installments,
                "remainingWon": transaction.billed_won * transaction.remaining_installments,
            }
        )
        month = statement.billing_month
        for _ in range(min(transaction.remaining_installments, INSTALMENT_PROJECTION_MONTHS)):
            month = next_month(month)
            projection[month] += transaction.billed_won

    return {
        "active": rows,
        "futureTotal": sum(row["remainingWon"] for row in rows),
        "byMonth": [
            {"month": month, "total": total} for month, total in sorted(projection.items())
        ],
    }


def top_merchants(
    transactions: list[Transaction], rules: RuleSet, limit: int = 15
) -> list[dict]:
    """Biggest merchants, with a chain's branches counted as one."""
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for transaction in transactions:
        key = rules.canonical(transaction.merchant_norm)
        totals[key] += transaction.billed_won
        counts[key] += 1
        labels.setdefault(key, transaction.merchant)

    ranked = sorted(totals.items(), key=lambda pair: -pair[1])[:limit]
    return [
        {
            "merchant": key,
            "example": labels[key],
            "total": total,
            "count": counts[key],
            "average": round(total / counts[key]),
        }
        for key, total in ranked
    ]


def fixed_costs(statements: list[Statement], rules: RuleSet, window: int) -> dict:
    """Split spending into what recurs every month and what does not.

    A merchant seen in more than half of the last `window` months counts as
    fixed. With fewer than `window` months on hand the split is not meaningful
    yet, so it is reported as unavailable rather than guessed from one or two
    statements.
    """
    ordered = sorted(statements, key=lambda item: item.billing_month)[-window:]
    if len(ordered) < window:
        return {"available": False, "months": len(ordered), "required": window, "merchants": []}

    seen: dict[str, set[str]] = defaultdict(set)
    totals: dict[str, int] = defaultdict(int)
    categories: dict[str, str] = {}
    for statement in ordered:
        for transaction in statement.transactions:
            key = rules.canonical(transaction.merchant_norm)
            seen[key].add(statement.billing_month)
            totals[key] += transaction.billed_won
            categories.setdefault(key, transaction.category)

    threshold = window / 2
    merchants = [
        {
            "merchant": key,
            "category": categories.get(key, UNCATEGORIZED),
            "monthsSeen": len(months),
            "total": totals[key],
            "average": round(totals[key] / len(months)),
        }
        for key, months in seen.items()
        if len(months) > threshold
    ]
    merchants.sort(key=lambda row: -row["average"])

    fixed_total = sum(row["total"] for row in merchants)
    grand_total = sum(totals.values())
    return {
        "available": True,
        "months": len(ordered),
        "required": window,
        "merchants": merchants,
        "fixedTotal": fixed_total,
        "variableTotal": grand_total - fixed_total,
        "fixedShare": _share(fixed_total, grand_total),
    }


def uncategorized_merchants(transactions: list[Transaction]) -> list[dict]:
    """Unknown merchants, biggest first — the queue for improving the rules."""
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for transaction in transactions:
        if transaction.category != UNCATEGORIZED:
            continue
        totals[transaction.merchant_norm] += transaction.billed_won
        counts[transaction.merchant_norm] += 1
        labels.setdefault(transaction.merchant_norm, transaction.merchant)
    return [
        {"merchant": key, "example": labels[key], "total": total, "count": counts[key]}
        for key, total in sorted(totals.items(), key=lambda pair: -pair[1])
    ]


def budget_status(transactions: list[Transaction], budgets: tuple[tuple[str, int], ...]) -> list[dict]:
    if not budgets:
        return []
    spent = category_totals(transactions)
    return [
        {
            "category": category,
            "budget": amount,
            "spent": spent.get(category, 0),
            "ratio": _share(spent.get(category, 0), amount),
        }
        for category, amount in budgets
    ]


def analyze(
    statements: list[Statement], rules: RuleSet, config: AnalysisConfig
) -> dict:
    """The whole dashboard payload, ready to be written as analysis.json."""
    ordered = sorted(statements, key=lambda item: item.billing_month)
    if not ordered:
        return {"generatedAt": iso_now(), "months": [], "latest": None, "empty": True}

    latest = ordered[-1]
    previous = ordered[-2] if len(ordered) > 1 else None
    if previous and next_month(previous.billing_month) != latest.billing_month:
        previous = None

    totals = monthly_totals(ordered)
    every_transaction = [item for statement in ordered for item in statement.transactions]

    return {
        "generatedAt": iso_now(),
        "empty": False,
        "latest": latest.billing_month,
        "paymentDate": latest.payment_date,
        "months": [item.to_dict() for item in totals],
        "trailingAverage": trailing_average(totals),
        "latestTotal": latest.parsed_total_won,
        "categories": category_breakdown(
            latest.transactions, previous.transactions if previous else None
        ),
        "categorySeries": category_series(ordered),
        "paymentTypes": payment_type_mix(latest.transactions),
        "installments": installment_outlook(latest),
        "topMerchants": top_merchants(latest.transactions, rules, config.top_merchants),
        "fixedCosts": fixed_costs(ordered, rules, config.fixed_cost_months),
        "uncategorized": uncategorized_merchants(every_transaction),
        "budgets": budget_status(latest.transactions, config.budgets),
        "transactions": [item.to_dict() for item in latest.transactions],
    }
