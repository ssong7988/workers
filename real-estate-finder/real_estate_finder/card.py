"""Render matched listings as a single card image for KakaoTalk.

Kakao's default text template caps messages at 200 characters, which silently
drops listings once a scan finds more than a handful.  An image has no such
limit, so the whole list is rendered to one PNG and sent as a feed message.
"""

from __future__ import annotations

import html
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Listing
from .notifier import format_eok


CardItem = tuple[Listing, bool, bool]  # (listing, urgent, new)

MAX_ROWS = 40
CARD_WIDTH = 540
CARD_SCALE = 2
# Kakao accepted a 1080x4992 / 341KB upload, so this is headroom rather than a
# published limit; it only exists to stop a runaway card.
MAX_BYTES = 1_800_000


class CardRenderError(RuntimeError):
    """Any failure while producing the card image."""


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CardRenderError("playwright가 없습니다. requirements.txt를 설치하세요.") from exc
    return sync_playwright


def _now_text(timezone: str) -> str:
    """Local timestamp for the card header.

    Falls back to the machine's own zone when the IANA database is missing; a
    clock label is not worth failing the whole card over.
    """
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        now = datetime.now().astimezone()
    return now.strftime("%Y.%m.%d %H:%M")


def _sort_key(item: CardItem) -> tuple[bool, int, int]:
    listing, urgent, _new = item
    floor = listing.floor if listing.floor is not None else 999
    return (not urgent, listing.price_won, floor)


def _thresholds(listing: Listing) -> str:
    if listing.effective_max_price_won is None:
        return "전체 매매 집계"
    text = f"조사 {format_eok(listing.effective_max_price_won)}"
    if listing.effective_urgent_price_won is not None:
        text += f" · 급매 {format_eok(listing.effective_urgent_price_won)}"
    return text


def _row_html(item: CardItem) -> str:
    listing, urgent, new = item
    badges = ""
    if urgent:
        badges += '<span class="badge urgent">급매</span>'
    if new:
        badges += '<span class="badge new">신규</span>'
    if listing.is_low_floor:
        badges += '<span class="badge low">저층</span>'
    detail = " · ".join(
        part
        for part in (
            html.escape(listing.type_name),
            f"전용 {listing.exclusive_area_m2:g}㎡" if listing.exclusive_area_m2 else "",
            html.escape(listing.floor_text),
            html.escape(listing.direction),
        )
        if part
    )
    return (
        f'<div class="row{" urgent" if urgent else ""}">'
        f'<div class="row-main"><span class="price">{html.escape(format_eok(listing.price_won))}</span>{badges}</div>'
        f'<div class="row-detail">{detail}</div>'
        f'<div class="row-note">{html.escape(_thresholds(listing))}</div>'
        "</div>"
    )


def _complex_html(name: str, items: list[CardItem]) -> str:
    rows = "".join(_row_html(item) for item in items)
    return (
        '<section class="complex">'
        f'<div class="complex-head"><h2>{html.escape(name)}</h2>'
        f'<span class="count">{len(items)}건</span></div>'
        f"{rows}"
        "</section>"
    )


