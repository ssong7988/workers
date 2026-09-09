"""실제로 저장된 보유·현금흐름에서 자산분류별 관측 성과를 계산한다."""

from datetime import date, timedelta
from decimal import Decimal

from .models import (
    AssetClass,
    CashFlow,
    InstrumentDailyPrice,
    PositionSnapshot,
)
from .performance import Window, _dietz

ZERO, ONE = Decimal("0"), Decimal("1")


def _estimated_price_history(
    start: date | None, end: date, account_id: str | None
) -> list[dict]:
    """현재 수량을 고정한 자산분류별 외부시세 가격지수.

    거래 시점이 없으므로 과거 평가액이나 실제 투자수익률로 부르지 않는다.
    비현금 구성 종목 모두의 종가가 있는 날짜만 쓰며 현금성 종목은 1원으로 둔다.
    """
    # 선택 구간이 현재 잔고를 기록하기 전에서 끝나더라도 '현재 보유 구성'을
    # 과거 가격에 적용해야 한다. 따라서 수량 기준일은 항상 최신 스냅샷이다.
    holdings = PositionSnapshot.objects.filter(account__active=True)
    if account_id:
        holdings = holdings.filter(account_id=account_id)
    latest = holdings.order_by("-as_of").values_list("as_of", flat=True).first()
    if latest is None:
        return []
    holdings = holdings.filter(as_of=latest)
    quantities: dict[str, dict[str, Decimal]] = {}
    cash_flags: dict[str, bool] = {}
    for row in holdings.values(
        "instrument_id",
        "instrument__asset_class_id",
        "instrument__is_cash",
        "quantity",
    ):
        bucket = quantities.setdefault(row["instrument__asset_class_id"], {})
        instrument_id = row["instrument_id"]
        bucket[instrument_id] = bucket.get(instrument_id, ZERO) + row["quantity"]
        cash_flags[instrument_id] = row["instrument__is_cash"]
    if not quantities:
        return []

    prices = InstrumentDailyPrice.objects.filter(
        instrument_id__in={item for bucket in quantities.values() for item in bucket},
        as_of__lte=end,
    )
    if start is not None:
        prices = prices.filter(as_of__gte=start)
    by_instrument: dict[str, dict[date, Decimal]] = {}
    for row in prices.values("instrument_id", "as_of", "close"):
        by_instrument.setdefault(row["instrument_id"], {})[row["as_of"]] = row["close"]

    result = []
    classes = {item.pk: item for item in AssetClass.objects.filter(pk__in=quantities)}
    for category_id, held in quantities.items():
        priced_ids = [item for item in held if not cash_flags[item]]
        common_days = None
        for instrument_id in priced_ids:
            days = set(by_instrument.get(instrument_id, {}))
            common_days = days if common_days is None else common_days & days
        if priced_ids:
            ordered_days = sorted(common_days or ())
        else:
            first = start or end - timedelta(days=365)
            ordered_days = [first + timedelta(days=offset) for offset in range((end - first).days + 1)]
        if not ordered_days:
            continue
        values = [
            sum(
                (
                    quantity
                    * (ONE if cash_flags[instrument_id] else by_instrument[instrument_id][day])
                    for instrument_id, quantity in held.items()
                ),
                ZERO,
            )
            for day in ordered_days
        ]
        baseline = values[0]
        if baseline <= ZERO:
            continue
        peak = ONE
        mdd = ZERO
        points = []
        for day, value in zip(ordered_days, values):
            index = value / baseline
            peak = max(peak, index)
            drawdown = index / peak - ONE
            mdd = min(mdd, drawdown)
            points.append(
                {"day": day, "return": index - ONE, "drawdown": drawdown, "mdd": mdd}
            )
        category = classes[category_id]
        result.append(
            {
                "id": category.pk,
                "name": category.name,
                "points": points,
                "basis": "current_holdings_price_index",
            }
        )
    return result


def class_history(start: date | None, end: date, account_id: str | None = None) -> list[dict]:
    positions = PositionSnapshot.objects.filter(account__active=True, as_of__lte=end)
    if start is not None:
        positions = positions.filter(as_of__gte=start)
    if account_id:
        positions = positions.filter(account_id=account_id)
    values, coverage, owners = {}, {}, {}
    for row in positions.values("as_of", "account_id", "instrument__asset_class_id", "market_value_krw"):
        day, account, category = row["as_of"], row["account_id"], row["instrument__asset_class_id"]
        coverage.setdefault(day, set()).add(account)
        owners.setdefault(category, set()).add(account)
        bucket = values.setdefault(category, {})
        bucket[day] = bucket.get(day, ZERO) + row["market_value_krw"]
    external_series = _estimated_price_history(start, end, account_id)
    if not coverage:
        return external_series
    flows = CashFlow.objects.filter(account__active=True, occurred_on__gt=min(coverage),
                                   occurred_on__lte=end, flow_type__in=("buy", "sell"),
                                   instrument__isnull=False)
    if account_id:
        flows = flows.filter(account_id=account_id)
    by_class = {}
    for row in flows.values("occurred_on", "instrument__asset_class_id", "flow_type", "amount_krw"):
        amount = abs(row["amount_krw"])
        if row["flow_type"] == "sell":
            amount = -amount
        by_class.setdefault(row["instrument__asset_class_id"], []).append((row["occurred_on"], amount))
    result = []
    for category in AssetClass.objects.filter(pk__in=values):
        series = values[category.pk]
        # 늦게 추가된 계좌(코인 등)를 0원에서 증가한 수익으로 간주하지 않는다.
        days = [day for day in sorted(coverage) if owners[category.pk] <= coverage[day]]
        points = []
        index = peak = ONE
        mdd = ZERO
        previous = None
        for day in days:
            value = series.get(day, ZERO)
            if previous is not None:
                window = Window(previous, day)
                movements = [(amount, window.weight(moment))
                             for moment, amount in by_class.get(category.pk, [])
                             if previous < moment <= day]
                change, _ = _dietz(series.get(previous, ZERO), value, movements)
                index *= ONE + change
            peak = max(peak, index)
            drawdown = index / peak - ONE if peak > ZERO else ZERO
            mdd = min(mdd, drawdown)
            points.append({"day": day, "return": index - ONE, "drawdown": drawdown, "mdd": mdd})
            previous = day
        result.append({"id": category.pk, "name": category.name, "points": points})
    # 직접 입력 자산은 과거 보유 이력이 없으므로, 희소한 잔고 스냅샷 대신
    # 외부 일봉으로 만든 현재 보유 구성 가격지수를 쓴다.
    external_ids = {row["id"] for row in external_series}
    combined = [row for row in result if row["id"] not in external_ids] + external_series
    display_order = {
        asset_id: index
        for index, asset_id in enumerate(
            AssetClass.objects.filter(pk__in={row["id"] for row in combined})
            .values_list("pk", flat=True)
        )
    }
    return sorted(combined, key=lambda row: display_order[row["id"]])
