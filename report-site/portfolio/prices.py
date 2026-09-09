"""수집기가 닿지 않는 자산의 시세를 가져온다.

KB 밖의 코인은 [1285]에 나오지 않는다. 그래서 **수량은 사람이 admin에 넣고,
가격은 매일 시세에서 가져와** 그날의 스냅샷을 만든다. 수량이 자주 바뀌지 않는
자산이라 이 나눔이 통한다.

시세는 공개 API만 쓴다. 인증도 키도 없다. 실패하면 지어내지 않고 멈춘다 -
어제 가격으로 오늘 평가액을 적으면 조용히 틀린다.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal, InvalidOperation

UPBIT_TICKER_URL = "https://api.upbit.com/v1/ticker?markets="
UPBIT_DAY_CANDLE_URL = "https://api.upbit.com/v1/candles/days"
YAHOO_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/"
TIMEOUT_SECONDS = 15.0
# `price_source`에 적는 형식: `업체:심볼`. 예) `upbit:KRW-BTC`
SOURCE_SEPARATOR = ":"
UPBIT = "upbit"
YAHOO = "yahoo"

# H-able 잔고에는 종목명이 있지만 거래소 코드가 없다. 현재 보유 종목의 공식
# 종목코드를 명시해 일봉 심볼로 바꾼다. 이름이 정확히 일치할 때만 사용한다.
KNOWN_HISTORY_SOURCES = {
    "삼성전자": "yahoo:005930.KS",
    "저스템": "yahoo:417840.KQ",
    "현대차": "yahoo:005380.KS",
    "SK하이닉스": "yahoo:000660.KS",
    "RISE 200": "yahoo:148020.KS",
    "RISE 코스닥150": "yahoo:270810.KS",
    "KODEX 미국나스닥100(H)": "yahoo:449190.KS",
    "RISE 미국S&P500(H)": "yahoo:453330.KS",
    "SOL 미국배당다우존스(H)": "yahoo:452360.KS",
    "KIWOOM 인도Nifty50(합성)": "yahoo:200250.KS",
    "RISE 유로스탁스50(H)": "yahoo:379790.KS",
    "ACE KRX금현물": "yahoo:411060.KS",
}


class PriceError(RuntimeError):
    """시세를 가져오지 못했을 때."""


def parse_source(text: str) -> tuple[str, str] | None:
    """`upbit:KRW-BTC`를 `("upbit", "KRW-BTC")`로. 형식이 아니면 None."""
    value = (text or "").strip()
    if SOURCE_SEPARATOR not in value:
        return None
    provider, _, symbol = value.partition(SOURCE_SEPARATOR)
    provider, symbol = provider.strip().lower(), symbol.strip()
    if not provider or not symbol:
        return None
    return provider, symbol


def describe_source_error(text: str) -> str:
    """`price_source`가 쓸 수 없는 값이면 그 이유를, 괜찮으면 빈 문자열을.

    모델의 검증과 수집 명령이 같은 규칙을 보게 하려고 여기 둔다.
    """
    parsed = parse_source(text)
    if parsed is None:
        return (
            "`upbit:KRW-BTC`처럼 `업체:심볼` 형식으로 적어 주세요."
        )
    provider, _ = parsed
    if provider != UPBIT:
        return f"아직 모르는 시세 업체입니다: {provider!r}. 지금은 `{UPBIT}`만 됩니다."
    return ""


def _read(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 portfolio-history"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise PriceError(f"시세를 받지 못했습니다: {url}\n{error}") from error


def parse_upbit(body: str, symbols: list[str]) -> dict[str, Decimal]:
    """업비트 응답에서 심볼별 현재가.

    빠진 심볼은 조용히 넘기지 않는다. 하나라도 없으면 그 자산의 평가액을
    지어내게 되기 때문이다.
    """
    try:
        rows = json.loads(body)
    except ValueError as error:
        raise PriceError(f"시세 응답을 읽지 못했습니다: {error}") from error
    if not isinstance(rows, list):
        raise PriceError("시세 응답이 목록이 아닙니다.")

    prices: dict[str, Decimal] = {}
    for row in rows:
        market = str(row.get("market", ""))
        try:
            prices[market] = Decimal(str(row["trade_price"]))
        except (KeyError, InvalidOperation, TypeError) as error:
            raise PriceError(f"{market}의 현재가를 읽지 못했습니다: {error}") from error

    missing = [symbol for symbol in symbols if symbol not in prices]
    if missing:
        raise PriceError(f"시세에 없는 심볼입니다: {', '.join(missing)}")
    return prices


def fetch_prices(sources: list[str], *, read=_read) -> dict[str, Decimal]:
    """`price_source` 목록 → 원본 문자열별 가격.

    업체별로 한 번씩만 부른다. 아는 업체가 아니면 멈춘다.
    """
    wanted: dict[str, list[str]] = {}
    for source in sources:
        parsed = parse_source(source)
        if parsed is None:
            raise PriceError(
                f"시세 출처 형식이 아닙니다: {source!r}\n"
                "`upbit:KRW-BTC`처럼 `업체:심볼`로 적어 주세요."
            )
        provider, symbol = parsed
        if provider != UPBIT:
            raise PriceError(f"아직 모르는 시세 업체입니다: {provider!r}")
        wanted.setdefault(provider, []).append(symbol)

    prices: dict[str, Decimal] = {}
    for provider, symbols in wanted.items():
        unique = sorted(set(symbols))
        body = read(UPBIT_TICKER_URL + ",".join(unique))
        by_symbol = parse_upbit(body, unique)
        for source in sources:
            parsed = parse_source(source)
            if parsed and parsed[0] == provider:
                prices[source] = by_symbol[parsed[1]]
    return prices


def parse_upbit_daily(body: str, symbol: str) -> list[tuple[date, Decimal]]:
    """업비트 일봉 응답 → 오래된 날짜 순의 (KST 기준일, 종가)."""
    try:
        rows = json.loads(body)
    except ValueError as error:
        raise PriceError(f"일봉 응답을 읽지 못했습니다: {error}") from error
    if not isinstance(rows, list):
        raise PriceError("일봉 응답이 목록이 아닙니다.")
    prices: dict[date, Decimal] = {}
    for row in rows:
        market = str(row.get("market", ""))
        if market != symbol:
            raise PriceError(f"요청하지 않은 일봉 심볼입니다: {market or '(없음)'}")
        try:
            day = date.fromisoformat(str(row["candle_date_time_kst"])[:10])
            close = Decimal(str(row["trade_price"]))
        except (KeyError, ValueError, InvalidOperation, TypeError) as error:
            raise PriceError(f"{symbol}의 일봉을 읽지 못했습니다: {error}") from error
        if close <= 0:
            raise PriceError(f"{symbol}의 일봉 종가가 0 이하입니다: {close}")
        prices[day] = close
    return sorted(prices.items())


def parse_yahoo_daily(body: str, symbol: str) -> list[tuple[date, Decimal]]:
    """Yahoo Finance chart 응답 → KST 기준 오래된 날짜 순 종가."""
    try:
        payload = json.loads(body)
        chart = payload["chart"]
        if chart.get("error"):
            raise PriceError(f"{symbol} 일봉 오류: {chart['error']}")
        result = chart["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise PriceError(f"{symbol}의 Yahoo 일봉을 읽지 못했습니다: {error}") from error
    if len(timestamps) != len(closes):
        raise PriceError(f"{symbol}의 Yahoo 일봉 날짜와 종가 수가 다릅니다.")
    kst = timezone(timedelta(hours=9))
    prices = {}
    for stamp, raw_close in zip(timestamps, closes):
        if raw_close is None:
            continue
        try:
            day = datetime.fromtimestamp(int(stamp), timezone.utc).astimezone(kst).date()
            close = Decimal(str(raw_close))
        except (ValueError, OverflowError, InvalidOperation, TypeError) as error:
            raise PriceError(f"{symbol}의 Yahoo 일봉 값이 잘못됐습니다: {error}") from error
        if close > Decimal("0"):
            prices[day] = close
    return sorted(prices.items())


def fetch_daily_prices(
    source: str,
    *,
    start: date,
    end: date,
    read=_read,
) -> list[tuple[date, Decimal]]:
    """공개 API에서 start~end(포함) 일 종가를 페이지 단위로 받는다."""
    parsed = parse_source(source)
    if parsed is None:
        raise PriceError(f"시세 출처 형식이 아닙니다: {source!r}")
    provider, symbol = parsed
    if provider == YAHOO:
        period1 = int(
            datetime.combine(start - timedelta(days=3), datetime_time(), timezone.utc).timestamp()
        )
        period2 = int(
            datetime.combine(end + timedelta(days=2), datetime_time(), timezone.utc).timestamp()
        )
        query = urllib.parse.urlencode(
            {"period1": period1, "period2": period2, "interval": "1d", "events": "history"}
        )
        rows = parse_yahoo_daily(
            read(f"{YAHOO_CHART_URL}{urllib.parse.quote(symbol)}?{query}"), symbol
        )
        return [(day, close) for day, close in rows if start <= day <= end]
    if provider != UPBIT:
        raise PriceError(f"아직 모르는 시세 업체입니다: {provider!r}")
    if start > end:
        return []

    # `to`는 exclusive다. KST 다음 날 0시를 UTC ISO 문자열로 보낸다.
    kst = timezone(timedelta(hours=9))
    cursor = datetime.combine(end + timedelta(days=1), datetime_time(), kst)
    found: dict[date, Decimal] = {}
    while True:
        query = urllib.parse.urlencode(
            {"market": symbol, "to": cursor.isoformat(), "count": 200}
        )
        page = parse_upbit_daily(read(f"{UPBIT_DAY_CANDLE_URL}?{query}"), symbol)
        if not page:
            break
        for day, close in page:
            if start <= day <= end:
                found[day] = close
        oldest = page[0][0]
        if oldest <= start:
            break
        cursor = datetime.combine(oldest, datetime_time(), kst)
    return sorted(found.items())


# admin 목록에서 쓰는 짧은 캐시. 화면을 새로 그릴 때마다 업비트를 부르면
# 새로고침 몇 번에 호출이 쌓인다. 저장되는 값은 여전히 매일 도는
# `update_manual_positions`가 그 시각에 직접 받아온 가격이고, 이 캐시는
# 화면에 보여주는 용도로만 쓴다.
_CACHE_SECONDS = 60.0
_cache: dict[str, tuple[float, Decimal]] = {}


def fetch_prices_cached(sources: list[str], *, now=time.monotonic) -> dict[str, Decimal]:
    """`fetch_prices`와 같지만 최근에 받은 값은 다시 받지 않는다."""
    moment = now()
    fresh = {
        source: price
        for source, (stamp, price) in _cache.items()
        if source in sources and moment - stamp < _CACHE_SECONDS
    }
    missing = [source for source in sources if source not in fresh]
    if missing:
        for source, price in fetch_prices(missing).items():
            _cache[source] = (moment, price)
            fresh[source] = price
    return fresh
