"""Inline SVG chart primitives for the dashboard.

Charts are generated server-side as SVG markup — no charting library, no CDN,
no build step — so the report stays a single file that opens from disk.

Colors are never written here as hex. Every mark references a CSS custom
property defined once in `report.py`, which is what lets light and dark mode
swap in one place.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

CORNER = 4  # rounded data-end, per the mark spec
BAR_GAP = 2  # surface gap between adjacent fills


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def format_won(value: int) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,}원"


def format_man(value: int) -> str:
    """Compact label in 만원, the unit Korean readers scan amounts in."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    man = abs(value) / 10_000
    # 억 only past a full 억 (10,000만). Switching at 1,000만 renders a
    # 1,500만원 month as "0.1억", which reads as an order of magnitude too small.
    if man >= 10_000:
        return f"{sign}{man / 10_000:,.2f}억"
    if man >= 100:
        return f"{sign}{man:,.0f}만"
    return f"{sign}{man:,.1f}만"


def format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.1f}%"


def _top_rounded(x: float, y: float, width: float, height: float) -> str:
    """A bar anchored to the baseline with only its data-end rounded."""
    radius = min(CORNER, width / 2, max(height, 0))
    if height <= 0:
        return ""
    return (
        f"M{x:.1f},{y + height:.1f} V{y + radius:.1f} "
        f"Q{x:.1f},{y:.1f} {x + radius:.1f},{y:.1f} "
        f"H{x + width - radius:.1f} Q{x + width:.1f},{y:.1f} {x + width:.1f},{y + radius:.1f} "
        f"V{y + height:.1f} Z"
    )


def _right_rounded(x: float, y: float, width: float, height: float) -> str:
    radius = min(CORNER, height / 2, max(width, 0))
    if width <= 0:
        return ""
    return (
        f"M{x:.1f},{y:.1f} H{x + width - radius:.1f} "
        f"Q{x + width:.1f},{y:.1f} {x + width:.1f},{y + radius:.1f} "
        f"V{y + height - radius:.1f} "
        f"Q{x + width:.1f},{y + height:.1f} {x + width - radius:.1f},{y + height:.1f} "
        f"H{x:.1f} Z"
    )


def _left_rounded(x: float, y: float, width: float, height: float) -> str:
    radius = min(CORNER, height / 2, max(width, 0))
    if width <= 0:
        return ""
    return (
        f"M{x + width:.1f},{y:.1f} H{x + radius:.1f} "
        f"Q{x:.1f},{y:.1f} {x:.1f},{y + radius:.1f} "
        f"V{y + height - radius:.1f} "
        f"Q{x:.1f},{y + height:.1f} {x + radius:.1f},{y + height:.1f} "
        f"H{x + width:.1f} Z"
    )


def _svg(width: int, height: int, body: str, label: str) -> str:
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(label)}" preserveAspectRatio="xMidYMid meet">{body}</svg>'
    )


def empty_note(message: str) -> str:
    return f'<p class="empty">{esc(message)}</p>'


@dataclass
class Column:
    label: str
    value: int
    tooltip: str = ""
    emphasis: bool = False


