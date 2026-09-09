"""Assign a spending category to each transaction.

Rules run first and cost nothing. Whatever they miss goes to the AI fallback in
`claude_client`, and confirmed answers are promoted back into `rules.yaml` so the
same merchant never needs the API twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import FINANCIAL_COST_TYPES, UNCATEGORIZED, Transaction
from .storage import write_json


FINANCIAL_COST_CATEGORY = "금융비용"

# Corporate forms carry no information and differ between statements for the
# same merchant, so they are stripped before any matching happens.
_CORPORATE = re.compile(r"\(주\)|\(유\)|㈜|주식회사|유한회사")
_WHITESPACE = re.compile(r"\s+")


def normalize_merchant(raw: str) -> str:
    """Collapse a statement's merchant name to a stable matching key.

    Branch suffixes are deliberately left in place: rules match by substring,
    so "스타벅스" already catches "스타벅스과천점", and stripping the suffix by
    guesswork would mangle names that legitimately end in those characters.
    """
    text = _CORPORATE.sub("", raw or "")
    text = _WHITESPACE.sub("", text)
    return text.upper()


@dataclass(frozen=True)
class Rule:
    category: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class RuleMatch:
    category: str
    keyword: str


@dataclass
class RuleSet:
    categories: tuple[str, ...]
    rules: tuple[Rule, ...]

    def match(self, merchant_norm: str) -> RuleMatch | None:
        """First matching rule wins, so narrower rules must be listed first."""
        if not merchant_norm:
            return None
        for rule in self.rules:
            for keyword in rule.keywords:
                if keyword and keyword in merchant_norm:
                    return RuleMatch(rule.category, keyword)
        return None

    def canonical(self, merchant_norm: str) -> str:
        """A display name that groups a chain's branches together.

        "스타벅스과천점" and "스타벅스판교점" both reduce to the keyword that
        matched them, so merchant rankings count a chain once. Unknown
        merchants keep their own normalized name.
        """
        matched = self.match(merchant_norm)
        return matched.keyword if matched else merchant_norm


def load_rules(path: Path) -> RuleSet:
    if not path.exists():
        raise ValueError(f"규칙 파일이 없습니다: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    categories = tuple(str(item) for item in raw.get("categories", []))
    if not categories:
        raise ValueError("rules.yaml에 categories가 비어 있습니다.")
    if UNCATEGORIZED in categories:
        raise ValueError(f"'{UNCATEGORIZED}'는 예약된 이름이라 categories에 넣을 수 없습니다.")

    rules: list[Rule] = []
    for index, item in enumerate(raw.get("rules", []), start=1):
        category = str(item.get("category", "")).strip()
        if not category:
            raise ValueError(f"{index}번째 규칙에 category가 없습니다.")
        if category not in categories:
            raise ValueError(f"규칙의 category가 categories 목록에 없습니다: {category}")
        keywords = tuple(
            normalize_merchant(str(word)) for word in item.get("keywords", []) if str(word).strip()
        )
        if not keywords:
            raise ValueError(f"{category} 규칙에 keywords가 비어 있습니다.")
        rules.append(Rule(category=category, keywords=keywords))

    if not rules:
        raise ValueError("rules.yaml에 rules가 비어 있습니다.")
    return RuleSet(categories=categories, rules=tuple(rules))


@dataclass
class CategorizeResult:
    by_rule: int = 0
    by_cache: int = 0
    by_payment_type: int = 0
    unmatched: list[str] = field(default_factory=list)

    @property
    def total_matched(self) -> int:
        return self.by_rule + self.by_cache + self.by_payment_type


def categorize(
    transactions: list[Transaction],
    rules: RuleSet,
    cache: dict[str, str] | None = None,
) -> CategorizeResult:
    """Set `category` on every transaction it can, in place.

    Order matters. The payment type settles annual fees and interest outright —
    those are charges, not spending at a merchant, so no keyword should ever get
    a say. Rules come next, then the AI cache from previous runs.
    """
    lookup = cache or {}
    result = CategorizeResult()
    unmatched: set[str] = set()

    for transaction in transactions:
        if transaction.payment_type in FINANCIAL_COST_TYPES:
            transaction.category = FINANCIAL_COST_CATEGORY
            transaction.category_source = "payment_type"
            result.by_payment_type += 1
            continue

        matched = rules.match(transaction.merchant_norm)
        if matched:
            transaction.category = matched.category
            transaction.category_source = "rule"
            result.by_rule += 1
            continue

        cached = lookup.get(transaction.merchant_norm)
        if cached and cached in rules.categories:
            transaction.category = cached
            transaction.category_source = "ai"
            result.by_cache += 1
            continue

        transaction.category = UNCATEGORIZED
        transaction.category_source = ""
        unmatched.add(transaction.merchant_norm)

    result.unmatched = sorted(unmatched)
    return result


def load_cache(path: Path) -> dict[str, str]:
    import json

    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A corrupt cache is a performance loss, not a reason to fail a run.
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save_cache(path: Path, cache: dict[str, str]) -> None:
    write_json(path, dict(sorted(cache.items())))


def promote_to_rules(path: Path, assignments: dict[str, str]) -> int:
    """Fold confirmed AI answers into rules.yaml so they cost nothing next month.

    Each merchant becomes its own keyword under its category. The file is
    rewritten rather than edited in place, so comments in the original are lost —
    the header comment is re-emitted to keep the file self-explanatory.
    """
    if not assignments:
        return 0
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    categories = [str(item) for item in raw.get("categories", [])]
    rules = raw.get("rules", [])

    by_category: dict[str, list] = {}
    for rule in rules:
        by_category.setdefault(str(rule.get("category", "")), []).append(rule)

    added = 0
    for merchant, category in sorted(assignments.items()):
        if category not in categories or not merchant:
            continue
        buckets = by_category.get(category)
        if buckets:
            target = buckets[-1]
            keywords = target.setdefault("keywords", [])
        else:
            target = {"category": category, "keywords": []}
            rules.append(target)
            by_category[category] = [target]
            keywords = target["keywords"]
        if merchant not in keywords:
            keywords.append(merchant)
            added += 1

    if added:
        header = (
            "# 가맹점 키워드 → 카테고리 규칙\n"
            "#\n"
            "# 이 파일은 `categorize --promote`가 다시 쓸 수 있습니다.\n"
            "# 위에서부터 먼저 맞는 규칙이 이기므로, 좁은 규칙을 위에 두세요.\n\n"
        )
        body = yaml.safe_dump(
            {"categories": categories, "rules": rules},
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )
        path.write_text(header + body, encoding="utf-8")
    return added
