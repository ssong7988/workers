"""Matching rules for collected real-estate listings."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Protocol

from .models import GlobalRule, SearchCondition


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


class MatchableListing(Protocol):
    complex_name: str
    type_name: str
    exclusive_area_m2: Decimal
    price_won: int
    floor_text: str
    floor: int | None
    is_low_floor: bool
    effective_max_price_won: int | None
    effective_urgent_price_won: int | None


def parse_price_won(text: str) -> int:
    value = text.replace(" ", "").replace("원", "")
    if not value:
        raise ValueError("가격이 비어 있습니다.")
    total = Decimal(0)
    if "억" in value:
        eok, value = value.split("억", 1)
        match = _NUMBER.search(eok)
        if not match:
            raise ValueError(f"가격을 해석할 수 없습니다: {text}")
        total += Decimal(match.group().replace(",", "")) * 100_000_000
    match = _NUMBER.search(value)
    if match:
        number = Decimal(match.group().replace(",", ""))
        total += number if number >= 1_000_000 else number * 10_000
    if total <= 0:
        raise ValueError(f"가격을 해석할 수 없습니다: {text}")
    return int(total)


def parse_floor(text: str, rule: GlobalRule) -> tuple[int | None, bool, bool]:
    """Return the listing floor, whether it is low, and whether it was known."""
    normalized = text.strip().replace(" ", "")
    head = normalized.partition("/")[0]
    for label in rule.low_floor_labels:
        if label and label in head:
            return None, True, True
    match = re.match(r"(\d{1,3})", head)
    if match:
        floor = int(match.group(1))
        return floor, floor in rule.low_floor_numeric_floors, True
    if any(label in head for label in ("중층", "고층", "중", "고")):
        return None, False, True
    return None, False, False


def normalize_type_name(text: str) -> str:
    compact = re.sub(r"\s+", "", text).upper()
    match = re.search(r"84(?:\.\d+)?([A-Z]?)", compact)
    return f"84{match.group(1)}" if match else compact


def _eok(price_won: int) -> str:
    return f"{price_won / 100_000_000:.2f}억"


# Maps each `explain_condition` branch to a stable code. The reasons above are
# Korean display strings that will be reworded; the codes are what the database
# and the statistics query rely on, so the two are kept side by side and pinned
# by a test that walks every branch.
EXCLUSION_CODES: tuple[tuple[str, str], ...] = (
    ("단지명 불일치", "complex"),
    ("면적 미달", "area"),
    ("면적 초과", "area"),
    ("타입 제외", "type"),
    ("층 해석 실패", "floor"),
    ("가격 초과", "price"),
)


def classify_exclusion(reason: str | None) -> str:
    """Return the stable code for an exclusion reason, or "" when it matched."""
    if not reason:
        return ""
    for prefix, code in EXCLUSION_CODES:
        if reason.startswith(prefix):
            return code
    return "other"


def explain_condition(
    listing: MatchableListing, condition: SearchCondition, rule: GlobalRule
) -> str | None:
    """Return an exclusion reason, filling calculated fields on the listing."""
    compact_name = listing.complex_name.replace(" ", "")
    if not any(alias.replace(" ", "") in compact_name for alias in condition.complex_names):
        return "단지명 불일치"

    area_min = condition.exclusive_area_min_m2
    area_max = condition.exclusive_area_max_m2
    if condition.exclusive_area_m2 is not None:
        area_min = area_min if area_min is not None else condition.exclusive_area_m2 - 1
        area_max = area_max if area_max is not None else condition.exclusive_area_m2 + 2
    if area_min is not None and listing.exclusive_area_m2 < area_min:
        return f"면적 미달 ({listing.exclusive_area_m2:g} < {area_min:g}㎡)"
    if area_max is not None and listing.exclusive_area_m2 > area_max:
        return f"면적 초과 ({listing.exclusive_area_m2:g} > {area_max:g}㎡)"

    normalized_type = normalize_type_name(listing.type_name)
    if condition.allowed_types is not None and normalized_type not in condition.allowed_types:
        return f"타입 제외 ({normalized_type})"

    floor, is_low, known = parse_floor(listing.floor_text, rule)
    if not known:
        return f"층 해석 실패 ('{listing.floor_text}')"
    listing.floor = floor
    listing.is_low_floor = is_low
    discount = (
        rule.low_floor_price_discount_won
        if is_low and condition.apply_low_floor_discount
        else 0
    )
    listing.effective_max_price_won = (
        condition.max_price_won - discount
        if condition.max_price_won is not None
        else None
    )
    listing.effective_urgent_price_won = (
        condition.urgent_price_won - discount
        if condition.urgent_price_won is not None
        else None
    )
    cap = listing.effective_max_price_won
    if cap is not None and listing.price_won > cap:
        suffix = " 저층기준" if is_low else ""
        return f"가격 초과 ({_eok(listing.price_won)} > {_eok(cap)}{suffix})"
    return None


def matches_condition(
    listing: MatchableListing, condition: SearchCondition, rule: GlobalRule
) -> bool:
    return explain_condition(listing, condition, rule) is None