def column_chart(
    columns: list[Column], *, average: int | None = None, title: str = "", height: int = 220
) -> str:
    """Magnitude over time, one series — a single sequential hue, no legend.

    The trailing-average rule is what makes a month readable as high or low; the
    bars alone only say "different".
    """
    if not columns:
        return empty_note("표시할 달이 없습니다.")

    width = 760
    # The average label lives in its own right gutter. Drawn inside the plot it
    # collides with the last bar's value whenever the newest month is near the
    # average, which is most months.
    gutter = 86 if average else 0
    pad_left, pad_right, pad_top, pad_bottom = 12, 12 + gutter, 26, 30
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom

    values = [item.value for item in columns] + ([average] if average else [])
    ceiling = max(values + [1])
    floor = min(values + [0])
    span = ceiling - floor or 1

    def y_of(value: float) -> float:
        return pad_top + plot_height * (ceiling - value) / span

    slot = plot_width / len(columns)
    bar_width = max(6.0, min(48.0, slot - BAR_GAP * 2 - 6))
    zero = y_of(0)

    parts = []
    if average:
        line_y = y_of(average)
        parts.append(
            f'<line class="rule" x1="{pad_left}" y1="{line_y:.1f}" '
            f'x2="{width - pad_right}" y2="{line_y:.1f}"/>'
        )
        parts.append(
            f'<text class="rule-label" x="{width - pad_right + 8:.1f}" y="{line_y + 4:.1f}" '
            f'text-anchor="start">평균 {esc(format_man(average))}</text>'
        )

    for index, column in enumerate(columns):
        center = pad_left + slot * (index + 0.5)
        x = center - bar_width / 2
        top = y_of(max(column.value, 0))
        bar_height = abs(y_of(column.value) - zero)
        fill = "var(--series-1)" if column.emphasis else "var(--seq-mid)"
        path = _top_rounded(x, top, bar_width, bar_height)
        tooltip = column.tooltip or f"{column.label} {format_won(column.value)}"
        parts.append(
            f'<g class="mark"><title>{esc(tooltip)}</title>'
            f'<path d="{path}" fill="{fill}"/></g>'
        )
        parts.append(
            f'<text class="bar-value" x="{center:.1f}" y="{top - 6:.1f}" text-anchor="middle">'
            f"{esc(format_man(column.value))}</text>"
        )
        parts.append(
            f'<text class="axis" x="{center:.1f}" y="{height - 10}" text-anchor="middle">'
            f"{esc(column.label)}</text>"
        )

    return _svg(width, height, "".join(parts), title or "월별 추이")


@dataclass
class Bar:
    label: str
    value: int
    note: str = ""
    tooltip: str = ""


def horizontal_bars(bars: list[Bar], *, title: str = "", row_height: int = 30) -> str:
    """Ranked magnitude — one sequential hue, longest first.

    Horizontal because Korean category and merchant names are long; rotated
    labels under a column chart would be unreadable.
    """
    if not bars:
        return empty_note("표시할 항목이 없습니다.")

    width = 760
    label_width = 150
    value_width = 110
    track_width = width - label_width - value_width - 16
    height = row_height * len(bars) + 8
    ceiling = max([abs(item.value) for item in bars] + [1])

    parts = []
    for index, bar in enumerate(bars):
        y = index * row_height + 4
        bar_height = row_height - BAR_GAP * 2 - 6
        length = track_width * abs(bar.value) / ceiling
        tooltip = bar.tooltip or f"{bar.label} {format_won(bar.value)}"
        parts.append(
            f'<text class="row-label" x="{label_width - 10}" y="{y + bar_height / 2 + 4:.1f}" '
            f'text-anchor="end">{esc(bar.label)}</text>'
        )
        parts.append(
            f'<g class="mark"><title>{esc(tooltip)}</title>'
            f'<path d="{_right_rounded(label_width, y, length, bar_height)}" '
            f'fill="var(--seq-mid)"/></g>'
        )
        text = format_won(bar.value) + (f"  {bar.note}" if bar.note else "")
        parts.append(
            f'<text class="row-value" x="{width - 4}" y="{y + bar_height / 2 + 4:.1f}" '
            f'text-anchor="end">{esc(text)}</text>'
        )

    return _svg(width, height, "".join(parts), title or "항목별 금액")


