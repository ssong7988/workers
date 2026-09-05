"""로그인된 KB증권 웹 화면(mable)에서 내자산 표를 읽는다. **지금은 재워 뒀다.**

웹은 6시간마다 자동 로그아웃된다 - 자세한 이유는 `web/__init__.py` 참고.

핵심 약속은 네이버 수집기와 같다. **로그인은 사람이 하고, 프로그램은 이미
로그인된 브라우저에 붙어 화면에 보이는 것만 읽는다.** 인증서 비밀번호나 OTP를
저장하지도, 우회하지도 않는다. 내부 API를 호출하지도 않는다 - 사람이 보는 그
표를 그대로 읽는다.

DOM 구조에 기대지 않는 이유는 `grid.js` 첫머리에 적어 두었다.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..parsing import (
    HEADER_ALIASES,
    RowError,
    flatten_row,
    group_by_account,
    map_columns,
    missing_fields,
    row_to_position,
)

MABLE_URL = "https://mablewide.kbsec.com/go.able"
TAB_WORDS = ("국내주식", "해외주식", "금융상품")
GRID_SCRIPT = (Path(__file__).resolve().parent / "grid.js").read_text(encoding="utf-8")

# grid.js가 앵커로 쓸 헤더 글자. parsing의 별칭을 그대로 넘겨 두 곳이 어긋나지
# 않게 한다.
HEADER_LABELS = [alias for aliases in HEADER_ALIASES.values() for alias in aliases]

SCROLL_SCRIPT = """
(step) => {
  let moved = false;
  const elements = [document.scrollingElement, ...document.querySelectorAll('*')];
  for (const element of elements) {
    if (!element) continue;
    if (element.scrollHeight - element.clientHeight <= 20) continue;
    const before = element.scrollTop;
    element.scrollTop = step === 0 ? 0 : element.scrollTop + step;
    if (element.scrollTop !== before) moved = true;
  }
  return moved;
}
"""


class CollectionError(RuntimeError):
    """화면을 읽지 못했을 때. 추측해서 메우지 않고 여기서 멈춘다."""


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - 설치 안내
        raise CollectionError(
            "playwright가 설치돼 있지 않습니다. real-estate-finder의 가상환경으로 실행하세요."
        ) from exc
    return sync_playwright


def _cdp_help(endpoint: str) -> str:
    return (
        f"KB 전용 Edge에 붙지 못했습니다: {endpoint}\n"
        "Edge를 이 프로필로 다시 띄우려면 열린 창을 모두 닫고 실행을 반복하세요."
    )


class MableCollector:
    """열려 있는 mable 화면 하나를 읽는다."""

    # 화면이 뜰 때까지 기다리는 시간. 로그인과 메뉴 이동을 사람이 하는 동안이다.
    SCREEN_WAIT_SECONDS = 300
    POLL_SECONDS = 3.0
    SCROLL_STEP = 400
    MAX_SCROLL_ROUNDS = 60
    SETTLE_MS = 700

    def __init__(self, cdp_endpoint: str) -> None:
        self.cdp_endpoint = cdp_endpoint

    # ------------------------------------------------------------------ 연결

    def _connect(self, playwright):
        try:
            browser = playwright.chromium.connect_over_cdp(self.cdp_endpoint)
        except Exception as exc:
            raise CollectionError(_cdp_help(self.cdp_endpoint)) from exc
        if not browser.contexts:
            raise CollectionError("연결된 Edge에서 브라우저 컨텍스트를 찾지 못했습니다.")
        return browser, browser.contexts[0]

    @staticmethod
    def _kbsec_frames(context) -> list:
        frames = []
        for page in context.pages:
            for frame in page.frames:
                if "kbsec.com" in (frame.url or ""):
                    frames.append((page, frame))
        return frames

    def _ensure_mable_open(self, context) -> None:
        if self._kbsec_frames(context):
            return
        print(f"mable 화면이 열려 있지 않아 새 탭을 엽니다: {MABLE_URL}")
        page = context.new_page()
        page.goto(MABLE_URL, wait_until="domcontentloaded")

    # ------------------------------------------------------------------ 수확

    def _harvest(self, frame) -> dict[str, Any] | None:
        try:
            return frame.evaluate(
                GRID_SCRIPT,
                {
                    "headerLabels": HEADER_LABELS,
                    "tabWords": list(TAB_WORDS),
                    "minHeaderMatches": 4,
                },
            )
        except Exception:
            # 프레임이 방금 사라졌거나 아직 못 그렸을 뿐이다. 다음 회차에 다시 본다.
            return None

    @staticmethod
    def _usable_candidate(harvest: dict[str, Any] | None) -> dict[str, Any] | None:
        """필요한 열을 다 갖춘 후보만 고른다."""
        if not harvest:
            return None
        for candidate in harvest.get("candidates", []):
            columns = map_columns(candidate.get("headers", []))
            if not missing_fields(columns):
                candidate = dict(candidate)
                candidate["columns"] = columns
                return candidate
        return None

    def _find_screen(self, context, *, wait: bool) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        """내자산 표가 보이는 프레임을 찾는다. 없으면 사람에게 부탁하고 기다린다."""
        deadline = time.monotonic() + (self.SCREEN_WAIT_SECONDS if wait else 0)
        announced = False
        while True:
            best: tuple[Any, dict, dict] | None = None
            for _page, frame in self._kbsec_frames(context):
                harvest = self._harvest(frame)
                candidate = self._usable_candidate(harvest)
                if candidate is None:
                    continue
                if best is None or candidate["rowCount"] > best[2]["rowCount"]:
                    best = (frame, harvest, candidate)
            if best is not None:
                return best
            if time.monotonic() >= deadline:
                raise CollectionError(
                    "내자산 표를 찾지 못했습니다.\n"
                    "KB 전용 Edge에서 로그인한 뒤 내자산(보유종목) 화면을 열어 두고 다시 실행하세요.\n"
                    "화면은 열려 있는데 계속 실패하면 `probe` 명령으로 화면 구조를 덤프해 주세요."
                )
            if not announced:
                print(
                    "Edge에서 KB증권에 로그인하고 내자산 화면을 열어 두세요. "
                    f"화면이 보이면 자동으로 이어갑니다 (최대 {self.SCREEN_WAIT_SECONDS}초)."
                )
                announced = True
            time.sleep(self.POLL_SECONDS)

    def _harvest_all_rows(self, frame, page) -> tuple[list[list[list[str]]], list[str]]:
        """스크롤하며 행을 모은다. 가상 스크롤이면 보이는 것만 DOM에 있다."""
        frame.evaluate(SCROLL_SCRIPT, 0)
        page.wait_for_timeout(self.SETTLE_MS)

        seen: set[tuple] = set()
        rows: list[list[list[str]]] = []
        headers: list[str] = []
        for _round in range(self.MAX_SCROLL_ROUNDS):
            candidate = self._usable_candidate(self._harvest(frame))
            if candidate is None:
                break
            headers = candidate["headers"]
            added = 0
            for cells in candidate["rows"]:
                key = tuple(tuple(cell) for cell in cells)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(cells)
                added += 1
            moved = frame.evaluate(SCROLL_SCRIPT, self.SCROLL_STEP)
            if not moved and added == 0:
                break
            page.wait_for_timeout(self.SETTLE_MS)
        return rows, headers

    def _open_tab(self, frame, page, word: str) -> bool:
        try:
            tab = frame.get_by_text(word, exact=False).first
            if tab.count() == 0:
                return False
            tab.click(timeout=5_000)
        except Exception:
            return False
        page.wait_for_timeout(self.SETTLE_MS * 2)
        return True

    # ------------------------------------------------------------------ 공개

    def probe(self) -> dict[str, Any]:
        """화면 구조를 그대로 덤프한다. 진단용이고 아무것도 바꾸지 않는다."""
        sync_playwright = _load_playwright()
        with sync_playwright() as playwright:
            _browser, context = self._connect(playwright)
            try:
                self._ensure_mable_open(context)
                frames = self._kbsec_frames(context)
                if not frames:
                    raise CollectionError(
                        "kbsec.com 프레임을 찾지 못했습니다. mable에 접속한 탭이 있는지 확인하세요."
                    )
                dumps = []
                for _page, frame in frames:
                    harvest = self._harvest(frame)
                    if harvest is None:
                        continue
                    for candidate in harvest.get("candidates", []):
                        columns = map_columns(candidate.get("headers", []))
                        candidate["mapped_columns"] = columns
                        candidate["missing_fields"] = missing_fields(columns)
                        candidate["rows"] = candidate.get("rows", [])[:3]
                    dumps.append(harvest)
                return {"observed_at": iso_now(), "frames": dumps}
            finally:
                # 사용자가 띄운 브라우저다. 연결만 끊고 창은 그대로 둔다 -
                # 네이버 수집기가 외부 관리 컨텍스트를 다루는 방식과 같다.
                pass

    def collect_holdings(self) -> dict[str, Any]:
        """탭을 돌며 보유 종목을 읽어 계좌별로 묶은 결과를 돌려준다."""
        sync_playwright = _load_playwright()
        with sync_playwright() as playwright:
            _browser, context = self._connect(playwright)
            try:
                self._ensure_mable_open(context)
                frame, harvest, _candidate = self._find_screen(context, wait=True)
                page = frame.page
                page.bring_to_front()

                expected = {
                    tab["label"]: tab.get("count")
                    for tab in harvest.get("tabs", [])
                    if tab.get("count") is not None
                }
                if expected:
                    summary = ", ".join(f"{label} {count}" for label, count in expected.items())
                    print(f"화면이 말하는 건수: {summary}")

                positions: list[dict] = []
                tab_reports: list[dict] = []
                problems: list[str] = []

                for word in TAB_WORDS:
                    count = expected.get(word)
                    if count == 0:
                        tab_reports.append({"tab": word, "expected": 0, "rows": 0})
                        continue
                    if word != TAB_WORDS[0] and not self._open_tab(frame, page, word):
                        if count:
                            problems.append(f"{word} 탭을 열지 못했습니다 ({count}건).")
                        continue
                    rows, headers = self._harvest_all_rows(frame, page)
                    columns = map_columns(headers)
                    if missing_fields(columns):
                        if count:
                            problems.append(
                                f"{word} 탭에서 {', '.join(missing_fields(columns))} 열을 찾지 못했습니다."
                            )
                        continue
                    parsed, skipped = self._rows_to_positions(word, columns, rows)
                    positions.extend(parsed)
                    tab_reports.append(
                        {"tab": word, "expected": count, "rows": len(parsed), "skipped": skipped}
                    )
                    print(
                        f"{word}: {len(parsed)}건 읽음"
                        + (f" (화면 표기 {count}건)" if count is not None else "")
                    )
                    if count is not None and len(parsed) != count:
                        problems.append(
                            f"{word} 탭은 {count}건이라고 표시하는데 {len(parsed)}건만 읽었습니다."
                        )

                if problems:
                    raise CollectionError(
                        "화면과 읽은 결과가 맞지 않습니다. 저장하지 않고 멈춥니다.\n- "
                        + "\n- ".join(problems)
                    )
                if not positions:
                    raise CollectionError("보유 종목을 한 건도 읽지 못했습니다.")

                return {
                    "observed_at": iso_now(),
                    "as_of": date.today().isoformat(),
                    "source_url": harvest.get("url", ""),
                    "tabs": tab_reports,
                    "accounts": group_by_account(positions),
                }
            finally:
                # 사용자가 띄운 브라우저다. 연결만 끊고 창은 그대로 둔다 -
                # 네이버 수집기가 외부 관리 컨텍스트를 다루는 방식과 같다.
                pass

    @staticmethod
    def _rows_to_positions(
        word: str, columns: dict[str, int], rows: list[list[list[str]]]
    ) -> tuple[list[dict], int]:
        """행을 값으로 바꾼다. 합계·소계 줄은 종목명이 비어 자연히 걸러진다."""
        parsed: list[dict] = []
        skipped = 0
        for cells in rows:
            flat = flatten_row(columns, cells)
            try:
                parsed.append(row_to_position(columns, flat))
            except RowError as exc:
                # 표의 마지막 합계 줄처럼 종목이 아닌 줄이 섞인다. 값이 하나도
                # 없는 줄만 조용히 넘기고, 그 외에는 이유를 남긴다.
                if any(part.strip() for part in flat):
                    print(f"  {word}: 건너뜀 - {exc}")
                skipped += 1
        return parsed, skipped
