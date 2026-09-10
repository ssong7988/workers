"""거래에 카테고리를 매긴다.

규칙은 admin이 소유한다(`MerchantRule`). 수집기는 가맹점명만 넘기고 분류에는
관여하지 않으므로, 규칙을 고치면 다시 수집하지 않고 재분류만 하면 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    FINANCIAL_COST_TYPES,
    UNCLASSIFIED_CATEGORY_ID,
    MerchantRule,
    SpendingCategory,
    Transaction,
)


@dataclass
class CategorizeResult:
    by_rule: int = 0
    by_payment_type: int = 0
    unmatched: list[str] = field(default_factory=list)

    @property
    def total_matched(self) -> int:
        return self.by_rule + self.by_payment_type


def financial_cost_category() -> SpendingCategory:
    """연회비·이자가 갈 곳. 지정된 것이 없으면 미분류로 보낸다."""
    category = SpendingCategory.objects.filter(is_financial_cost=True).first()
    return category or unclassified_category()


def unclassified_category() -> SpendingCategory:
    category, _ = SpendingCategory.objects.get_or_create(
        pk=UNCLASSIFIED_CATEGORY_ID,
        defaults={"name": "미분류", "order": 999},
    )
    return category


def classify(merchant_norm: str, rules: list[MerchantRule]) -> MerchantRule | None:
    """먼저 맞는 규칙이 이긴다. 그래서 좁은 규칙이 위에 있어야 한다."""
    if not merchant_norm:
        return None
    for rule in rules:
        if rule.keyword and rule.keyword in merchant_norm:
            return rule
    return None


def categorize(transactions) -> CategorizeResult:
    """넘어온 거래에 카테고리를 매기고 바뀐 것만 저장한다.

    순서가 중요하다. 연회비와 이자는 가맹점 소비가 아니라 청구이므로 결제유형이
    먼저 결정하고, 어떤 키워드도 끼어들지 못한다.
    """
    rules = list(MerchantRule.objects.select_related("category").all())
    financial = financial_cost_category()
    unclassified = unclassified_category()

    result = CategorizeResult()
    unmatched: set[str] = set()
    changed: list[Transaction] = []

    for transaction in transactions:
        if transaction.payment_type in FINANCIAL_COST_TYPES:
            category, source = financial, "payment_type"
            result.by_payment_type += 1
        else:
            matched = classify(transaction.merchant_norm, rules)
            if matched:
                category, source = matched.category, "rule"
                result.by_rule += 1
            else:
                category, source = unclassified, ""
                unmatched.add(transaction.merchant_norm)

        # 사람이 admin에서 직접 지정한 분류는 규칙이 덮지 않는다.
        if transaction.category_source == "manual":
            continue
        if transaction.category_id != category.pk or transaction.category_source != source:
            transaction.category = category
            transaction.category_source = source
            changed.append(transaction)

    if changed:
        Transaction.objects.bulk_update(changed, ["category", "category_source"])
    result.unmatched = sorted(unmatched)
    return result


def recategorize_all() -> CategorizeResult:
    """규칙을 고친 뒤 전체를 다시 분류한다."""
    return categorize(list(Transaction.objects.select_related("category").all()))