def diverging_bars(bars: list[Bar], *, title: str = "", row_height: int = 30) -> str:
    """Change against zero — two poles and a neutral midpoint.

    Increases and decreases must read as opposite at a glance, which a single
    hue cannot do.
    """
    if not bars:
        return empty_note("비교할 전월 데이터가 없습니다.")

    width = 760
    label_width = 150
    value_width = 110
    track_width = width - label_width - value_width - 16
    center = label_width + track_width / 2
    height = row_height * len(bars) + 8
    ceiling = max([abs(item.value) for item in bars] + [1])

    parts = [
        f'<line class="zero" x1="{center:.1f}" y1="0" x2="{center:.1f}" y2="{height - 4}"/>'
    ]
    for index, bar in enumerate(bars):
        y = index * row_height + 4
        bar_height = row_height - BAR_GAP * 2 - 6
        length = (track_width / 2) * abs(bar.value) / ceiling
        increased = bar.value > 0
        fill = "var(--diverge-up)" if increased else "var(--diverge-down)"
        path = (
            _right_rounded(center, y, length, bar_height)
            if increased
            else _left_rounded(center - length, y, length, bar_height)
        )
        tooltip = bar.tooltip or f"{bar.label} {format_won(bar.value)}"
        parts.append(
            f'<text class="row-label" x="{label_width - 10}" y="{y + bar_height / 2 + 4:.1f}" '
            f'text-anchor="end">{esc(bar.label)}</text>'
        )
        if path:
            parts.append(
                f'<g class="mark"><title>{esc(tooltip)}</title>'
                f'<path d="{path}" fill="{fill}"/></g>'
            )
        text = ("+" if increased else "") + format_won(bar.value)
        parts.append(
            f'<text class="row-value" x="{width - 4}" y="{y + bar_height / 2 + 4:.1f}" '
            f'text-anchor="end">{esc(text)}</text>'
        )

    return _svg(width, height, "".join(parts), title or "전월 대비 증감")


@dataclass
class Segment:
    label: str
    value: int
    slot: int  # 1-based categorical slot


def stacked_bar(segments: list[Segment], *, title: str = "") -> str:
    """Part-to-whole in one bar, with a legend and per-segment values.

    Three of the light-mode categorical slots sit below 3:1 against the surface,
    so the values are always drawn as text — identity never rests on color alone.
    """
    segments = [item for item in segments if item.value > 0]
    if not segments:
        return empty_note("표시할 구성이 없습니다.")

    width = 760
    height = 44
    whole = sum(item.value for item in segments)
    parts = []
    x = 0.0
    for index, segment in enumerate(segments):
        length = max(0.0, (width * segment.value / whole) - (BAR_GAP if index else 0))
        offset = x + (BAR_GAP if index else 0)
        first, last = index == 0, index == len(segments) - 1
        if first and last:
            path = _right_rounded(offset, 0, length, height)
        elif first:
            path = _left_rounded(offset, 0, length, height)
        elif last:
            path = _right_rounded(offset, 0, length, height)
        else:
            path = f"M{offset:.1f},0 h{length:.1f} v{height} h{-length:.1f} Z"
        share = segment.value / whole
        parts.append(
            f'<g class="mark"><title>'
            f"{esc(f'{segment.label} {format_won(segment.value)} ({share * 100:.1f}%)')}"
            f'</title><path d="{path}" fill="var(--series-{segment.slot})"/></g>'
        )
        if length > 56:
            parts.append(
                f'<text class="segment-label" x="{offset + length / 2:.1f}" y="{height / 2 + 4:.0f}" '
                f'text-anchor="middle">{share * 100:.0f}%</text>'
            )
        x = offset + length

    legend = "".join(
        f'<span class="legend-item"><span class="swatch" '
        f'style="background:var(--series-{segment.slot})"></span>'
        f"{esc(segment.label)} <b>{esc(format_won(segment.value))}</b></span>"
        for segment in segments
    )
    chart = _svg(width, height, "".join(parts), title or "구성 비율")
    return f'{chart}<div class="legend">{legend}</div>'


def meter(used: int, limit: int, *, label: str) -> str:
    """A single ratio against a limit, on the same ramp as the track."""
    ratio = min(used / limit, 1.0) if limit else 0.0
    over = limit and used > limit
    fill = "var(--status-critical)" if over else "var(--seq-mid)"
    percent = (used / limit * 100) if limit else 0
    return (
        f'<div class="meter" title="{esc(f"{label} {format_won(used)} / {format_won(limit)}")}">'
        f'<div class="meter-head"><span>{esc(label)}</span>'
        f'<span class="meter-value">{esc(format_won(used))} / {esc(format_won(limit))}'
        f" ({percent:.0f}%)</span></div>"
        f'<div class="meter-track"><div class="meter-fill" '
        f'style="width:{ratio * 100:.1f}%;background:{fill}"></div></div></div>'
    )
