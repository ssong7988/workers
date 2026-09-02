"""Domain models shared by collection, filtering, storage, and notification."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class LowFloorRule:
    numeric_floors: tuple[int, ...] = (1, 2, 3)
    labels: tuple[str, ...] = ("저", "저층")
    price_discount_won: int = 100_000_000


@dataclass(frozen=True)
class SearchCondition:
    id: str
    name: str
    complex_names: tuple[str, ...]
    search_url: str
    exclusive_area_m2: float | None
    allowed_types: tuple[str, ...] | None
    max_price_won: int | None
    urgent_price_won: int | None
    exclusive_area_min_m2: float | None = None
    exclusive_area_max_m2: float | None = None
    notify_new: bool = False
    apply_low_floor_discount: bool = True
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    trade_type: str
    low_floor: LowFloorRule
    searches: tuple[SearchCondition, ...]
    timezone: str = "Asia/Seoul"
    digest_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    digest_hour: int = 8


@dataclass
class Listing:
    condition_id: str
    listing_id: str
    complex_name: str
    type_name: str
    exclusive_area_m2: float
    price_won: int
    floor_text: str
    floor: int | None
    direction: str
    description: str
    url: str
    observed_at: str
    is_low_floor: bool = False
    effective_max_price_won: int | None = None
    effective_urgent_price_won: int | None = None

    @property
    def key(self) -> str:
        return f"{self.condition_id}:{self.listing_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Listing":
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})


@dataclass
class ScanResult:
    started_at: str
    finished_at: str
    successful_conditions: list[str] = field(default_factory=list)
    failed_conditions: dict[str, str] = field(default_factory=dict)
    collected_count: int = 0
    matched: list[Listing] = field(default_factory=list)
    urgent: list[Listing] = field(default_factory=list)
    excluded_count: int = 0

    @property
    def success(self) -> bool:
        return not self.failed_conditions and bool(self.successful_conditions)


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
