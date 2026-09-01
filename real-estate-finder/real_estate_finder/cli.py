"""Command-line interface for setup, scheduled scans, and smoke tests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .collector import NaverBrowserCollector
from .config import load_config, validate_config
from .notifier import KakaoNotifier
from .service import FinderService
from .storage import FileStore


PROJECT_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = PROJECT_DIR.parent


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
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate-config", help="설정 검증")
    commands.add_parser("browser-login", help="Edge 로그인 프로필 준비")
    commands.add_parser("scan-once", help="즉시 1회 조회 및 정규 급매 알림")
    commands.add_parser("smoke-test", help="즉시 1회 조회하고 결과를 카카오톡으로 전송")
    commands.add_parser("scheduled-run", help="시간별 조회 및 오전 보고")
    commands.add_parser("send-digest", help="저장된 현재 매물 전체 보고")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
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

        store = FileStore(PROJECT_DIR / "data")
        notifier = KakaoNotifier(ROOT_DIR / "kakao-notifier")
        service = FinderService(config, collector, store, notifier)
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
