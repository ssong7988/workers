"""현금흐름을 보정한 수익률·투자손익·MDD.

평가액만으로는 성과를 말할 수 없다. 월급이 들어온 달은 평가액이 오르고,
출금한 달은 내려가지만 둘 다 투자 결과가 아니다. 그래서 여기서는 외부
입출금을 제거한 성과지수를 만들고, 수익률과 MDD를 전부 그 지수 위에서 읽는다.

시각 정보 없이 날짜만 있는 현금흐름은 그날 장 마감에 발생한 것으로 본다
(`.agent/PROJECT_STATE.md`의 "계산 규칙"에 명시된 가정). Modified Dietz의
가중치는 그 가정에서 나오며, 마지막 날 흐름의 가중치는 0이 된다.

수집이 매일 되는 것은 아니므로 구간은 "직전 완전 수집일 다음날부터 이번
완전 수집일까지"다. 주말과 놓친 날의 흐름이 사라지지 않게 하려는 것이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from django.db import transaction
from django.db.models import Sum

from .importing import complete_dates
from .models import CashFlow, DailyPortfolioMetric, Instrument, PositionSnapshot


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class Window:
    """완전 수집일 하나와, 그 앞의 완전 수집일 이후에 생긴 현금흐름 구간."""

    start_after: date | None
    end: date

    def weight(self, moment: date) -> Decimal:
        """장 마감 가정에서의 Modified Dietz 가중치.

        구간의 마지막 날 흐름은 평가액에 반영된 직후이므로 분모에 기여하지
        않는다(가중치 0). 구간 첫날 흐름은 거의 온전히 기여한다.
        """
        if self.start_after is None:
            return ZERO
        span = (self.end - self.start_after).days
        if span <= 0:
            return ZERO
        elapsed = (moment - self.start_after).days
        return Decimal(span - elapsed) / Decimal(span)


def _windows(days: list[date]) -> list[Window]:
    return [
        Window(start_after=days[index - 1] if index else None, end=day)
        for index, day in enumerate(days)
    ]


def _market_values(days: Iterable[date]) -> dict[date, Decimal]:
    rows = (
        PositionSnapshot.objects.filter(as_of__in=list(days), account__active=True)
        .values("as_of")
        .annotate(total=Sum("market_value_krw"))
    )
    return {row["as_of"]: row["total"] or ZERO for row in rows}


def _external_flows(first_day: date) -> list[tuple[date, Decimal]]:
    rows = (
        CashFlow.objects.filter(
            is_external=True, occurred_on__gt=first_day, account__active=True
        )
        .values("occurred_on")
        .annotate(total=Sum("amount_krw"))
        .order_by("occurred_on")
    )
    return [(row["occurred_on"], row["total"] or ZERO) for row in rows]


def _dietz(
    begin_value: Decimal, end_value: Decimal, flows: list[tuple[Decimal, Decimal]]
) -> tuple[Decimal, Decimal]:
    """(수익률, 순현금흐름)을 돌려준다. `flows`는 (금액, 가중치) 목록이다."""
    net = sum((amount for amount, _ in flows), ZERO)
    denominator = begin_value + sum((amount * weight for amount, weight in flows), ZERO)
    if denominator <= ZERO:
        # 계좌가 비어 있다 다시 채워진 구간. 이 구간에는 성과가 없다고 본다.
        return ZERO, net
    return (end_value - begin_value - net) / denominator, net


@transaction.atomic
def rebuild_metrics() -> int:
    """완전 수집일 전체의 성과를 다시 계산한다. 계산한 날짜 수를 돌려준다.

    증분이 아니라 전체 재계산이다. 하루치가 뒤늦게 도착하거나 admin에서
    분류가 바뀌면 이후 전부가 달라지고, 대상 날짜가 많아야 수백 개다.
    """
    days = complete_dates()
    DailyPortfolioMetric.objects.exclude(as_of__in=days).delete()
    if not days:
        return 0

    values = _market_values(days)
    flows = _external_flows(days[0])

    index = ONE
    peak = ONE
    max_drawdown = ZERO
    cumulative_flow = ZERO
    first_value = values.get(days[0], ZERO)

    for window in _windows(days):
        end_value = values.get(window.end, ZERO)
        if window.start_after is None:
            daily_return, net = ZERO, ZERO
        else:
            in_window = [
                (amount, window.weight(moment))
                for moment, amount in flows
                if window.start_after < moment <= window.end
            ]
            daily_return, net = _dietz(
                values.get(window.start_after, ZERO), end_value, in_window
            )
        index *= ONE + daily_return
        cumulative_flow += net
        peak = max(peak, index)
        drawdown = index / peak - ONE
        max_drawdown = min(max_drawdown, drawdown)

        DailyPortfolioMetric.objects.update_or_create(
            as_of=window.end,
            defaults={
                "market_value": end_value,
                "external_flow": net,
                "cumulative_external_flow": cumulative_flow,
                "investment_pl": end_value - first_value - cumulative_flow,
                "daily_return": daily_return,
                "cumulative_return": index - ONE,
                "index_value": index,
                "peak_index": peak,
                "drawdown": drawdown,
                "max_drawdown": max_drawdown,
            },
        )
    return len(days)


# --- 자산분류별 성과 -------------------------------------------------------
#
# 총 포트폴리오와 같은 방법이지만 "외부"의 뜻이 다르다. 분류 하나의 입장에서는
# 그 분류로 들어온 매수와 나간 매도가 외부 현금흐름이다. 그래야 "돈을 더 넣어
# 늘어난 것"과 "값이 올라 늘어난 것"이 갈린다.


@dataclass(frozen=True)
class ClassPerformance:
    asset_class_id: str
    name: str
    market_value: Decimal
    period_return: Decimal | None
    observed_days: int


def _class_of_instrument() -> dict[str, tuple[str, str]]:
    return {
        row.pk: (row.asset_class_id, row.asset_class.name)
        for row in Instrument.objects.select_related("asset_class")
    }


def class_performance(days: list[date]) -> list[ClassPerformance]:
    """구간 `days`(완전 수집일만) 전체에 대한 자산분류별 수익률.

    관측일이 둘 미만이면 수익률을 만들지 않는다 — 하루치로 추세를 말하지
    않기로 한 규칙이다.
    """
    if not days:
        return []
    classes = _class_of_instrument()
    positions = PositionSnapshot.objects.filter(
        as_of__in=days, account__active=True
    ).values("as_of", "instrument_id", "market_value_krw")

    by_class: dict[str, dict[date, Decimal]] = {}
    for row in positions:
        mapped = classes.get(row["instrument_id"])
        if mapped is None:
            continue
        bucket = by_class.setdefault(mapped[0], {})
        bucket[row["as_of"]] = bucket.get(row["as_of"], ZERO) + row["market_value_krw"]

    windows = _windows(days)
    trades = (
        CashFlow.objects.filter(
            flow_type__in=("buy", "sell"),
            occurred_on__gt=days[0],
            occurred_on__lte=days[-1],
            account__active=True,
            instrument__isnull=False,
        ).values("occurred_on", "instrument_id", "flow_type", "amount_krw")
    )
    # 매수는 그 분류로 들어온 돈, 매도는 나간 돈이다. 원본 부호에 기대지 않고
    # 구분으로 정한다 - H-able 파일마다 부호 관행이 다를 수 있다.
    class_flows: dict[str, list[tuple[date, Decimal]]] = {}
    for row in trades:
        mapped = classes.get(row["instrument_id"])
        if mapped is None:
            continue
        signed = abs(row["amount_krw"])
        if row["flow_type"] == "sell":
            signed = -signed
        class_flows.setdefault(mapped[0], []).append((row["occurred_on"], signed))

    class_names = {klass: name for klass, name in classes.values()}
    results = []
    for asset_class_id, series in by_class.items():
        name = class_names.get(asset_class_id, asset_class_id)
        observed = [day for day in days if day in series]
        index = ONE
        if len(observed) >= 2:
            for window in windows:
                if window.start_after is None or window.end not in series:
                    continue
                begin = series.get(window.start_after)
                if begin is None:
                    continue
                in_window = [
                    (amount, window.weight(moment))
                    for moment, amount in class_flows.get(asset_class_id, [])
                    if window.start_after < moment <= window.end
                ]
                period_return, _ = _dietz(begin, series[window.end], in_window)
                index *= ONE + period_return
        results.append(
            ClassPerformance(
                asset_class_id=asset_class_id,
                name=name,
                market_value=series.get(days[-1], ZERO),
                period_return=(index - ONE) if len(observed) >= 2 else None,
                observed_days=len(observed),
            )
        )
    results.sort(key=lambda row: row.market_value, reverse=True)
    return results
