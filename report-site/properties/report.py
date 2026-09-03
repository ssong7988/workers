"""Build the shared display payload for reports and Kakao cards."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from decimal import Decimal

from .models import Listing, SearchCondition


def price_text(price_won: int) -> str:
    eok, remainder = divmod(price_won, 100_000_000)
    if not remainder:
        return f"{eok}억"
    return f"{eok}억 {remainder // 10_000:,}"


def _area_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def rule_text(condition: SearchCondition) -> str:
    area_min = condition.exclusive_area_min_m2
    area_max = condition.exclusive_area_max_m2
    if area_min is not None and area_max is not None:
        area = f"전용 {_area_text(area_min)}~{_area_text(area_max)}㎡"
    elif area_min is not None:
        area = f"전용 {_area_text(area_min)}㎡ 이상"
    elif area_max is not None:
        area = f"전용 {_area_text(area_max)}㎡ 이하"
    elif condition.exclusive_area_m2 is not None:
        area = (
            f"전용 {_area_text(condition.exclusive_area_m2 - 1)}"
            f"~{_area_text(condition.exclusive_area_m2 + 2)}㎡"
        )
    else:
        area = "전체 면적"
    price = (
        f"{price_text(condition.max_price_won)} 이하"
        if condition.max_price_won is not None
        else "가격 제한 없음"
    )
    return f"{price} · {area}"


def build_report_payload(
    listings: Iterable[Listing],
    conditions: Sequence[SearchCondition],
    *,
    observed_at: str,
) -> dict:
    """Group active listings in condition order, preserving the existing UI shape."""
    grouped: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        if listing.listing_id.isdigit() and "/articles/" in listing.url:
            grouped[listing.condition_id].append(listing)

    complexes = []
    for condition in conditions:
        items = sorted(
            grouped.get(condition.pk, []),
            key=lambda item: (item.price_won, -int(item.listing_id)),
        )
        if not items:
            continue
        complexes.append(
            {
                "name": items[0].complex_name,
                "rule": rule_text(condition),
                "listings": [
                    {
                        "price": price_text(item.price_won),
                        "area": _area_text(item.exclusive_area_m2),
                        "floor": item.floor_text,
                        "direction": item.direction,
                        "urgent": item.is_urgent,
                        "url": item.url,
                    }
                    for item in items
                ],
            }
        )

    return {"observedAt": observed_at, "complexes": complexes}
