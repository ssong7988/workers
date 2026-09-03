"""What the collector reads and what it reports.

Both shapes are deliberately thin. Search conditions arrive from report-site's
API and are used only to decide which scraped complex belongs to which
condition; a listing is the raw row as it appeared on screen. Nothing here
decides whether a listing matches, is a bargain, or is worth a message - that
judgement lives in `report-site/properties/`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SearchCondition:
    """One search condition, as served by `GET /api/conditions/`."""

    id: str
    name: str
    complex_names: tuple[str, ...]
    search_url: str = ""
    exclusive_area_m2: float | None = None
    exclusive_area_min_m2: float | None = None
    exclusive_area_max_m2: float | None = None
    allowed_types: tuple[str, ...] | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "SearchCondition":
        names = payload.get("complex_names") or []
        types = payload.get("allowed_types")
        return cls(
            id=str(payload["id"]),
            name=str(payload.get("name", "")),
            complex_names=tuple(str(name) for name in names),
            search_url=str(payload.get("search_url") or ""),
            exclusive_area_m2=payload.get("exclusive_area_m2"),
            exclusive_area_min_m2=payload.get("exclusive_area_min_m2"),
            exclusive_area_max_m2=payload.get("exclusive_area_max_m2"),
            allowed_types=tuple(str(item) for item in types) if types else None,
        )


@dataclass
class Listing:
    """One listing exactly as scraped, before anyone judges it."""

    condition_id: str
    listing_id: str
    complex_name: str
    type_name: str
    exclusive_area_m2: float
    price_won: int
    floor_text: str
    direction: str
    description: str
    url: str
    observed_at: str

    @property
    def key(self) -> str:
        return f"{self.condition_id}:{self.listing_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
