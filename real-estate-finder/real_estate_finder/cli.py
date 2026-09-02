"""Command-line interface for setup, scheduled scans, and smoke tests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from collections import Counter

from .card import CardItem, build_card_image
from .collector import NaverBrowserCollector
from .config import load_config, validate_config
from .models import Listing
from .notifier import REPORT_URL, KakaoNotifier
from .parsing import explain_condition
from .publish import (
    MANUAL_STEPS,
    SITE_DIR,
    VERIFY_ATTEMPTS,
    build_site,
    describe_live,
    is_live,
)
from .service import FinderService
from .storage import FileStore


PROJECT_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = PROJECT_DIR.parent


def _stored_card_items(store: FileStore) -> list[CardItem]:
    """Rebuild card items from the last successful scan."""
    state = store.load_state()
    listings = [
        Listing.from_dict(payload)
        for payload in state.get("listings", {}).values()
        if payload.get("active")
    ]
    if not listings:
        raise RuntimeError("저장된 활성 매물이 없습니다. 먼저 scan-once를 실행하세요.")
    return [
        (
            listing,
            listing.effective_urgent_price_won is not None
            and listing.price_won <= listing.effective_urgent_price_won,
            False,
        )
        for listing in listings
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="과천 관심 매물 모니터")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_DIR / "config" / "searches.local.yaml",
        help="검색 조건 YAML 경로",
    )
    parser.add_argument("--headless", action="store_true", help="브라우저 창을 숨김")
    parser.add_argument(
        "--edge-cdp",
        default="http://127.0.0.1:9222",
        help="현재 실행 중인 Edge DevTools 주소 (빈 문자열이면 전용 프로필 사용)",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="카드 이미지 대신 기존 텍스트 메시지로 전송",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate-config", help="설정 검증")
    commands.add_parser("browser-login", help="Edge 로그인 프로필 준비")
    commands.add_parser("scan-once", help="즉시 1회 조회 및 정규 급매 알림")
    commands.add_parser("smoke-test", help="즉시 1회 조회하고 결과를 카카오톡으로 전송")
    commands.add_parser("scheduled-run", help="시간별 조회 및 오전 보고")
    commands.add_parser("send-digest", help="저장된 현재 매물 전체 보고")
    commands.add_parser(
        "collect-favorites",
        help="로그인된 화면에서 관심부동산 6개 단지 매물을 JSON으로 저장",
    )
    preview = commands.add_parser(
        "preview-card", help="저장된 매물로 카드 이미지만 만들고 전송하지 않음"
    )
    preview.add_argument(
        "--out", type=Path, default=PROJECT_DIR / "data" / "card-preview.png"
    )
    publish = commands.add_parser(
        "publish-report",
        help="현재 리포트 데이터를 빌드·배포하고 라이브에 반영됐는지 확인",
    )
    publish.add_argument(
        "--verify-only",
        action="store_true",
        help="빌드와 배포는 건너뛰고 라이브 반영 여부만 확인",
    )
    explain = commands.add_parser(
        "explain-filters",
        help="수집된 매물이 조건을 통과했는지, 아니면 왜 빠졌는지 출력",
    )
    explain.add_argument(
        "--all", action="store_true", help="통과한 매물도 함께 출력"
    )
    return parser


def _explain_filters(config, store: FileStore, show_passed: bool) -> None:
    """Replay the filters over the last snapshot so exclusions are visible.

    Reads only the saved JSON, so it needs no browser and cannot disturb a scan.
    """
    snapshot_path = PROJECT_DIR / "data" / "favorites-latest.json"
    if not snapshot_path.exists():
        raise RuntimeError(
            f"수집 스냅샷이 없습니다: {snapshot_path}\n먼저 collect-favorites를 실행하세요."
        )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    print(f"수집 시각: {snapshot.get('observed_at', '?')}\n")

    for condition in config.searches:
        rows: list[tuple[Listing, str | None]] = []
        for complex_info in snapshot["complexes"]:
            compact = complex_info["name"].replace(" ", "")
            if not any(a.replace(" ", "") in compact for a in condition.complex_names):
                continue
            for raw in complex_info["listings"]:
                listing = Listing.from_dict({**raw, "condition_id": condition.id, "floor": None})
                rows.append((listing, explain_condition(listing, condition, config.low_floor)))
        if not rows:
            continue

        passed = [item for item in rows if item[1] is None]
        print(f"■ {condition.name}  (수집 {len(rows)}건 → 통과 {len(passed)}건)")
        reasons = Counter(reason.split(" (")[0] for _, reason in rows if reason)
        for label, count in reasons.most_common():
            print(f"    {label}: {count}건")
        for listing, reason in rows:
            if reason is None and not show_passed:
                continue
            mark = "통과" if reason is None else reason
            print(
                f"      {listing.price_won / 1e8:>6.2f}억 {listing.type_name:>9}"
                f" {listing.floor_text:>8}  {mark}"
            )
        print()


def _publish_report(verify_only: bool) -> None:
    """Build the report the last scan wrote, then prove the live page shows it.

    The page imports its data at build time and the deploy itself happens in the
    ChatGPT app-hosting UI, so "wrote the JSON" and "the button opens the right
    report" are two different things; only the live check tells them apart.
    """
    report_data = SITE_DIR / "app" / "report-data.json"
    if not report_data.exists():
        raise RuntimeError(f"리포트 데이터가 없습니다: {report_data}")
    data = json.loads(report_data.read_text(encoding="utf-8"))
    observed_at = data["observedAt"]
    total = sum(len(item["listings"]) for item in data["complexes"])
    print(
        f"발행 대상: 단지 {len(data['complexes'])}개, 매물 {total}건, 기준 {observed_at}"
    )
    print(f"현재 라이브: {describe_live(REPORT_URL)}")

    if not verify_only:
        print("사이트를 빌드합니다...")
        build_site()
        print("빌드 완료. 이제 앱 호스팅 UI에서 배포하세요.")
        print(MANUAL_STEPS)

    if is_live(observed_at, REPORT_URL, attempts=VERIFY_ATTEMPTS if verify_only else 1):
        print(f"발행 완료: {REPORT_URL} 가 {observed_at} 결과를 보여줍니다.")
        return
    print(f"아직 반영되지 않았습니다: {REPORT_URL}")
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "publish-report":
            _publish_report(args.verify_only)
            return
        if args.config.name == "searches.local.yaml" and not args.config.exists():
            args.config = PROJECT_DIR / "config" / "searches.yaml"
        config = load_config(args.config)
        validate_config(config, require_urls=False)
        collector = NaverBrowserCollector(
            PROJECT_DIR / "data" / "browser-profile",
            headed=not args.headless,
            cdp_endpoint=args.edge_cdp or None,
        )
        if args.command == "validate-config":
            print(f"설정 정상: 활성 검색 조건 {sum(c.enabled for c in config.searches)}개")
            return
        if args.command == "browser-login":
            collector.open_login()
            print("브라우저 로그인 프로필을 저장했습니다.")
            return
        if args.command == "collect-favorites":
            snapshot = collector.collect_favorites_snapshot()
            output = PROJECT_DIR / "data" / "favorites-latest.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(output)
            total = sum(item["listing_count"] for item in snapshot["complexes"])
            cards = sum(item["card_count"] for item in snapshot["complexes"])
            expected = sum(item["expected_count"] for item in snapshot["complexes"])
            print(
                f"관심부동산 수집 완료: 단지 {len(snapshot['complexes'])}개, "
                f"카드 {cards}/{expected}개, 매매 매물 {total}건, {output}"
            )
            return

        store = FileStore(PROJECT_DIR / "data")

        if args.command == "explain-filters":
            _explain_filters(config, store, args.all)
            return

        if args.command == "preview-card":
            items = _stored_card_items(store)
            image_path, width, height = build_card_image(
                items,
                args.out,
                heading="과천 관심 매물",
                report_url=REPORT_URL,
                timezone=config.timezone,
            )
            print(
                f"카드 이미지 생성: {image_path} "
                f"({width}x{height}px, {image_path.stat().st_size / 1024:.0f}KB, 매물 {len(items)}건)"
            )
            return

        notifier = KakaoNotifier(ROOT_DIR / "kakao-notifier")
        service = FinderService(config, collector, store, notifier, use_cards=not args.text_only)
        with store.run_lock():
            if args.command == "scan-once":
                result = service.scan()
            elif args.command == "smoke-test":
                result = service.smoke_test()
            elif args.command == "scheduled-run":
                result = service.scheduled_run()
            else:
                service.send_digest()
                print("저장된 매물 보고를 전송했습니다.")
                return
        print(
            f"조회 완료: 수집 {result.collected_count}, 조건충족 {len(result.matched)}, "
            f"급매 {len(result.urgent)}, 실패 {len(result.failed_conditions)}"
        )
        if not result.success:
            raise SystemExit(1)
    except (RuntimeError, ValueError) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
