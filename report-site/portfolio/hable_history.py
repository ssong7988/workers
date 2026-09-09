"""H-able의 계좌별 일간 기록을 포트폴리오 성과선으로 합친다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .models import HableAccountDailyMetric, InvestmentAccount

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class HablePortfolioDay:
    as_of: date
    market_value: Decimal
    external_flow: Decimal
    cumulative_external_flow: Decimal
    investment_pl: Decimal
    daily_return: Decimal
    cumulative_return: Decimal
    index_value: Decimal
    drawdown: Decimal
    max_drawdown: Decimal


def portfolio_history(account_id: str | None = None) -> list[HablePortfolioDay]:
    """모든 활성 KB계좌가 있는 날짜만 합쳐 최대 1년 성과를 돌려준다."""
    account_ids = list(
        InvestmentAccount.objects.filter(active=True, institution="KB증권")
        .exclude(account_type="")
        .values_list("pk", flat=True)
    )
    if account_id is not None:
        account_ids = [key for key in account_ids if key == account_id]
    if not account_ids:
        return []
    rows = HableAccountDailyMetric.objects.filter(account_id__in=account_ids)
    by_day: dict[date, dict[str, HableAccountDailyMetric]] = {}
    for row in rows:
        by_day.setdefault(row.as_of, {})[row.account_id] = row

    index = peak = ONE
    max_drawdown = ZERO
    cumulative_flow = cumulative_pl = ZERO
    previous: dict[str, HableAccountDailyMetric] | None = None
    result: list[HablePortfolioDay] = []
    for day in sorted(by_day):
        current = by_day[day]
        if set(current) != set(account_ids):
            continue
        market_value = sum((r.market_value for r in current.values()), ZERO)
        flow = sum((r.deposit - r.withdrawal for r in current.values()), ZERO)
        day_pl = sum((r.investment_pl for r in current.values()), ZERO)
        if previous is None:
            daily_return = ZERO
        elif len(account_ids) == 1:
            daily_return = current[account_ids[0]].daily_return
        else:
            denominator = sum((r.market_value for r in previous.values()), ZERO)
            weighted = sum(
                (previous[key].market_value * current[key].daily_return for key in account_ids),
                ZERO,
            )
            daily_return = weighted / denominator if denominator > ZERO else ZERO
        index *= ONE + daily_return
        peak = max(peak, index)
        drawdown = index / peak - ONE
        max_drawdown = min(max_drawdown, drawdown)
        cumulative_flow += flow
        cumulative_pl += day_pl
        result.append(
            HablePortfolioDay(
                as_of=day,
                market_value=market_value,
                external_flow=flow,
                cumulative_external_flow=cumulative_flow,
                investment_pl=cumulative_pl,
                daily_return=daily_return,
                cumulative_return=index - ONE,
                index_value=index,
                drawdown=drawdown,
                max_drawdown=max_drawdown,
            )
        )
        previous = current
    return result
