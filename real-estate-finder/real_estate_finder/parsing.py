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
    """Read a listing's own floor from Naver's `<floor>/<building height>층` text.

    Only the part before the slash describes the listing; the number after it is
    how tall the building is. Matching anywhere in the string would read
    "중/23층" as floor 23 instead of an unnumbered middle floor.
    """
    normalized = text.strip().replace(" ", "")
    head = normalized.partition("/")[0]
    for label in rule.labels:
        if label and label in head:
            return None, True, True
    match = re.match(r"(\d{1,3})", head)
    if match:
        floor = int(match.group(1))
        return floor, floor in rule.numeric_floors, True
    if any(label in head for label in ("중층", "고층", "중", "고")):
        return None, False, True
    return None, False, False


def normalize_type_name(text: str) -> str:
    compact = re.sub(r"\s+", "", text).upper()
    match = re.search(r"84(?:\.\d+)?([A-Z]?)", compact)
    return f"84{match.group(1)}" if match else compact


def _eok(price_won: int) -> str:
    return f"{price_won / 100_000_000:.2f}억"


def explain_condition(
    listing: Listing, condition: SearchCondition, rule: LowFloorRule
) -> str | None:
    """Why a listing does not match, or None when it does.

    Also fills in the listing's floor, low-floor flag and effective thresholds,
    which the caller relies on afterwards.
    """
    if not any(alias.replace(" ", "") in listing.complex_name.replace(" ", "") for alias in condition.complex_names):
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
    discount = rule.price_discount_won if is_low and condition.apply_low_floor_discount else 0
    listing.effective_max_price_won = (
        condition.max_price_won - discount if condition.max_price_won is not None else None
    )
    listing.effective_urgent_price_won = (
        condition.urgent_price_won - discount if condition.urgent_price_won is not None else None
    )
    cap = listing.effective_max_price_won
    if cap is not None and listing.price_won > cap:
        return f"가격 초과 ({_eok(listing.price_won)} > {_eok(cap)}{' 저층기준' if is_low else ''})"
    return None


def matches_condition(listing: Listing, condition: SearchCondition, rule: LowFloorRule) -> bool:
    return explain_condition(listing, condition, rule) is None
