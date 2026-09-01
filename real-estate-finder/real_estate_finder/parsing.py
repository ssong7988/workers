"""Normalize Korean real-estate prices, floors, and listing types."""

from __future__ import annotations

import re
from decimal import Decimal

from .models import Listing, LowFloorRule, SearchCondition


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


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


def parse_floor(text: str, rule: LowFloorRule) -> tuple[int | None, bool, bool]:
    normalized = text.strip().replace(" ", "")
    for label in rule.labels:
        if label and label in normalized:
            return None, True, True
    match = re.search(r"(?<!\d)(\d{1,3})(?:층|/)", normalized)
    if match:
        floor = int(match.group(1))
        return floor, floor in rule.numeric_floors, True
    if any(label in normalized for label in ("중층", "고층", "중", "고")):
        return None, False, True
    return None, False, False


def normalize_type_name(text: str) -> str:
    compact = re.sub(r"\s+", "", text).upper()
    match = re.search(r"84(?:\.\d+)?([A-Z]?)", compact)
    return f"84{match.group(1)}" if match else compact


def matches_condition(listing: Listing, condition: SearchCondition, rule: LowFloorRule) -> bool:
    if not any(alias.replace(" ", "") in listing.complex_name.replace(" ", "") for alias in condition.complex_names):
        return False
    if not condition.exclusive_area_m2 <= listing.exclusive_area_m2 < condition.exclusive_area_m2 + 1:
        return False
    normalized_type = normalize_type_name(listing.type_name)
    if condition.allowed_types is not None and normalized_type not in condition.allowed_types:
        return False
    floor, is_low, known = parse_floor(listing.floor_text, rule)
    if not known:
        return False
    listing.floor = floor
    listing.is_low_floor = is_low
    discount = rule.price_discount_won if is_low else 0
    listing.effective_max_price_won = condition.max_price_won - discount
    listing.effective_urgent_price_won = condition.urgent_price_won - discount
    return listing.price_won <= listing.effective_max_price_won
