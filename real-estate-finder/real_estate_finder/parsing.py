"""Turn Naver's on-screen text into numbers.

Only what collection needs to build a raw listing. Condition matching, floor
rules and bargain thresholds moved to `report-site/properties/matching.py` -
this process no longer judges anything.
"""

from __future__ import annotations

import re
from decimal import Decimal


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def parse_price_won(text: str) -> int:
    value = text.replace(" ", "").replace("원", "")
    if not value:
        raise ValueError("가격이 비어 있습니다.")
    total = Decimal(0)
    if "억" in value:
        eok, value = value.split("억", 1)
        match = _NUMBER.search(eok)
        if not match:
            raise ValueError(f"가격을 해석할 수 없습니다: {text}")
        total += Decimal(match.group().replace(",", "")) * 100_000_000
    match = _NUMBER.search(value)
    if match:
        number = Decimal(match.group().replace(",", ""))
        total += number if number >= 1_000_000 else number * 10_000
    if total <= 0:
        raise ValueError(f"가격을 해석할 수 없습니다: {text}")
    return int(total)


def normalize_type_name(text: str) -> str:
    compact = re.sub(r"\s+", "", text).upper()
    match = re.search(r"84(?:\.\d+)?([A-Z]?)", compact)
    return f"84{match.group(1)}" if match else compact
