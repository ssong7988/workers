"""수집기가 닿지 않는 자산의 시세를 가져온다.

KB 밖의 코인은 [1285]에 나오지 않는다. 그래서 **수량은 사람이 admin에 넣고,
가격은 매일 시세에서 가져와** 그날의 스냅샷을 만든다. 수량이 자주 바뀌지 않는
자산이라 이 나눔이 통한다.

시세는 공개 API만 쓴다. 인증도 키도 없다. 실패하면 지어내지 않고 멈춘다 -
어제 가격으로 오늘 평가액을 적으면 조용히 틀린다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

UPBIT_TICKER_URL = "https://api.upbit.com/v1/ticker?markets="
TIMEOUT_SECONDS = 15.0
# `price_source`에 적는 형식: `업체:심볼`. 예) `upbit:KRW-BTC`
SOURCE_SEPARATOR = ":"
UPBIT = "upbit"


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


def _read(url: str) -> str:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
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
