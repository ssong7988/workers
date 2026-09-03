"""Read the statistics screen's query string into a date range and a scope.

Every value here arrives from a URL a person can type, so nothing raises: a
malformed date falls back to the default range and says so on the page. That
keeps a shared or bookmarked link from turning into a 500.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from properties.models import SearchCondition
from properties.statistics import DEFAULT_REGION, month_before


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date
    month: str  # "YYYY-MM" when a whole month was chosen, else ""
    notice: str


@dataclass(frozen=True)
class Scope:
    region: str  # "" means every region
    condition_id: str
    label: str


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def resolve_range(params, today: date) -> DateRange:
    month = params.get("month", "").strip()
    if month:
        try:
            year, month_number = (int(part) for part in month.split("-", 1))
            last = monthrange(year, month_number)[1]
        except (ValueError, TypeError):
            return DateRange(
                start=month_before(today),
                end=today,
                month="",
                notice="월 형식을 읽지 못해 최근 1개월로 되돌렸습니다.",
            )
        return DateRange(
            start=date(year, month_number, 1),
            end=date(year, month_number, last),
            month=f"{year:04d}-{month_number:02d}",
            notice="",
        )

    raw_start, raw_end = params.get("from", ""), params.get("to", "")
    if raw_start or raw_end:
        start, end = _parse_date(raw_start), _parse_date(raw_end)
        if start is None or end is None:
            return DateRange(
                start=month_before(today),
                end=today,
                month="",
                notice="날짜 형식을 읽지 못해 최근 1개월로 되돌렸습니다.",
            )
        if start > end:
            start, end = end, start
            return DateRange(
                start=start,
                end=end,
                month="",
                notice="시작일이 종료일보다 늦어 두 날짜를 바꿨습니다.",
            )
        return DateRange(start=start, end=end, month="", notice="")

    return DateRange(start=month_before(today), end=today, month="", notice="")


def resolve_scope(params, conditions: list[SearchCondition]) -> Scope:
    """Pick the complex or region to chart, defaulting to Gwacheon.

    A chosen complex also decides the region shown in the first select, so the
    two controls can never contradict each other.
    """
    by_id = {condition.pk: condition for condition in conditions}
    condition_id = params.get("condition", "").strip()
    if condition_id in by_id:
        condition = by_id[condition_id]
        return Scope(
            region=condition.region, condition_id=condition.pk, label=condition.name
        )

    regions = [region for region in dict.fromkeys(c.region for c in conditions) if region]
    requested = params.get("region", "").strip()
    if requested == "all":
        return Scope(region="", condition_id="", label="전체 지역")
    if requested in regions:
        return Scope(region=requested, condition_id="", label=f"{requested} 전체")
    if not requested and DEFAULT_REGION in regions:
        return Scope(
            region=DEFAULT_REGION, condition_id="", label=f"{DEFAULT_REGION} 전체"
        )
    return Scope(region="", condition_id="", label="전체 지역")
