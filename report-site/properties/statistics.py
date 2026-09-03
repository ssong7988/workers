"""Daily asking-price distributions built from the raw observation history.

Two things make this less obvious than a `GROUP BY date`.

The scanner runs many times a day, so one listing contributes twenty rows to a
single day. Counting them all would let a frequently-scanned listing dominate
the quartiles, so each (condition, listing, local day) is collapsed to its last
observation of that day.

And the population is deliberately wider than the report's: listings excluded
only because they are above a condition's price cap are kept. They passed the
area and type filters, so they are the same floor plan, and dropping them would
clip the maximum and the third quartile at whatever ceiling the user happens to
be shopping under.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import Observation
from .report import price_text


# Observations that belong in the price distribution: matched, or excluded for
# price alone. See the module docstring.
POPULATION_CODES = ("", "price")

# Below this many listings a day's quartiles say more about the sample than the
# market, so the chart draws it faintly.
THIN_SAMPLE = 5


@dataclass(frozen=True)
class DaySummary:
    """One day's price distribution, in won."""

    day: date
    count: int
    minimum: int
    q1: int
    mean: int
    q3: int
    maximum: int

    @property
    def thin(self) -> bool:
        return self.count < THIN_SAMPLE


@dataclass(frozen=True)
class PeriodSummary:
    """Headline numbers for the whole selected range."""

    days: int
    samples: int
    minimum: int
    maximum: int
    latest: DaySummary | None


def _day_bounds(
    start_day: date, end_day: date, timezone_name: str
) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone_name)
    return (
        datetime.combine(start_day, time.min, tzinfo=zone),
        datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=zone),
    )


def _summarize(day: date, prices: list[int]) -> DaySummary:
    ordered = sorted(prices)
    if len(ordered) >= 2:
        q1, _median, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    else:
        # A single listing is its own quartiles; the chart draws a flat mark.
        q1 = q3 = float(ordered[0])
    return DaySummary(
        day=day,
        count=len(ordered),
        minimum=ordered[0],
        q1=round(q1),
        mean=round(statistics.fmean(ordered)),
        q3=round(q3),
        maximum=ordered[-1],
    )


def collect_series(
    *,
    start_day: date,
    end_day: date,
    region: str = "",
    condition_id: str = "",
    timezone_name: str = "Asia/Seoul",
) -> list[DaySummary]:
    """Return one summary per day that actually has observations, oldest first.

    Days with no scan are omitted rather than drawn as gaps, so a weekend or an
    outage does not read as a price of zero.
    """
    started, ended = _day_bounds(start_day, end_day, timezone_name)
    query = Observation.objects.filter(
        observed_at__gte=started,
        observed_at__lt=ended,
        exclusion_code__in=POPULATION_CODES,
        condition__enabled=True,
    )
    if condition_id:
        query = query.filter(condition_id=condition_id)
    elif region:
        query = query.filter(condition__region=region)

    zone = ZoneInfo(timezone_name)
    latest: dict[tuple[str, str, date], int] = {}
    rows = query.order_by("observed_at", "pk").values_list(
        "condition_id", "listing_id", "observed_at", "price_won"
    )
    for condition, listing_id, observed_at, price_won in rows.iterator():
        key = (condition, listing_id, observed_at.astimezone(zone).date())
        latest[key] = price_won

    by_day: dict[date, list[int]] = {}
    for (_condition, _listing_id, day), price_won in latest.items():
        by_day.setdefault(day, []).append(price_won)

    return [_summarize(day, by_day[day]) for day in sorted(by_day)]


def summarize_period(series: list[DaySummary]) -> PeriodSummary:
    if not series:
        return PeriodSummary(days=0, samples=0, minimum=0, maximum=0, latest=None)
    return PeriodSummary(
        days=len(series),
        samples=sum(day.count for day in series),
        minimum=min(day.minimum for day in series),
        maximum=max(day.maximum for day in series),
        latest=series[-1],
    )


# --- Chart geometry -------------------------------------------------------
#
# Coordinates are computed here rather than in the template so the SVG stays a
# dumb list of shapes and the arithmetic can be unit tested.

