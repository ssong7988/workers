"""현재 비중, 목표 대비 리밸런싱, 국민연금 비교.

세 가지를 계산하지만 분모는 하나다: **분류 가능한 금융자산 총액**. 미분류
종목은 분모에서 빠지고, 대신 얼마가 빠졌는지 화면이 명시한다. 임의 분류로
숫자를 채우는 쪽이 편하지만, 그러면 admin에서 분류를 손볼 이유가 사라진다.

리밸런싱은 현재 평가총액을 유지하는 참고 금액이다. 주문 실행도, 계좌별
배분도 하지 않는다 - ISA·연금·퇴직연금의 매매/인출 제약이 여기에 들어오면
그건 다른 기능이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import cos, pi, sin

from .display import round_to_man
from .importing import account_status, latest_complete_date
from .models import (
    BENCHMARK_LABELS,
    BENCHMARK_ORDER,
    AssetClass,
    BenchmarkAllocation,
    PortfolioTarget,
    PositionSnapshot,
)


ZERO = Decimal("0")
HUNDRED = Decimal("100")

# 분류 수만큼 돌려 쓰는 색. 부동산 화면의 녹색 계열과 어긋나지 않게 골랐다.
SLICE_COLORS = (
    "#047857",
    "#0ea5e9",
    "#f59e0b",
    "#7c3aed",
    "#e11d48",
    "#0f766e",
    "#64748b",
    "#a16207",
)
UNCLASSIFIED_COLOR = "#cbd5e1"


@dataclass(frozen=True)
class AllocationRow:
    asset_class_id: str
    name: str
    market_value: Decimal
    ratio: Decimal
    color: str
    target_percent: Decimal | None
    target_value: Decimal | None
    rebalance_value: Decimal | None

    @property
    def gap_points(self) -> Decimal | None:
        if self.target_percent is None:
            return None
        return self.ratio * HUNDRED - self.target_percent


@dataclass(frozen=True)
class Slice:
    path: str
    color: str
    label: str
    percent: Decimal


@dataclass(frozen=True)
class BenchmarkRow:
    category: str
    label: str
    mine_percent: Decimal
    benchmark_percent: Decimal

    @property
    def gap_points(self) -> Decimal:
        return self.mine_percent - self.benchmark_percent


@dataclass(frozen=True)
class AllocationView:
    as_of: date | None
    has_data: bool
    total_value: Decimal
    unclassified_value: Decimal
    gross_value: Decimal
    rows: list[AllocationRow]
    slices: list[Slice]
    target_effective_from: date | None
    target_note: str
    rounding_remainder: Decimal
    benchmark_as_of: date | None
    benchmark_rows: list[BenchmarkRow]
    accounts: list[dict]


def active_targets(as_of: date) -> tuple[date | None, dict[str, Decimal], str]:
    """`as_of`에 적용되는 목표 비중 세트.

    합계가 100%가 아니면 그 세트를 쓰지 않는다. 예전 세트로 조용히 되돌아가면
    화면은 멀쩡해 보이면서 실제와 다른 리밸런싱을 권하게 된다.
    """
    latest = (
        PortfolioTarget.objects.filter(effective_from__lte=as_of, active=True)
        .order_by("-effective_from")
        .values_list("effective_from", flat=True)
        .first()
    )
    if latest is None:
        return None, {}, "목표 비중이 아직 없습니다. admin에서 입력하세요."
    rows = PortfolioTarget.objects.filter(effective_from=latest, active=True)
    total = sum((row.target_percent for row in rows), ZERO)
    if total != HUNDRED:
        return (
            latest,
            {},
            f"{latest} 목표 비중 합계가 {total}%입니다. 100%로 맞추기 전에는 "
            "리밸런싱을 계산하지 않습니다.",
        )
    return latest, {row.asset_class_id: row.target_percent for row in rows}, ""


def _slices(rows: list[AllocationRow], unclassified: Decimal, gross: Decimal) -> list[Slice]:
    """도넛 조각의 SVG 경로를 서버에서 만든다.

    부동산 통계 화면과 같은 방식이다 - 브라우저에서 차트 라이브러리를 불러오지
    않고 좌표를 그대로 내려보낸다.
    """
    if gross <= ZERO:
        return []
    center, outer, inner = 110.0, 100.0, 58.0
    parts = [(row.name, row.market_value, row.color) for row in rows]
    if unclassified > ZERO:
        parts.append(("미분류", unclassified, UNCLASSIFIED_COLOR))

    result = []
    angle = -pi / 2  # 12시부터 시계 방향
    for label, value, color in parts:
        share = float(value / gross)
        sweep = share * 2 * pi
        end = angle + sweep
        large = 1 if sweep > pi else 0
        if share >= 0.9999:
            # 조각이 하나뿐이면 호가 닫히지 않는다. 도넛 두 개로 그린다.
            path = (
                f"M {center - outer:.2f} {center:.2f} "
                f"a {outer:.2f} {outer:.2f} 0 1 1 {outer * 2:.2f} 0 "
                f"a {outer:.2f} {outer:.2f} 0 1 1 {-outer * 2:.2f} 0 Z "
                f"M {center - inner:.2f} {center:.2f} "
                f"a {inner:.2f} {inner:.2f} 0 1 0 {inner * 2:.2f} 0 "
                f"a {inner:.2f} {inner:.2f} 0 1 0 {-inner * 2:.2f} 0 Z"
            )
        else:
            path = (
                f"M {center + outer * cos(angle):.2f} {center + outer * sin(angle):.2f} "
                f"A {outer:.2f} {outer:.2f} 0 {large} 1 "
                f"{center + outer * cos(end):.2f} {center + outer * sin(end):.2f} "
                f"L {center + inner * cos(end):.2f} {center + inner * sin(end):.2f} "
                f"A {inner:.2f} {inner:.2f} 0 {large} 0 "
                f"{center + inner * cos(angle):.2f} {center + inner * sin(angle):.2f} Z"
            )
        result.append(
            Slice(
                path=path,
                color=color,
                label=label,
                percent=(value / gross * HUNDRED),
            )
        )
        angle = end
    return result


def _benchmark_rows(
    values_by_class: dict[str, Decimal],
    classes: dict[str, AssetClass],
    total: Decimal,
) -> tuple[date | None, list[BenchmarkRow]]:
    """개인 비중을 공통분류로 접고, 국민연금 원본 비중을 100%로 정규화해 맞춘다."""
    benchmark_as_of = (
        BenchmarkAllocation.objects.order_by("-as_of")
        .values_list("as_of", flat=True)
        .first()
    )
    if benchmark_as_of is None or total <= ZERO:
        return benchmark_as_of, []

    mine: dict[str, Decimal] = {}
    for class_id, value in values_by_class.items():
        category = classes[class_id].benchmark_category
        if not category:
            continue
        mine[category] = mine.get(category, ZERO) + value

    folded: dict[str, Decimal] = {}
    rows = BenchmarkAllocation.objects.filter(as_of=benchmark_as_of)
    source_total = sum((row.source_percent for row in rows), ZERO)
    for row in rows:
        folded[row.benchmark_category] = (
            folded.get(row.benchmark_category, ZERO) + row.source_percent
        )
    if source_total <= ZERO:
        return benchmark_as_of, []

    comparison = []
    for category in BENCHMARK_ORDER:
        if category not in folded and category not in mine:
            continue
        comparison.append(
            BenchmarkRow(
                category=category,
                label=BENCHMARK_LABELS[category],
                mine_percent=mine.get(category, ZERO) / total * HUNDRED,
                # 원본 합계(99.8% 등)는 DB에 남기고, 비교할 때만 100%로 맞춘다.
                benchmark_percent=folded.get(category, ZERO) / source_total * HUNDRED,
            )
        )
    return benchmark_as_of, comparison


def build_allocation(as_of: date | None = None) -> AllocationView:
    """`as_of`(기본값: 마지막 완전 수집일)의 비중·리밸런싱·국민연금 비교."""
    as_of = as_of or latest_complete_date()
    if as_of is None:
        return AllocationView(
            as_of=None,
            has_data=False,
            total_value=ZERO,
            unclassified_value=ZERO,
            gross_value=ZERO,
            rows=[],
            slices=[],
            target_effective_from=None,
            target_note="아직 완전한 수집 결과가 없습니다.",
            rounding_remainder=ZERO,
            benchmark_as_of=None,
            benchmark_rows=[],
            accounts=account_status(None),
        )

    classes = {item.pk: item for item in AssetClass.objects.all()}
    values_by_class: dict[str, Decimal] = {}
    positions = PositionSnapshot.objects.filter(
        as_of=as_of, account__active=True
    ).values_list("instrument__asset_class_id", "market_value_krw")
    for class_id, value in positions:
        values_by_class[class_id] = values_by_class.get(class_id, ZERO) + value

    unclassified = ZERO
    classified: dict[str, Decimal] = {}
    for class_id, value in values_by_class.items():
        asset_class = classes.get(class_id)
        if asset_class is None or asset_class.is_unclassified:
            unclassified += value
        else:
            classified[class_id] = value
    total = sum(classified.values(), ZERO)
    gross = total + unclassified

    effective_from, targets, note = active_targets(as_of)
    # 목표에만 있고 지금은 하나도 없는 분류도 줄로 보여야 "여기를 사야 한다"가
    # 드러난다.
    class_ids = sorted(
        set(classified) | set(targets),
        key=lambda key: (
            classes[key].display_order if key in classes else 999,
            classes[key].name if key in classes else key,
        ),
    )

    rows = []
    for index, class_id in enumerate(class_ids):
        asset_class = classes.get(class_id)
        value = classified.get(class_id, ZERO)
        target_percent = targets.get(class_id)
        target_value = (
            total * target_percent / HUNDRED if target_percent is not None else None
        )
        rows.append(
            AllocationRow(
                asset_class_id=class_id,
                name=asset_class.name if asset_class else class_id,
                market_value=value,
                ratio=(value / total) if total > ZERO else ZERO,
                color=SLICE_COLORS[index % len(SLICE_COLORS)],
                target_percent=target_percent,
                target_value=target_value,
                rebalance_value=(target_value - value) if target_value is not None else None,
            )
        )

    # 만원으로 반올림해 표시하므로 매수 합계와 매도 합계가 정확히 상쇄되지
    # 않는다. 그 잔액을 숨기지 않고 화면에 적는다.
    remainder = sum(
        (
            round_to_man(row.rebalance_value)
            for row in rows
            if row.rebalance_value is not None
        ),
        ZERO,
    )

    benchmark_as_of, benchmark_rows = _benchmark_rows(classified, classes, total)

    return AllocationView(
        as_of=as_of,
        has_data=gross > ZERO,
        total_value=total,
        unclassified_value=unclassified,
        gross_value=gross,
        rows=rows,
        slices=_slices([row for row in rows if row.market_value > ZERO], unclassified, gross),
        target_effective_from=effective_from,
        target_note=note,
        rounding_remainder=remainder,
        benchmark_as_of=benchmark_as_of,
        benchmark_rows=benchmark_rows,
        accounts=account_status(as_of),
    )
