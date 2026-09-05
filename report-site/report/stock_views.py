"""금융자산 두 화면을 PostgreSQL에서 바로 렌더링한다.

부동산 화면과 같은 구조다 - 빌드도 배포도 없고, 요청마다 DB를 읽어 그린다.
차트 좌표는 서버에서 만들어 내려보낸다(브라우저에서 차트 라이브러리를 받지
않는다). 표기는 전부 `portfolio/display.py` 하나를 통과한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from portfolio.allocation import build_allocation
from portfolio.display import (
    man_won_text,
    percent_point_text,
    percent_text,
    round_to_man,
    signed_man_won_text,
    signed_percent_text,
)
from portfolio.models import DailyPortfolioMetric
from portfolio.performance import class_performance


ZERO = Decimal("0")

# 화면에서 고를 수 있는 기간. `None`은 전체 기간이다.
RANGES: tuple[tuple[str, str, int | None], ...] = (
    ("1m", "1개월", 30),
    ("3m", "3개월", 91),
    ("6m", "6개월", 182),
    ("1y", "1년", 365),
    ("all", "전체", None),
)
DEFAULT_RANGE = "1y"

CHART_WIDTH = 720
CHART_HEIGHT = 240
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 56, 16, 16, 28


@dataclass(frozen=True)
class Point:
    x: float
    y: float


def _links(page: str) -> dict[str, str]:
    """두 화면 사이의 탭. `page`는 지금 보고 있는 쪽을 표시한다."""
    return {
        "page": page,
        "allocation_url": f"{settings.ALLOCATION_URL_PATH}/",
        "performance_url": f"{settings.PERFORMANCE_URL_PATH}/",
    }


def allocation(request: HttpRequest) -> HttpResponse:
    view = build_allocation()
    rows = [
        {
            "name": row.name,
            "color": row.color,
            "value_text": man_won_text(row.market_value),
            "ratio_text": percent_text(row.ratio),
            "target_text": (
                f"{row.target_percent:.1f}%" if row.target_percent is not None else "-"
            ),
            "gap_text": percent_point_text(row.gap_points),
            "rebalance_text": (
                signed_man_won_text(row.rebalance_value)
                if row.rebalance_value is not None
                else "-"
            ),
            # 매수/매도를 색으로 구분한다. 0에 가까우면 중립으로 둔다.
            "action": (
                ""
                if row.rebalance_value is None or round_to_man(row.rebalance_value) == ZERO
                else ("buy" if row.rebalance_value > ZERO else "sell")
            ),
        }
        for row in view.rows
    ]
    benchmark = [
        {
            "label": row.label,
            "mine_text": f"{row.mine_percent:.1f}%",
            "benchmark_text": f"{row.benchmark_percent:.1f}%",
            "gap_text": percent_point_text(row.gap_points),
            # 막대 두 개의 상대 길이. 가장 큰 값을 100%로 잡는다.
            "mine_width": float(row.mine_percent),
            "benchmark_width": float(row.benchmark_percent),
        }
        for row in view.benchmark_rows
    ]
    return render(
        request,
        "report/stock_allocation.html",
        {
            **_links("allocation"),
            "view": view,
            "rows": rows,
            "slices": view.slices,
            "benchmark": benchmark,
            "total_text": man_won_text(view.total_value),
            "gross_text": man_won_text(view.gross_value),
            "unclassified_text": man_won_text(view.unclassified_value),
            "remainder_text": signed_man_won_text(view.rounding_remainder),
            "has_remainder": round_to_man(view.rounding_remainder) != ZERO,
            "has_targets": any(row.target_percent is not None for row in view.rows),
        },
    )


def _resolve_range(raw: str | None) -> tuple[str, str, int | None]:
    for key, label, days in RANGES:
        if key == raw:
            return key, label, days
    return next((r for r in RANGES if r[0] == DEFAULT_RANGE), RANGES[-1])


def _line_chart(rows: list[DailyPortfolioMetric]) -> dict | None:
    """성과지수 선과 그 아래 면적. 0% 기준선을 항상 축에 포함한다."""
    if len(rows) < 2:
        return None
    values = [(row.cumulative_return - rows[0].cumulative_return) for row in rows]
    # 기간 안에서의 상대 수익률로 다시 잡는다. 1개월을 골랐으면 그 1개월의
    # 시작을 0%로 보는 것이 읽기 쉽다.
    low, high = min(values + [ZERO]), max(values + [ZERO])
    if high == low:
        low, high = low - Decimal("0.01"), high + Decimal("0.01")
    plot_left, plot_right = float(PAD_LEFT), float(CHART_WIDTH - PAD_RIGHT)
    plot_top, plot_bottom = float(PAD_TOP), float(CHART_HEIGHT - PAD_BOTTOM)

    def y_of(value: Decimal) -> float:
        ratio = float((value - low) / (high - low))
        return round(plot_bottom - ratio * (plot_bottom - plot_top), 1)

    step = (plot_right - plot_left) / (len(rows) - 1)
    points = [
        Point(x=round(plot_left + step * index, 1), y=y_of(value))
        for index, value in enumerate(values)
    ]
    line = " ".join(f"{point.x},{point.y}" for point in points)
    area = (
        f"{points[0].x},{plot_bottom} "
        + line
        + f" {points[-1].x},{plot_bottom}"
    )
    ticks = []
    for fraction in (Decimal("0"), Decimal("0.5"), Decimal("1")):
        value = low + (high - low) * fraction
        ticks.append({"y": y_of(value), "label": f"{value * 100:+.1f}%"})
    return {
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
        "line": line,
        "area": area,
        "ticks": ticks,
        "zero_y": y_of(ZERO),
        "plot_left": plot_left,
        "plot_right": plot_right,
        "tick_label_x": plot_left - 8,
        "x_label_y": CHART_HEIGHT - 8,
        "start_label": rows[0].as_of,
        "end_label": rows[-1].as_of,
    }


def performance(request: HttpRequest) -> HttpResponse:
    range_key, range_label, days = _resolve_range(request.GET.get("range"))
    latest = DailyPortfolioMetric.objects.order_by("-as_of").first()
    rows: list[DailyPortfolioMetric] = []
    if latest is not None:
        query = DailyPortfolioMetric.objects.order_by("as_of")
        if days is not None:
            query = query.filter(as_of__gte=latest.as_of - timedelta(days=days))
        rows = list(query)

    # 기간 수익률은 그 기간의 성과지수 비율이다. 누적 수익률을 빼서 만들면
    # 복리가 어긋난다.
    period_return = None
    if len(rows) >= 2 and rows[0].index_value > ZERO:
        period_return = rows[-1].index_value / rows[0].index_value - Decimal("1")

    classes = [
        {
            "name": row.name,
            "value_text": man_won_text(row.market_value),
            "return_text": signed_percent_text(row.period_return),
            "observed_days": row.observed_days,
            "trend": (
                ""
                if row.period_return is None
                else ("up" if row.period_return > ZERO else "down")
            ),
        }
        for row in class_performance([row.as_of for row in rows])
    ]

    return render(
        request,
        "report/stock_performance.html",
        {
            **_links("performance"),
            "has_data": latest is not None,
            "latest": latest,
            "range_key": range_key,
            "range_label": range_label,
            "ranges": [{"key": key, "label": label} for key, label, _ in RANGES],
            "chart": _line_chart(rows),
            "observed_days": len(rows),
            "first_day": rows[0].as_of if rows else None,
            "summary": _summary(latest, rows, period_return) if latest else None,
            "classes": classes,
        },
    )


def _summary(
    latest: DailyPortfolioMetric,
    rows: list[DailyPortfolioMetric],
    period_return: Decimal | None,
) -> dict:
    return {
        "market_value_text": man_won_text(latest.market_value),
        "first_value_text": man_won_text(rows[0].market_value) if rows else "-",
        "net_flow_text": signed_man_won_text(latest.cumulative_external_flow),
        "investment_pl_text": signed_man_won_text(latest.investment_pl),
        "cumulative_return_text": signed_percent_text(latest.cumulative_return),
        "period_return_text": signed_percent_text(period_return),
        "drawdown_text": percent_text(latest.drawdown, digits=2),
        "max_drawdown_text": percent_text(latest.max_drawdown, digits=2),
        "profit": latest.investment_pl >= ZERO,
    }