WIDTH = 760
HEIGHT = 320
PAD_LEFT = 70
PAD_RIGHT = 14
PAD_TOP = 14
PAD_BOTTOM = 42
MAX_X_LABELS = 8
EOK = 100_000_000
TICK_STEPS = (EOK // 4, EOK // 2, EOK, 2 * EOK, 5 * EOK, 10 * EOK, 20 * EOK)


@dataclass(frozen=True)
class Bar:
    x: float
    box_x: float
    box_width: float
    box_y: float
    box_height: float
    wick_top: float
    wick_bottom: float
    mean_y: float
    thin: bool
    label: str
    show_label: bool
    title: str


@dataclass(frozen=True)
class Tick:
    y: float
    label: str


@dataclass(frozen=True)
class Chart:
    width: int
    height: int
    plot_left: float
    plot_right: float
    plot_top: float
    plot_bottom: float
    bars: list[Bar]
    ticks: list[Tick]


def eok_text(price_won: int) -> str:
    """Compact axis and headline form: 23.5억, 24억."""
    return f"{price_won / EOK:.1f}".rstrip("0").rstrip(".") + "억"


def _tick_bounds(low: int, high: int) -> tuple[int, int, int]:
    if high == low:
        low, high = low - EOK // 2, high + EOK // 2
    span = high - low
    step = next(
        (candidate for candidate in TICK_STEPS if span / candidate <= 6), TICK_STEPS[-1]
    )
    return (low // step) * step, -(-high // step) * step, step


def _tooltip(day: DaySummary) -> str:
    return (
        f"{day.day:%Y.%m.%d} · {day.count}건\n"
        f"최고 {eok_text(day.maximum)} / 3분위 {eok_text(day.q3)} / "
        f"평균 {eok_text(day.mean)} / 1분위 {eok_text(day.q1)} / "
        f"최저 {eok_text(day.minimum)}"
    )


def build_chart(series: list[DaySummary]) -> Chart | None:
    """Lay the summaries out as min/max wicks with Q1-Q3 boxes and a mean line."""
    if not series:
        return None

    plot_left, plot_right = float(PAD_LEFT), float(WIDTH - PAD_RIGHT)
    plot_top, plot_bottom = float(PAD_TOP), float(HEIGHT - PAD_BOTTOM)
    axis_low, axis_high, step = _tick_bounds(
        min(day.minimum for day in series), max(day.maximum for day in series)
    )

    def y_of(price_won: int) -> float:
        ratio = (price_won - axis_low) / (axis_high - axis_low)
        return round(plot_bottom - ratio * (plot_bottom - plot_top), 1)

    slot = (plot_right - plot_left) / len(series)
    box_width = round(min(max(slot * 0.55, 3.0), 20.0), 1)
    stride = -(-len(series) // MAX_X_LABELS)

    bars = []
    for index, day in enumerate(series):
        center = round(plot_left + slot * (index + 0.5), 1)
        box_top, box_bottom = y_of(day.q3), y_of(day.q1)
        bars.append(
            Bar(
                x=center,
                box_x=round(center - box_width / 2, 1),
                box_width=box_width,
                box_y=box_top,
                # A day where Q1 == Q3 would otherwise render as nothing.
                box_height=round(max(box_bottom - box_top, 1.5), 1),
                wick_top=y_of(day.maximum),
                wick_bottom=y_of(day.minimum),
                mean_y=y_of(day.mean),
                thin=day.thin,
                label=f"{day.day.month}/{day.day.day}",
                show_label=index % stride == 0 or index == len(series) - 1,
                title=_tooltip(day),
            )
        )

    ticks = [
        Tick(y=y_of(value), label=eok_text(value))
        for value in range(axis_low, axis_high + 1, step)
    ]
    return Chart(
        width=WIDTH,
        height=HEIGHT,
        plot_left=plot_left,
        plot_right=plot_right,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
        bars=bars,
        ticks=ticks,
    )


def table_rows(series: list[DaySummary]) -> list[dict]:
    """The same numbers as the chart, formatted the way the report formats prices."""
    return [
        {
            "day": day.day,
            "count": day.count,
            "minimum": price_text(day.minimum),
            "q1": price_text(day.q1),
            "mean": price_text(day.mean),
            "q3": price_text(day.q3),
            "maximum": price_text(day.maximum),
            "thin": day.thin,
        }
        for day in reversed(series)
    ]