def render_card_html(
    items: list[CardItem],
    *,
    heading: str,
    generated_at: str,
    report_url: str,
    max_rows: int = MAX_ROWS,
) -> str:
    """Build a fully self-contained HTML card. No external fonts, images or scripts."""
    ordered = sorted(items, key=_sort_key)
    overflow = max(0, len(ordered) - max_rows)
    shown = ordered[:max_rows] if overflow else ordered

    grouped: dict[str, list[CardItem]] = {}
    for item in shown:
        grouped.setdefault(item[0].complex_name, []).append(item)

    urgent_count = sum(1 for _, urgent, _ in items if urgent)
    new_count = sum(1 for _, _, new in items if new)
    sections = "".join(_complex_html(name, group) for name, group in grouped.items())
    overflow_html = f'<p class="overflow">외 {overflow}건</p>' if overflow else ""

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{html.escape(heading)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: {CARD_WIDTH}px; min-height: 260px; background: #f5f7f6; color: #0f172a;
    font-family: "Malgun Gothic", "맑은 고딕", "Segoe UI", sans-serif;
  }}
  header {{ background: #102f25; color: #fff; padding: 22px 24px 20px; }}
  header .eyebrow {{ font-size: 13px; font-weight: 700; color: #a7f3d0; }}
  header h1 {{ font-size: 25px; font-weight: 800; margin-top: 7px; letter-spacing: -.4px; }}
  header .when {{ font-size: 12px; color: rgba(209,250,229,.75); margin-top: 7px; }}
  .summary {{ display: flex; gap: 9px; padding: 16px 24px 0; }}
  .summary div {{
    flex: 1; text-align: center; padding: 12px 6px; border-radius: 14px;
    background: #fff; border: 1px solid #e2e8f0;
  }}
  .summary .n {{ font-size: 23px; font-weight: 800; }}
  .summary .k {{ font-size: 11px; font-weight: 700; color: #64748b; margin-top: 3px; }}
  .summary .red .n {{ color: #b91c1c; }}
  .summary .green .n {{ color: #047857; }}
  .complex {{
    margin: 14px 24px 0; background: #fff; border: 1px solid #e2e8f0;
    border-radius: 16px; overflow: hidden;
  }}
  .complex-head {{
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    padding: 13px 16px; border-bottom: 1px solid #f1f5f9;
  }}
  .complex-head h2 {{ font-size: 15px; font-weight: 800; }}
  .count {{
    font-size: 11px; font-weight: 800; color: #047857; background: #ecfdf5;
    border-radius: 999px; padding: 4px 9px; white-space: nowrap;
  }}
  .row {{ padding: 11px 16px; border-top: 1px solid #f8fafc; }}
  .row:first-of-type {{ border-top: 0; }}
  .row.urgent {{ background: #fef2f2; border-left: 4px solid #dc2626; }}
  .row-main {{ display: flex; align-items: center; gap: 7px; }}
  .price {{ font-size: 17px; font-weight: 800; }}
  .row.urgent .price {{ color: #b91c1c; }}
  .badge {{ font-size: 10px; font-weight: 800; border-radius: 5px; padding: 2px 6px; color: #fff; }}
  .badge.urgent {{ background: #dc2626; }}
  .badge.new {{ background: #047857; }}
  .badge.low {{ background: #e2e8f0; color: #475569; }}
  .row-detail {{ font-size: 12px; color: #475569; margin-top: 4px; }}
  .row-note {{ font-size: 11px; color: #94a3b8; margin-top: 2px; }}
  .overflow {{ text-align: center; font-size: 12px; color: #64748b; padding: 12px 0 0; }}
  footer {{ padding: 18px 24px 22px; text-align: center; font-size: 11px; line-height: 1.6; color: #94a3b8; }}
</style></head>
<body>
  <header>
    <div class="eyebrow">관심부동산 매물 리포트</div>
    <h1>{html.escape(heading)}</h1>
    <div class="when">{html.escape(generated_at)} 조회 · 네이버 부동산 기준</div>
  </header>
  <div class="summary">
    <div><div class="n">{len(items)}</div><div class="k">확인 매물</div></div>
    <div class="red"><div class="n">{urgent_count}</div><div class="k">급매</div></div>
    <div class="green"><div class="n">{new_count}</div><div class="k">신규</div></div>
  </div>
  {sections}
  {overflow_html}
  <footer>호가 기준이며 거래 상태는 네이버 부동산에서 최종 확인하세요.<br>{html.escape(report_url)}</footer>
</body></html>"""


def render_card_png(
    card_html: str,
    out_path: Path,
    *,
    width: int = CARD_WIDTH,
    scale: int = CARD_SCALE,
    max_bytes: int = MAX_BYTES,
) -> tuple[Path, int, int]:
    """Screenshot the card HTML with headless Edge.

    The browser profile lives in an OS temp directory and is removed afterwards;
    pointing it inside the repo is what left `edge-shot-profile*` behind before.
    """
    sync_playwright = _load_playwright()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="ref-card-"))
    html_path = work_dir / "card.html"
    html_path.write_text(card_html, encoding="utf-8")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="msedge", headless=True, args=["--disable-gpu"]
            )
            try:

                def shoot(target: Path, factor: int, **options) -> tuple[int, int]:
                    page = browser.new_page(
                        viewport={"width": width, "height": 1200},
                        device_scale_factor=factor,
                    )
                    try:
                        page.goto(html_path.as_uri())
                        page.screenshot(path=str(target), full_page=True, **options)
                        css_width, css_height = page.evaluate(
                            "() => [document.body.scrollWidth, document.body.scrollHeight]"
                        )
                        return css_width * factor, css_height * factor
                    finally:
                        page.close()

                # Shrink, then fall back to JPEG, if the PNG overshoots the size
                # Kakao is willing to host.
                for factor in dict.fromkeys((scale, 1)):
                    card_width, card_height = shoot(out_path, factor)
                    if out_path.stat().st_size <= max_bytes:
                        return out_path, card_width, card_height

                jpeg_path = out_path.with_suffix(".jpg")
                card_width, card_height = shoot(jpeg_path, 1, type="jpeg", quality=80)
                out_path.unlink(missing_ok=True)
                return jpeg_path, card_width, card_height
            finally:
                browser.close()
    except CardRenderError:
        raise
    except Exception as exc:
        raise CardRenderError(f"카드 이미지를 렌더링하지 못했습니다: {exc}") from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def build_card_image(
    items: list[CardItem],
    out_path: Path,
    *,
    heading: str,
    report_url: str,
    timezone: str = "Asia/Seoul",
    max_rows: int = MAX_ROWS,
) -> tuple[Path, int, int]:
    if not items:
        raise CardRenderError("카드로 만들 매물이 없습니다.")
    card_html = render_card_html(
        items,
        heading=heading,
        generated_at=_now_text(timezone),
        report_url=report_url,
        max_rows=max_rows,
    )
    return render_card_png(card_html, out_path)
