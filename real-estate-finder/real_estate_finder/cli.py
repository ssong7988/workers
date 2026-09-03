"""Command line for the collector.

This process opens the signed-in browser, reads the favorite complexes, and
posts what it saw to report-site. It does not decide which listings match, which
are bargains, what the report looks like, or what KakaoTalk receives - all of
that lives in `report-site/properties/` now, on top of the database.

That makes report-site a hard dependency of a scan, not just of reading the
report: `scan-once` checks the server is up before it touches the browser.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .api_client import ApiError, ReportSiteClient
from .collector import NaverBrowserCollector
from .models import Listing, SearchCondition, iso_now

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
LOCK_PATH = DATA_DIR / "run.lock"


@contextmanager
def run_lock() -> Iterator[None]:
    """Refuse to scrape twice at once; two runs would fight over the browser."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(
            f"이전 실행이 아직 진행 중입니다. 아니라면 {LOCK_PATH}를 지우세요."
        ) from exc
    try:
        os.write(handle, str(os.getpid()).encode("ascii"))
        os.close(handle)
        yield
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="과천 관심 매물 수집기")
    parser.add_argument("--headless", action="store_true", help="브라우저 창을 숨김")
    parser.add_argument(
        "--edge-cdp",
        default="http://127.0.0.1:9222",
        help="현재 실행 중인 Edge DevTools 주소 (빈 문자열이면 전용 프로필 사용)",
    )
    parser.add_argument(
        "--api-base",
        default=None,
        help="리포트 서버 주소 (기본값: FINDER_API_BASE 또는 http://127.0.0.1:8000)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-api", help="리포트 서버 연결과 검색 조건 확인")
    commands.add_parser("browser-login", help="Edge 로그인 프로필 준비")
    commands.add_parser("scan-once", help="즉시 1회 수집하고 리포트 서버에 전달")
    commands.add_parser(
        "smoke-test", help="즉시 1회 수집하고 급매 이력을 소모하지 않은 채 전체 매물 전송"
    )
    commands.add_parser(
        "collect-favorites",
        help="로그인된 화면의 관심부동산 매물을 JSON으로만 저장 (서버 전송 없음)",
    )
    return parser


def _fetch_conditions(client: ReportSiteClient) -> list[SearchCondition]:
    payload = client.conditions()
    conditions = [
        SearchCondition.from_api(item) for item in payload.get("conditions", [])
    ]
    if not conditions:
        raise RuntimeError(
            "활성 검색 조건이 없습니다. 리포트 서버 admin에서 조건을 켜세요."
        )
    return conditions


def _deduplicate(listings: list[Listing]) -> tuple[list[dict], int]:
    """One condition cannot report the same article twice.

    Two aliases of one condition can match two complex cards that share an
    article. The server rejects a duplicate and rolls the whole scan back, so
    drop it here and say how many went.
    """
    seen: set[str] = set()
    observations: list[dict] = []
    for listing in listings:
        if listing.key in seen:
            continue
        seen.add(listing.key)
        observations.append(listing.to_dict())
    return observations, len(listings) - len(observations)


def _collect_and_post(
    collector: NaverBrowserCollector, client: ReportSiteClient, *, smoke: bool
) -> bool:
    conditions = _fetch_conditions(client)
    print(f"활성 검색 조건 {len(conditions)}개를 받았습니다.")

    started_at = iso_now()
    collected: list[Listing] = []
    successful: list[str] = []
    failed: dict[str, str] = {}
    try:
        by_condition = collector.collect_all(conditions)
        for condition in conditions:
            successful.append(condition.id)
            collected.extend(by_condition.get(condition.id, []))
    except Exception as exc:
        # One favorites snapshot feeds every condition, so a failure is total.
        # Report it rather than swallowing it: the server records the failed
        # scan and, importantly, leaves existing listings active.
        print(f"수집 실패: {exc}", file=sys.stderr)
        failed = {condition.id: str(exc) for condition in conditions}
    finished_at = iso_now()

    observations, dropped = _deduplicate(collected)
    if dropped:
        print(f"같은 조건에서 중복된 매물 {dropped}건을 제외했습니다.")

    result = client.post_scan(
        {
            "started_at": started_at,
            "finished_at": finished_at,
            "observations": observations,
            "successful_conditions": successful,
            "failed_conditions": failed,
            "notify_urgent": True,
            "smoke": smoke,
        }
    )
    scan = result.get("scan", {})
    print(
        f"조회 완료: 수집 {scan.get('collected_count', 0)}, "
        f"조건충족 {scan.get('matched_count', 0)}, "
        f"급매 {scan.get('urgent_count', 0)}, "
        f"제외 {scan.get('excluded_count', 0)}, "
        f"실패 {len(scan.get('failed_conditions') or {})}"
    )
    # Always say whether Kakao went out and why. A silent finish is
    # indistinguishable from a failure.
    print(scan.get("notification", ""))
    return bool(scan.get("success"))


def _check_api(client: ReportSiteClient) -> None:
    health = client.health()
    print(f"리포트 서버: {client.base_url} ({health.get('status')}, DB {health.get('database')})")
    payload = client.conditions()
    rule = payload.get("global_rule", {})
    conditions = payload.get("conditions", [])
    print(f"거래 유형: {rule.get('trade_type')} · 활성 검색 조건 {len(conditions)}개")
    for item in conditions:
        print(f"  - {item.get('id')}: {item.get('name')}")


def _collect_favorites(collector: NaverBrowserCollector) -> None:
    snapshot = collector.collect_favorites_snapshot()
    output = DATA_DIR / "favorites-latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    total = sum(item["listing_count"] for item in snapshot["complexes"])
    cards = sum(item["card_count"] for item in snapshot["complexes"])
    expected = sum(item["expected_count"] for item in snapshot["complexes"])
    print(
        f"관심부동산 수집 완료: 단지 {len(snapshot['complexes'])}개, "
        f"카드 {cards}/{expected}개, 매매 매물 {total}건, {output}"
    )


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        collector = NaverBrowserCollector(
            DATA_DIR / "browser-profile",
            headed=not args.headless,
            cdp_endpoint=args.edge_cdp or None,
        )
        if args.command == "browser-login":
            collector.open_login()
            print("브라우저 로그인 프로필을 저장했습니다.")
            return
        if args.command == "collect-favorites":
            _collect_favorites(collector)
            return

        client = ReportSiteClient(args.api_base)
        if args.command == "check-api":
            _check_api(client)
            return

        # Fail before opening a browser if the server that owns the data is
        # not there. Without it a scan has nowhere to go.
        client.health()
        with run_lock():
            success = _collect_and_post(
                collector, client, smoke=args.command == "smoke-test"
            )
        if not success:
            raise SystemExit(1)
    except ApiError as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (RuntimeError, ValueError) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
