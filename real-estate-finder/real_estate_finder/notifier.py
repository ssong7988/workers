"""Kakao notifier adapter and message formatting."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable

from .models import Listing, ScanResult


REPORT_URL = "https://my-property-report-20260902.ssong7988.chatgpt.site"
# Kakao feed templates cap the title and description; the card image carries
# the detail, so these only ever hold a short summary.
CAPTION_LIMIT = 180


def format_eok(price_won: int) -> str:
    eok, remainder = divmod(price_won, 100_000_000)
    man = remainder // 10_000
    return f"{eok}억" if not man else f"{eok}억 {man:,}만"


def listing_message(listing: Listing, urgent: bool = False, new: bool = False) -> str:
    kind = "🚨 급매" if urgent else ("🆕 신규" if new else "🏠 매물")
    floor_kind = "저층" if listing.is_low_floor else "일반층"
    thresholds = "전체 매매 집계"
    if listing.effective_max_price_won is not None:
        thresholds = f"조사 {format_eok(listing.effective_max_price_won)}"
        if listing.effective_urgent_price_won is not None:
            thresholds += f" / 급매 {format_eok(listing.effective_urgent_price_won)}"
    message = (
        f"{kind} | {listing.complex_name} {listing.type_name}\n"
        f"{format_eok(listing.price_won)} · {listing.floor_text} · {listing.direction}\n"
        f"{floor_kind} {thresholds}"
    )
    return message[:200]


def batch_listing_message(items: list[tuple[Listing, bool, bool]]) -> str:
    """Build one compact Kakao message for every alert found in one scan."""
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
        candidate = "\n".join([*lines, line])
        if len(candidate) > 194:
            remaining = len(items) - (len(lines) - 1)
            suffix = f"\n외 {remaining}건"
            while len("\n".join(lines) + suffix) > 200 and len(lines) > 1:
                lines.pop()
                remaining += 1
                suffix = f"\n외 {remaining}건"
            return "\n".join(lines) + suffix
        lines.append(line)
    return "\n".join(lines)


def scan_summary_message(result: ScanResult, smoke: bool = False) -> str:
    title = "✅ 즉시 조회 성공" if result.success else "❌ 즉시 조회 실패"
    if not smoke:
        title = "✅ 매물 조회 완료" if result.success else "❌ 매물 조회 실패"
    failures = ", ".join(result.failed_conditions) or "없음"
    return (
        f"{title}\n수집 {result.collected_count}건 · 조건충족 {len(result.matched)}건 · "
        f"급매 {len(result.urgent)}건\n실패 조건: {failures}"
    )[:200]


def card_heading(items: list[tuple[Listing, bool, bool]]) -> str:
    """Short feed title. The card image carries the full list."""
    urgent_count = sum(urgent for _, urgent, _ in items)
    new_count = sum(new for _, _, new in items)
    # "관심 매물", not "알림": the count is every matched listing on the card,
    # of which only some triggered the alert.
    parts = [f"🏠 관심 매물 {len(items)}건"]
    if urgent_count:
        parts.append(f"급매 {urgent_count}")
    if new_count:
        parts.append(f"신규 {new_count}")
    return " · ".join(parts)[:CAPTION_LIMIT]


def card_caption(items: list[tuple[Listing, bool, bool]]) -> str:
    if not items:
        return ""
    cheapest = min(listing.price_won for listing, _, _ in items)
    names = list(dict.fromkeys(listing.complex_name for listing, _, _ in items))
    where = names[0] if len(names) == 1 else f"{names[0]} 외 {len(names) - 1}단지"
    return f"최저 {format_eok(cheapest)} · {where}"[:CAPTION_LIMIT]


class KakaoNotifier:
    def __init__(
        self,
        kakao_dir: Path,
        sender: Callable[[str, str], None] | None = None,
        image_sender: Callable[..., None] | None = None,
    ) -> None:
        self.kakao_dir = kakao_dir
        self._sender = sender
        self._image_sender = image_sender

    def _load_module(self):
        module_path = self.kakao_dir / "kakao_notifier.py"
        spec = importlib.util.spec_from_file_location("project_kakao_notifier", module_path)
        if not spec or not spec.loader:
            raise RuntimeError(f"카카오 모듈을 불러올 수 없습니다: {module_path}")
        module = importlib.util.module_from_spec(spec)
        import sys

        sys.path.insert(0, str(self.kakao_dir))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        return module

    def send(self, message: str, link_url: str = REPORT_URL) -> None:
        if self._sender:
            self._sender(message, link_url)
            return
        self._load_module().send_to_me(message, link_url)

    def send_image(
        self,
        image_path: Path,
        title: str,
        description: str,
        link_url: str | None = None,
        image_width: int | None = None,
        image_height: int | None = None,
    ) -> None:
        """Send the card. With no link_url it opens the full-resolution original."""
        if self._image_sender:
            self._image_sender(image_path, title, description, link_url)
            return
        self._load_module().send_card_to_me(
            image_path, title, description, link_url, image_width, image_height
        )
