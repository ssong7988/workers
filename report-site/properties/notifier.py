"""Kakao adapter and compact message formatting."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Callable

from django.conf import settings

from .models import Listing
from .statistics import eok_text


KAKAO_DIR = settings.ROOT_DIR / "kakao-notifier"
# Kakao's default text template caps the body at 200 characters, and the
# statistics headline now shares that budget with the listing lines.
TEXT_LIMIT = 200
OVERFLOW_RESERVE = 6
CardItem = tuple[Listing, bool, bool]


def format_eok(price_won: int) -> str:
    eok, remainder = divmod(price_won, 100_000_000)
    man = remainder // 10_000
    return f"{eok}억" if not man else f"{eok}억 {man:,}만"


def batch_listing_message(items: list[CardItem], *, budget: int = TEXT_LIMIT) -> str:
    urgent_count = sum(urgent for _, urgent, _ in items)
    new_count = sum(new for _, _, new in items)
    lines = [f"🏠 매물 알림 {len(items)}건 · 급매{urgent_count} · 신규{new_count}"]
    for listing, urgent, new in items:
        marker = "🚨" if urgent else ("🆕" if new else "·")
        name = listing.complex_name.replace("(주상복합)", "")
        line = (
            f"{marker}{name} {format_eok(listing.price_won)} "
            f"{listing.floor_text} {listing.direction}"
        )
        # Leave room for the trailing overflow line that replaces the rest.
        if len("\n".join([*lines, line])) > budget - OVERFLOW_RESERVE:
            remaining = len(items) - (len(lines) - 1)
            suffix = f"\n외 {remaining}건"
            while len("\n".join(lines) + suffix) > budget and len(lines) > 1:
                lines.pop()
                remaining += 1
                suffix = f"\n외 {remaining}건"
            return "\n".join(lines) + suffix
        lines.append(line)
    return "\n".join(lines)


def stats_headline(label: str, period) -> str:
    """One line describing the distribution the statistics button opens on."""
    if not period.samples or period.latest is None:
        return ""
    return (
        f"📊 {label} · 최저 {eok_text(period.minimum)} · "
        f"평균 {eok_text(period.latest.mean)} · 최고 {eok_text(period.maximum)}"
    )


def scan_summary_message(
    *,
    success: bool,
    collected_count: int,
    matched_count: int,
    urgent_count: int,
    failed_conditions: dict[str, str],
    smoke: bool = False,
) -> str:
    title = "✅ 즉시 조회 성공" if success else "❌ 즉시 조회 실패"
    if not smoke:
        title = "✅ 매물 조회 완료" if success else "❌ 매물 조회 실패"
    failures = ", ".join(failed_conditions) or "없음"
    return (
        f"{title}\n수집 {collected_count}건 · 조건충족 {matched_count}건 · "
        f"급매 {urgent_count}건\n실패 조건: {failures}"
    )[:200]


class KakaoNotifier:
    def __init__(
        self,
        kakao_dir: Path = KAKAO_DIR,
        sender: Callable[[str, str], None] | None = None,
        links_sender: Callable[..., None] | None = None,
    ) -> None:
        self.kakao_dir = kakao_dir
        self._sender = sender
        self._links_sender = links_sender

    def _load_module(self):
        module_path = self.kakao_dir / "kakao_notifier.py"
        spec = importlib.util.spec_from_file_location("project_kakao_notifier", module_path)
        if not spec or not spec.loader:
            raise RuntimeError(f"카카오 모듈을 불러올 수 없습니다: {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(self.kakao_dir))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def send(self, message: str, link_url: str) -> None:
        if self._sender:
            self._sender(message, link_url)
            return
        self._load_module().send_to_me(message, link_url)

    def send_links(self, message: str, buttons: list[tuple[str, str]]) -> None:
        """Send one text message carrying labelled buttons (at most two)."""
        if self._links_sender:
            self._links_sender(message, buttons)
            return
        self._load_module().send_links_to_me(message, buttons)
