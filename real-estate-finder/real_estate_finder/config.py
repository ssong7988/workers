"""YAML configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml

from .models import AppConfig, LowFloorRule, SearchCondition


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise ValueError(f"설정 파일이 없습니다: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    global_rules = raw.get("global_rules", {})
    low_raw = global_rules.get("low_floor", {})
    low_floor = LowFloorRule(
        numeric_floors=tuple(int(v) for v in low_raw.get("numeric_floors", [1, 2, 3])),
        labels=tuple(str(v).strip() for v in low_raw.get("labels", ["저", "저층"])),
        price_discount_won=int(low_raw.get("price_discount_won", 100_000_000)),
    )

    searches: list[SearchCondition] = []
    for item in raw.get("searches", []):
        allowed = item.get("allowed_types", "all")
        allowed_types = None if allowed == "all" else tuple(str(v).upper() for v in allowed)
        searches.append(
            SearchCondition(
                id=str(item["id"]),
                name=str(item["name"]),
                complex_names=tuple(str(v) for v in item.get("complex_names", [item["name"]])),
                search_url=str(item.get("search_url", "")).strip(),
                exclusive_area_m2=float(item["exclusive_area_m2"]),
                allowed_types=allowed_types,
                max_price_won=int(item["max_price_won"]),
                urgent_price_won=int(item["urgent_price_won"]),
                enabled=bool(item.get("enabled", True)),
            )
        )

    schedule = raw.get("schedule", {})
    config = AppConfig(
        trade_type=str(global_rules.get("trade_type", "sale")),
        low_floor=low_floor,
        searches=tuple(searches),
        timezone=str(schedule.get("timezone", "Asia/Seoul")),
        digest_weekdays=tuple(int(v) for v in schedule.get("digest_weekdays", [0, 1, 2, 3, 4])),
        digest_hour=int(schedule.get("digest_hour", 8)),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig, require_urls: bool = False) -> None:
    if config.trade_type != "sale":
        raise ValueError("초기 버전은 매매(sale)만 지원합니다.")
    if not config.searches:
        raise ValueError("검색 조건이 하나 이상 필요합니다.")
    ids = [condition.id for condition in config.searches]
    if len(ids) != len(set(ids)):
        raise ValueError("검색 조건 id는 고유해야 합니다.")
    if config.low_floor.price_discount_won < 0:
        raise ValueError("저층 가격 차감액은 음수일 수 없습니다.")
    for condition in config.searches:
        if condition.urgent_price_won > condition.max_price_won:
            raise ValueError(f"{condition.id}: 급매 기준이 조사 기준보다 높습니다.")
        if condition.urgent_price_won <= config.low_floor.price_discount_won:
            raise ValueError(f"{condition.id}: 저층 급매 기준이 0 이하가 됩니다.")
        if require_urls and condition.enabled and not condition.search_url:
            raise ValueError(f"{condition.id}: search_url을 입력하세요.")
        if condition.search_url:
            parsed = urlparse(condition.search_url)
            if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith("naver.com"):
                raise ValueError(f"{condition.id}: 네이버 HTTPS 검색 URL만 허용합니다.")
