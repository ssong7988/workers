"""수집기 명령줄.

이 프로세스는 로그인된 H-able 화면을 읽고, 본 것을 report-site로 넘긴다. 어떤
종목이 어느 자산분류인지, 비중이 목표에서 얼마나 벗어났는지, 수익률과 MDD가
얼마인지는 전부 서버가 정한다.

그래서 리포트 서버는 읽기 대상이 아니라 실행 조건이다. `hable-import`는 창을
건드리기 전에 서버부터 확인한다 - 자료가 갈 곳이 없으면 수집할 이유도 없다.

`web-*` 명령은 재워 둔 웹 경로다. 동작하지만 쓰지 않는다(`web/__init__.py` 참고).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from .api_client import ApiError, StockApiClient
from .hable import keepalive
from .trades import rows_to_cash_flows, summarize, unknown_kinds
from .hable.collector import HableCollector
from .hable.extract import ExtractionError
from .hable.window import HableError
from .parsing import RowError
from .payload import build_import_payload, build_trade_payload

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
LOCK_PATH = DATA_DIR / "run.lock"


def _report_trades(snapshot: dict) -> dict[str, list[dict]]:
    """원본을 현금흐름으로 바꿔 보고, 모르는 거래종류는 한 번에 모아 보여준다.

    화면을 다시 만지지 않으므로 여기서 실패해도 원본은 이미 저장돼 있다.
    """
    unknown: dict[str, list[str]] = {}
    flows: dict[str, list[dict]] = {}
    for account, table in snapshot["accounts"].items():
        missing = unknown_kinds(table["headers"], table["rows"])
        if missing:
            unknown[account] = missing
            continue
        rows = rows_to_cash_flows(table["headers"], table["rows"], account)
        flows[account] = rows
        print(f"  {account}: 현금흐름 {len(rows)}건 {summarize(rows)}")

    if unknown:
        print()
        print("모르는 거래종류가 있어 그 계좌는 넘겼습니다:")
        for account, kinds in unknown.items():
            for kind in kinds:
                print(f"  {account}: {kind!r}")
        print("`stock_importer/trades.py`의 FLOW_KINDS에 적어 주세요.")
    total = sum(len(rows) for rows in flows.values())
    print(f"현금흐름 {total}건 (계좌 {len(flows)}/{len(snapshot['accounts'])}개)")
    return flows


def _send_trades(
    flows: dict[str, list[dict]], snapshot: dict, client: StockApiClient
) -> None:
    """계좌마다 거래내역을 서버로 넘긴다.

    같은 기간을 다시 보내도 서버가 `external_key`로 같은 행을 알아보므로
    안전하다. 그래서 겹치는 구간을 걱정하지 않고 돌릴 수 있다.
    """
    if not flows:
        print("보낼 것이 없습니다.")
        return
    _check_api(client)
    as_of = snapshot["until"]
    for account, rows in flows.items():
        if not rows:
            continue
        payload = build_trade_payload(
            account, as_of, rows, source_name=snapshot.get("source_name", "")
        )
        result = client.post_import_run(payload)
        run = result.get("import_run", result)
        state = run.get("status") or result.get("result") or "저장"
        print(f"  {account} → {state}: 현금흐름 {run.get('cash_flows', len(rows))}건")


def _trade_period(since: str | None, until: str | None) -> tuple[str, str]:
    """기본은 오늘까지의 1년. 화면이 1년 구간을 한 번에 받는 것을 확인했다."""
    end = date.fromisoformat(until) if until else date.today()
    if since:
        start = date.fromisoformat(since)
    else:
        try:
            start = end.replace(year=end.year - 1)
        except ValueError:  # 2월 29일
            start = end.replace(year=end.year - 1, day=28)
    if start > end:
        raise RuntimeError("시작일이 종료일보다 늦습니다.")
    return start.isoformat(), end.isoformat()


def _touch_session(collector: HableCollector, *, require_ready: bool) -> int:
    """세션을 깨우거나 준비 상태를 확인하고, 종료 코드를 돌려준다.

    수집이 이미 돌고 있으면 락을 기다리지 않고 넘어간다. 수집이 돈다는 것은
    세션이 살아 있다는 뜻이라 여기서 더 할 일이 없다.
    """
    if LOCK_PATH.exists():
        result = {"state": keepalive.STATE_BLOCKED, "detail": "다른 실행이 창을 쓰는 중입니다."}
    else:
        with run_lock():
            result = collector.check_ready() if require_ready else collector.keep_awake()
    print(f"{result['state']}: {result['detail']}")
    return keepalive.exit_code(result["state"], require_ready=require_ready)


@contextmanager
def run_lock() -> Iterator[None]:
    """같은 창을 두 실행이 동시에 만지지 못하게 한다."""
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


def hide_own_console() -> None:
    """우리 콘솔 창을 숨긴다.

    작업 스케줄러가 이 프로그램을 띄우면 cmd 콘솔이 화면 한가운데 뜬다. 그 창이
    H-able을 덮으면 우리 클릭이 H-able에 닿지 않는다 - 실제로 그 때문에 한참
    헛돌았다. 출력은 어차피 로그 파일로 가므로 창은 필요 없다.
    """
    import ctypes

    window = ctypes.windll.kernel32.GetConsoleWindow()
    if window:
        ctypes.windll.user32.ShowWindow(window, 0)  # SW_HIDE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KB증권 금융자산 수집기")
    parser.add_argument(
        "--api-base",
        default=None,
        help="리포트 서버 주소 (기본값: STOCK_API_BASE 또는 http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--hide-console",
        action="store_true",
        help="콘솔 창을 숨긴다 (작업 스케줄러 실행용 - 창이 H-able을 덮으면 클릭이 막힌다)",
    )
    parser.add_argument(
        "--edge-cdp",
        default="http://127.0.0.1:9223",
        help="재워 둔 web-* 명령이 쓰는 Edge DevTools 주소",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-api", help="리포트 서버 연결과 계좌 상태 확인")
    probe = commands.add_parser(
        "hable-probe", help="H-able 화면 구조 덤프 (전송 없음)"
    )
    probe.add_argument(
        "--screen",
        default=None,
        help="덤프할 화면번호 (기본값: 1285 총자산현황). 예: 0112 거래내역조회",
    )
    probe.add_argument(
        "--no-query",
        action="store_true",
        help="조회·복사·내보내기를 하지 않고 창 구조만 읽는다 (처음 보는 화면용)",
    )
    commands.add_parser(
        "hable-keepalive", help="세션이 끊기지 않게 조회를 한 번 누름 (사람이 자리에 있으면 건너뜀)"
    )
    commands.add_parser(
        "hable-status", help="수집할 수 있는 상태인지 확인 (준비 안 됐으면 실패로 끝남)"
    )
    commands.add_parser("hable-collect", help="H-able [1285]을 읽어 JSON으로만 저장")
    trades = commands.add_parser(
        "hable-trades", help="H-able [0112] 거래내역을 계좌별로 읽어 JSON으로만 저장"
    )
    trades.add_argument("--since", default=None, help="시작일 YYYY-MM-DD (기본값: 1년 전)")
    trades.add_argument("--until", default=None, help="종료일 YYYY-MM-DD (기본값: 오늘)")
    trades.add_argument(
        "--send", action="store_true", help="읽은 현금흐름을 리포트 서버로 보낸다"
    )
    trades.add_argument(
        "--from-file",
        action="store_true",
        help="화면을 만지지 않고 지난번 원본(hable-trades-raw.json)으로 다시 처리한다",
    )
    commands.add_parser("hable-import", help="H-able [1285]을 읽어 리포트 서버로 전달")
    commands.add_parser("web-browser", help="[재워 둠] KB 전용 Edge를 mable 주소로 띄우기")
    commands.add_parser("web-probe", help="[재워 둠] mable 화면 구조 덤프")
    commands.add_parser("web-collect", help="[재워 둠] mable 내자산을 JSON으로만 저장")
    return parser


def _write_json(name: str, payload: object) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = DATA_DIR / name
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return output


def _check_api(client: StockApiClient) -> dict:
    status = client.status()
    print(f"리포트 서버: {client.base_url}{client.prefix}")
    print(f"마지막 완전 수집일: {status.get('complete_as_of') or '없음'}")
    print(f"미분류 종목: {status.get('unclassified_instruments', 0)}개")
    for account in status.get("accounts", []):
        number = account.get("masked_number") or "(계좌번호 미등록)"
        print(
            f"  - {account.get('alias')} [{account.get('account_type')}] "
            f"{number} · {account.get('status')}"
        )
    return status


def _report_snapshot(snapshot: dict) -> None:
    accounts = snapshot["accounts"]
    total = sum(len(rows) for rows in accounts.values())
    print(f"계좌 {len(accounts)}개, 보유 {total}건을 읽었습니다.")
    for account_number, rows in sorted(accounts.items()):
        print(f"  - {account_number}: {len(rows)}건")


def _import(snapshot: dict, client: StockApiClient) -> bool:
    as_of = snapshot["as_of"]
    source = snapshot.get("source_name", "")
    failures: list[str] = []
    complete_as_of = None
    for account_number, rows in sorted(snapshot["accounts"].items()):
        payload = build_import_payload(account_number, as_of, rows, source_name=source)
        try:
            result = client.post_import_run(payload)
        except ApiError as exc:
            failures.append(f"{account_number}: {exc}")
            continue
        run = result.get("import_run", {})
        state = "이미 반영됨" if result.get("duplicate") else "저장됨"
        complete_as_of = result.get("complete_as_of") or complete_as_of
        new_instruments = result.get("new_instruments") or []
        print(
            f"{account_number} → {run.get('account')} {state}: "
            f"보유 {result.get('positions', 0)}건"
            + (f", 새 종목 {len(new_instruments)}개" if new_instruments else "")
        )

    if failures:
        print("\n전달하지 못한 계좌가 있습니다:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return False

    print(f"\n완전 수집일: {complete_as_of or '아직 아님 (필수 계좌가 남았습니다)'}")
    return True


def _print_probe(dump: dict) -> None:
    screen = dump["screen"]
    print(f"화면: {screen['title']}  rect={screen['rect']}")
    if dump["logged_out_notice"]:
        print(f"** 자동 로그아웃 안내창이 떠 있습니다: {dump['logged_out_notice']}")
    for dialog in dump["notice_dialogs"]:
        print(f"  안내창 {dialog['handle']} {dialog['rect']} {dialog['labels']}")
    grid = dump["grid_pane"]
    print(f"그리드로 고른 영역: {grid['handle']} ({grid['x']},{grid['y']}) "
          f"{grid['width']}x{grid['height']}  (후보 {len(dump['panes'])}개)")
    print(f"우클릭 메뉴 창: {dump['context_menu_windows'] or '없음'}")
    if dump.get('context_menu_items'):
        print(f"  메뉴 항목: {' | '.join(dump['context_menu_items'])}")
    print(f"클립보드: {dump['clipboard_characters']}자, {dump['clipboard_row_count']}행")
    if dump["clipboard_headers"]:
        print(f"  헤더: {' | '.join(dump['clipboard_headers'])}")
        print(f"  매핑: {dump['clipboard_columns']}")
        print(f"  누락: {dump['clipboard_missing_fields'] or '없음'}")
    export = dump.get("excel_export") or {}
    if export.get("error"):
        print(f"엑셀 내보내기: 실패 - {export['error'].splitlines()[0]}")
    elif export:
        print(f"엑셀 내보내기: {export.get('row_count')}행 → {export.get('file')}")
        print(f"  헤더: {' | '.join(export.get('headers') or [])}")
        print(f"  누락: {export.get('missing_fields') or '없음'}")
    print(f"화면 그림: {dump['screenshot']}")


def _web_collector(edge_cdp: str):
    from .web.collector import MableCollector

    print("[재워 둔 경로] mable 웹은 6시간마다 자동 로그아웃됩니다. 진단용으로만 쓰세요.")
    return MableCollector(edge_cdp)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.hide_console:
        hide_own_console()
    try:
        if args.command == "check-api":
            _check_api(StockApiClient(args.api_base))
            return

        if args.command.startswith("web-"):
            from .web.runtime import ensure_edge_debugging
            from .web.collector import MABLE_URL

            ensure_edge_debugging(args.edge_cdp, start_url=MABLE_URL)
            if args.command == "web-browser":
                print("KB증권에 로그인하고 내자산 화면을 열어 두세요.")
                return
            collector = _web_collector(args.edge_cdp)
            with run_lock():
                if args.command == "web-probe":
                    print(f"저장: {_write_json('web-probe-latest.json', collector.probe())}")
                else:
                    snapshot = collector.collect_holdings()
                    _report_snapshot(snapshot)
                    print(f"저장: {_write_json('web-holdings-latest.json', snapshot)}")
            return

        collector = HableCollector(DATA_DIR, screen=getattr(args, "screen", None))

        if args.command in ("hable-keepalive", "hable-status"):
            require_ready = args.command == "hable-status"
            raise SystemExit(_touch_session(collector, require_ready=require_ready))

        if args.command == "hable-probe":
            with run_lock():
                dump = collector.probe(query=not args.no_query)
            _print_probe(dump)
            name = f"hable-probe-{collector.screen}.json"
            print(f"전체 덤프: {_write_json(name, dump)}")
            return

        if args.command == "hable-trades":
            if args.from_file:
                snapshot = json.loads(
                    (DATA_DIR / "hable-trades-raw.json").read_text(encoding="utf-8")
                )
                print(f"지난번 원본으로 처리합니다: {snapshot['since']} ~ {snapshot['until']}")
            else:
                since, until = _trade_period(args.since, args.until)
                print(f"조회기간 {since} ~ {until}")
                with run_lock():
                    snapshot = collector.collect_trades(since, until)
                print(f"원본 저장: {_write_json('hable-trades-raw.json', snapshot)}")
            flows = _report_trades(snapshot)
            if args.send:
                _send_trades(flows, snapshot, StockApiClient(args.api_base))
            return

        if args.command == "hable-collect":
            with run_lock():
                snapshot = collector.collect_holdings()
            _report_snapshot(snapshot)
            print(f"저장: {_write_json('hable-holdings-latest.json', snapshot)}")
            return

        # hable-import: 자료가 갈 곳부터 확인한다.
        client = StockApiClient(args.api_base)
        _check_api(client)
        with run_lock():
            snapshot = collector.collect_holdings()
            _report_snapshot(snapshot)
            _write_json("hable-holdings-latest.json", snapshot)
            if not _import(snapshot, client):
                raise SystemExit(1)
    except ApiError as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (HableError, ExtractionError, RowError, RuntimeError, ValueError) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
