"""Synthetic statements, so the pipeline runs before a real one arrives.

The parser is the one stage that needs an actual statement mail. Everything
downstream — categorization, aggregation, the dashboard — can be exercised and
looked at today against data of the same shape.

Amounts are made up. The generator is seeded, so the same command always
produces the same months and the output is safe to compare against.
"""

from __future__ import annotations

import random
from datetime import date

from .categorize import normalize_merchant
from .models import Statement, Transaction, iso_now


# (merchant, typical amount, times per month) — chains, subscriptions and
# one-offs mixed, so fixed-vs-variable has something real to separate.
RECURRING = [
    ("SK텔레콤 요금", 55_000, 1),
    ("NETFLIX.COM", 17_000, 1),
    ("스타벅스 과천점", 5_600, 6),
    ("GS25 과천점", 4_200, 8),
    ("이마트 과천점", 68_000, 3),
    ("배달의민족", 24_000, 5),
    ("카카오T", 12_000, 4),
    ("SK에너지 주유소", 82_000, 2),
]

OCCASIONAL = [
    ("올리브영 강남점", 38_000),
    ("CGV 평촌", 28_000),
    ("교보문고", 42_000),
    ("동네분식", 9_000),
    ("한빛의원", 15_000),
    ("우리동네 세탁소", 22_000),
    ("쿠팡", 76_000),
    ("무신사", 129_000),
    ("성심당", 31_000),
]

INSTALLMENT = ("삼성전자판매 노트북", 1_800_000, 6)


def _month_sequence(count: int, end: date) -> list[str]:
    months = []
    year, month = end.year, end.month
    for _ in range(count):
        months.append(f"{year}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(months))


def _transaction(month: str, merchant: str, amount: int, day: int, **extra) -> Transaction:
    return Transaction(
        billing_month=month,
        used_at=f"{month}-{day:02d}",
        merchant=merchant,
        merchant_norm=normalize_merchant(merchant),
        billed_won=extra.pop("billed", amount),
        total_won=amount,
        payment_type=extra.pop("payment_type", "일시불"),
        card_last4="4821",
        **extra,
    )


def build_demo_statements(months: int = 7, seed: int = 20260909) -> list[Statement]:
    rng = random.Random(seed)
    sequence = _month_sequence(months, date(2026, 9, 1))
    statements: list[Statement] = []

    installment_name, installment_total, installment_months = INSTALLMENT
    per_installment = installment_total // installment_months
    # The purchase lands partway through, so early months have no instalment and
    # the outlook has something still to come in the latest month.
    installment_start = max(0, len(sequence) - 4)

    for index, month in enumerate(sequence):
        transactions: list[Transaction] = []

        for merchant, typical, times in RECURRING:
            for _ in range(max(1, times + rng.randint(-1, 1))):
                amount = max(1_000, int(typical * rng.uniform(0.8, 1.25) / 100) * 100)
                transactions.append(_transaction(month, merchant, amount, rng.randint(1, 28)))

        for merchant, typical in rng.sample(OCCASIONAL, k=rng.randint(3, 6)):
            amount = max(1_000, int(typical * rng.uniform(0.7, 1.3) / 100) * 100)
            transactions.append(_transaction(month, merchant, amount, rng.randint(1, 28)))

        sequence_number = index - installment_start + 1
        if 1 <= sequence_number <= installment_months:
            transactions.append(
                _transaction(
                    month,
                    installment_name,
                    installment_total,
                    12,
                    billed=per_installment,
                    payment_type="할부",
                    installment_seq=sequence_number,
                    installment_months=installment_months,
                )
            )

        if index == len(sequence) - 1:
            transactions.append(
                _transaction(month, "연회비", 15_000, 1, payment_type="연회비")
            )

        transactions.sort(key=lambda item: item.used_at)
        statements.append(
            Statement(
                billing_month=month,
                payment_date=f"{month}-25",
                total_billed_won=sum(item.billed_won for item in transactions),
                transactions=transactions,
                source_ref="demo",
                parsed_at=iso_now(),
            )
        )

    return statements
