"""Build the property report payload shared by the digest card and the report site."""

from __future__ import annotations

from collections import defaultdict

from .models import AppConfig, Listing, SearchCondition


def _price_text(price_won: int) -> str:
    eok, remainder = divmod(price_won, 100_000_000)
    if not remainder:
        return f"{eok}억"
    return f"{eok}억 {remainder // 10_000:,}"


def _rule_text(condition: SearchCondition) -> str:
    if condition.exclusive_area_min_m2 is not None:
        area = f"전용 {condition.exclusive_area_min_m2:g}~{condition.exclusive_area_max_m2:g}㎡"
    elif condition.exclusive_area_m2 is not None:
        area = f"전용 {condition.exclusive_area_m2 - 1:g}~{condition.exclusive_area_m2 + 2:g}㎡"
    else:
        area = "전체 면적"
    price = (
        f"{_price_text(condition.max_price_won)} 이하"
        if condition.max_price_won is not None
        else "가격 제한 없음"
    )
    return f"{price} · {area}"


def build_report_payload(
    listings: list[Listing], config: AppConfig, *, observed_at: str
) -> dict:
    """Group matched listings by search condition, in the report's on-screen shape.

    Only direct article URLs are included; a complex/home fallback is never
    emitted. Shared by the Kakao digest card and the report site so their
    price/area text and grouping cannot drift apart.
    """
    grouped: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        if listing.listing_id.isdigit() and "/articles/" in listing.url:
            grouped[listing.condition_id].append(listing)

    complexes = []
    for condition in config.searches:
        items = sorted(
            grouped.get(condition.id, []),
            key=lambda item: (item.price_won, -int(item.listing_id)),
        )
        if not items:
            continue
        complexes.append(
            {
                "name": items[0].complex_name,
                "rule": _rule_text(condition),
                "listings": [
                    {
                        "price": _price_text(item.price_won),
                        "area": f"{item.exclusive_area_m2:g}",
                        "floor": item.floor_text,
                        "direction": item.direction,
                        "urgent": item.effective_urgent_price_won is not None
                        and item.price_won <= item.effective_urgent_price_won,
                        "url": item.url,
                    }
                    for item in items
                ],
            }
        )

    return {"observedAt": observed_at, "complexes": complexes}
