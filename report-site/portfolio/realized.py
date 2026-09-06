"""거래내역에서 실현손익을 누적한다.

평가액 기반 수익률(`performance.py`)은 수집을 시작한 날부터만 말할 수 있다.
과거를 되살릴 방법이 없기 때문이다 - 지난날의 시세가 없다. 반면 **거래내역은
1년치를 통째로 받아올 수 있으므로** 확정된 손익만큼은 과거까지 채울 수 있다.

실현손익 = 매도 정산금액 − 판 만큼의 평균 취득원가 + 배당 + 이자 − 수수료 − 세금

정산금액은 이미 수수료와 세금을 뺀 실입금이므로 따로 빼지 않는다.

**모르는 것은 지어내지 않는다.** 1년 창 이전에 산 주식은 취득원가를 알 수 없다.
그런 매도는 손익을 0으로 넣는 대신 `원가 미상`으로 따로 세어 화면이 그 사실을
말하게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .models import CashFlow

ZERO = Decimal("0")
# 취득원가를 늘리는 것들. 매수는 현금을 주고, 입고는 주식만 들어온다.
ACQUISITIONS = ("buy", "transfer_in")
# 손익에 그대로 더해지는 것들. 투자 결과이지 원금 이동이 아니다.
INCOME = ("dividend", "interest")
COSTS = ("fee", "tax")


@dataclass
class Lot:
    """한 계좌·한 종목의 평균 취득원가."""

    quantity: Decimal = ZERO
    cost: Decimal = ZERO

    @property
    def unit_cost(self) -> Decimal:
        if self.quantity <= ZERO:
            return ZERO
        return self.cost / self.quantity

    def add(self, quantity: Decimal, amount: Decimal) -> None:
        self.quantity += quantity
        self.cost += amount

    def take(self, quantity: Decimal) -> tuple[Decimal, Decimal]:
        """판 만큼의 원가를 덜어낸다. `(덜어낸 원가, 원가를 모르는 수량)`."""
        known = min(quantity, self.quantity) if self.quantity > ZERO else ZERO
        unknown = quantity - known
        cost = self.unit_cost * known
        self.quantity -= known
        self.cost -= cost
        return cost, unknown


@dataclass
class DayResult:
    as_of: date
    realized: Decimal
    cumulative: Decimal


@dataclass
class RealizedSeries:
    days: list[DayResult] = field(default_factory=list)
    total: Decimal = ZERO
    # 취득원가를 모르는 매도 건수. 0이 아니면 화면이 그 사실을 밝혀야 한다.
    unknown_cost_sales: int = 0

    @property
    def has_data(self) -> bool:
        return bool(self.days)


def _acquisition_amount(flow: CashFlow) -> Decimal:
    """입고처럼 현금이 0인 취득은 수량×단가를 원가로 본다."""
    if flow.amount and flow.amount != ZERO:
        return abs(flow.amount)
    if flow.quantity and flow.unit_price:
        return flow.quantity * flow.unit_price
    return ZERO


def build_realized(until: date | None = None) -> RealizedSeries:
    """날짜순으로 훑으며 실현손익을 누적한다.

    계좌와 종목마다 평균단가를 들고 간다. 순서가 중요하므로 날짜, 그 안에서는
    기록된 순서대로 본다.
    """
    rows = (
        CashFlow.objects.filter(account__active=True)
        .select_related("instrument")
        .order_by("occurred_on", "id")
    )
    if until is not None:
        rows = rows.filter(occurred_on__lte=until)

    lots: dict[tuple[str, str], Lot] = {}
    by_day: dict[date, Decimal] = {}
    series = RealizedSeries()

    for flow in rows:
        gain = ZERO
        if flow.flow_type in ACQUISITIONS and flow.instrument_id:
            key = (flow.account_id, flow.instrument_id)
            lot = lots.setdefault(key, Lot())
            lot.add(flow.quantity or ZERO, _acquisition_amount(flow))
        elif flow.flow_type in ("sell", "transfer_out") and flow.instrument_id:
            key = (flow.account_id, flow.instrument_id)
            lot = lots.setdefault(key, Lot())
            quantity = flow.quantity or ZERO
            cost, unknown = lot.take(quantity)
            # 수량이 없으면 원가를 계산할 방법이 없다. 그대로 두면 매도대금
            # 전액이 이익으로 잡히면서 아무 표시도 남지 않는다 - 조용히 크게
            # 틀리는 자리라 반드시 센다.
            if unknown > ZERO or quantity <= ZERO:
                series.unknown_cost_sales += 1
            if flow.flow_type == "sell":
                gain = flow.amount - cost
        elif flow.flow_type in INCOME:
            gain = flow.amount
        elif flow.flow_type in COSTS:
            gain = flow.amount

        if gain != ZERO:
            by_day[flow.occurred_on] = by_day.get(flow.occurred_on, ZERO) + gain

    running = ZERO
    for day in sorted(by_day):
        running += by_day[day]
        series.days.append(DayResult(as_of=day, realized=by_day[day], cumulative=running))
    series.total = running
    return series
