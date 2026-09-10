"""Domain models shared by mail collection, parsing, categorization, and analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


UNCATEGORIZED = "미분류"

# Payment types as the statement itself separates them. `금융비용` covers the
# annual fee and interest rows, which are charges rather than spending and are
# categorized without ever going through the merchant rules.
PAYMENT_TYPES = ("일시불", "할부", "현금서비스", "해외", "연회비", "이자", "기타")
FINANCIAL_COST_TYPES = ("연회비", "이자")


@dataclass
class Transaction:
    """One billed line of a statement.

    Amounts follow the billing basis: `billed_won` is what this month's
    statement charges, so an installment contributes only its instalment for
    the month. `total_won` keeps the original purchase amount so the used
    basis stays available later without re-parsing.
    """

    billing_month: str  # "2026-09" — the axis every aggregate groups by
    used_at: str  # ISO date the purchase was made
    merchant: str  # as printed on the statement
    merchant_norm: str  # normalized; the key for rules and grouping
    billed_won: int  # charged this month; cancellations are negative
    total_won: int  # original amount (equals billed_won when paid in full)
    payment_type: str
    installment_seq: int = 0  # the 3 of "3/6회차"
    installment_months: int = 0  # the 6 of "3/6회차"
    card_last4: str = ""  # only ever the last four digits
    category: str = UNCATEGORIZED
    category_source: str = ""  # rule | ai | manual

    @property
    def is_installment(self) -> bool:
        return self.installment_months > 1

    @property
    def remaining_installments(self) -> int:
        """How many instalments after this one are still to be charged."""
        if not self.is_installment:
            return 0
        return max(0, self.installment_months - self.installment_seq)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transaction":
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})


@dataclass
class Statement:
    """One month's statement, stored and replaced as a whole.

    A statement is a monthly snapshot, so a re-sent or corrected copy replaces
    the stored month outright. That is why nothing here needs per-transaction
    deduplication.
    """

    billing_month: str
    payment_date: str
    total_billed_won: int  # the header total; the yardstick for parse checks
    transactions: list[Transaction] = field(default_factory=list)
    source_ref: str = ""  # originating mail Message-ID
    parsed_at: str = ""
    # 건수가 명세서의 소계와 다를 때 남기는 메모. 거절 사유는 아니다 - 카드사가
    # 0원짜리 줄을 달마다 다르게 세기 때문이며, 금액은 그와 무관하게 맞는다.
    count_notes: list[str] = field(default_factory=list)

    @property
    def parsed_total_won(self) -> int:
        return sum(item.billed_won for item in self.transactions)

    @property
    def discrepancy_won(self) -> int:
        """Signed gap between the parsed rows and the statement's own total."""
        return self.parsed_total_won - self.total_billed_won

    def to_dict(self) -> dict[str, Any]:
        return {
            "billing_month": self.billing_month,
            "payment_date": self.payment_date,
            "total_billed_won": self.total_billed_won,
            "source_ref": self.source_ref,
            "parsed_at": self.parsed_at,
            "transactions": [item.to_dict() for item in self.transactions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Statement":
        return cls(
            billing_month=data["billing_month"],
            payment_date=data.get("payment_date", ""),
            total_billed_won=int(data["total_billed_won"]),
            transactions=[Transaction.from_dict(item) for item in data.get("transactions", [])],
            source_ref=data.get("source_ref", ""),
            parsed_at=data.get("parsed_at", ""),
        )


@dataclass(frozen=True)
class MailConfig:
    host: str = "imap.gmail.com"
    port: int = 993
    folder: str = "INBOX"
    senders: tuple[str, ...] = ()
    subject_keywords: tuple[str, ...] = ()
    since: str = ""  # "YYYY-MM-DD"; empty means no lower bound


@dataclass(frozen=True)
class AnalysisConfig:
    # A merchant seen in more than half of the last N months counts as fixed cost.
    fixed_cost_months: int = 3
    top_merchants: int = 15
    budgets: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class AiConfig:
    enabled: bool = True
    model: str = "claude-opus-5"
    batch_size: int = 200


@dataclass(frozen=True)
class AppConfig:
    mail: MailConfig
    analysis: AnalysisConfig
    ai: AiConfig
    timezone: str = "Asia/Seoul"


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
