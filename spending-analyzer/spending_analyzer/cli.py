"""Command-line interface.

The pipeline is `fetch → categorize → analyze → report`. Only `fetch` needs a
real statement mail; everything after it works on stored statements, so `demo`
can fill those in and the dashboard can be looked at before the first statement
arrives.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .analyze import analyze
from .categorize import (
    categorize,
    load_cache,
    load_rules,
    promote_to_rules,
    save_cache,
)
from .claude_client import classify_merchants, describe_usage
from .config import load_config
from .demo import build_demo_statements
from .diagnose import describe_message, statement_attachments, verdict
from .env import MissingCredential, load_env, optional, require, require_secret
from .mailbox import Mailbox, MailboxError
from .models import Statement
from .report import load_analysis, write_report
from .securemail import SecureMailError
from .statement import StatementParseError
from .statement import parse as parse_statement
from .storage import StatementStore, write_json


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_DIR / "config" / "settings.yaml"
LOCAL_CONFIG = PROJECT_DIR / "config" / "settings.local.yaml"
RULES_PATH = PROJECT_DIR / "config" / "rules.yaml"
DEFAULT_DATA_DIR = PROJECT_DIR / "data"

GMAIL_HINT = (
    "Gmail 앱 비밀번호가 필요합니다 (계정 비밀번호가 아닙니다).\n"
    "  Google 계정 > 보안 > 2단계 인증 > 앱 비밀번호에서 발급한 뒤\n"
    f"  {PROJECT_DIR / '.env'} 에 넣으세요:\n"
    "    GMAIL_USER=본인주소@gmail.com\n"
    "    GMAIL_APP_PASSWORD=발급받은16자리"
)

STATEMENT_HINT = (
    "명세서 첨부를 여는 비밀번호가 필요합니다.\n"
    f"  {PROJECT_DIR / '.env'} 에 넣으세요:\n"
    "    SAMSUNG_STATEMENT_PASSWORD=생년월일6자리\n"
    "  (메일 본문 안내: 생년월일 6자리 또는 사업자번호 뒤 7자리)"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="삼성카드 명세서 소비 분석")
    parser.add_argument("--config", type=Path, default=LOCAL_CONFIG, help="설정 YAML 경로")
    parser.add_argument(
        "--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="명세서와 결과를 둘 폴더"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("validate-config", help="설정과 자격증명을 검증")

    scan = commands.add_parser("scan-mail", help="명세서 메일의 구조를 진단 (파싱하지 않음)")
    scan.add_argument("--limit", type=int, default=5, help="자세히 볼 최근 메일 수")
    scan.add_argument("--since", default=None, help="YYYY-MM-DD, 설정값을 덮어씀")
    scan.add_argument("--dump", type=int, default=None, help="이 번호 메일의 원문·첨부를 저장")
    scan.add_argument("--all-senders", action="store_true", help="제목이 안 맞는 메일도 출력")

    fetch = commands.add_parser("fetch", help="메일의 명세서를 읽어 저장")
    fetch.add_argument("--since", default=None, help="YYYY-MM-DD, 설정값을 덮어씀")
    fetch.add_argument(
        "--force", action="store_true", help="이미 저장된 청구월도 다시 읽음"
    )

    demo = commands.add_parser(
        "demo", help="가짜 명세서를 만들어 분류·집계·페이지를 먼저 확인"
    )
    demo.add_argument("--months", type=int, default=7, help="만들 개월 수")

    categorize_cmd = commands.add_parser("categorize", help="규칙과 AI로 카테고리를 매김")
    categorize_cmd.add_argument(
        "--promote", action="store_true", help="AI 분류 결과를 rules.yaml에 반영"
    )
    categorize_cmd.add_argument("--no-ai", action="store_true", help="규칙만 사용")

    commands.add_parser("analyze", help="집계해서 analysis.json 생성")
    commands.add_parser("report", help="analysis.json으로 대시보드 HTML 생성")

    serve = commands.add_parser("serve", help="대시보드를 로컬에서 열기")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않음")

    run = commands.add_parser("run", help="categorize → analyze → report를 한 번에")
    run.add_argument("--no-ai", action="store_true", help="규칙만 사용")
    return parser


def _resolve_config(path: Path) -> Path:
    """Fall back to the tracked default when no local override exists."""
    return DEFAULT_CONFIG if path == LOCAL_CONFIG and not path.exists() else path


def _paths(data_dir: Path) -> dict[str, Path]:
    return {
        "analysis": data_dir / "analysis.json",
        "cache": data_dir / "category-cache.json",
        "report_dir": data_dir / "report",
        "report": data_dir / "report" / "index.html",
        "samples": data_dir / "samples",
    }


def _open_mailbox(config) -> Mailbox:
    return Mailbox(
        config.mail,
        require("GMAIL_USER", GMAIL_HINT),
        require_secret("GMAIL_APP_PASSWORD", GMAIL_HINT),
    )


def _require_statements(store: StatementStore) -> list[Statement]:
    statements = store.load_all()
    if not statements:
        raise RuntimeError(
            f"저장된 명세서가 없습니다: {store.statements_dir}\n"
            "  실제 명세서가 아직 없다면 `demo`로 가짜 데이터를 만들어 확인할 수 있습니다."
        )
    return statements


def _validate_config(config, config_path: Path, store: StatementStore) -> None:
    print(f"설정 정상: {config_path}")
    print(f"  메일함   : {config.mail.host}:{config.mail.port} / {config.mail.folder}")
    print(f"  발신자   : {', '.join(config.mail.senders)}")
    print(f"  제목 조건: {', '.join(config.mail.subject_keywords) or '(없음 — 모든 메일 통과)'}")
    print(f"  수집 시작: {config.mail.since or '(제한 없음)'}")
    print(f"  분류 모델: {config.ai.model} ({'사용' if config.ai.enabled else '미사용'})")

    for name in ("GMAIL_USER", "GMAIL_APP_PASSWORD"):
        status = "설정됨" if optional(name) else "없음   ← scan-mail을 돌리려면 필요합니다"
        print(f"  {name}: {status}")
    for name in ("SAMSUNG_STATEMENT_PASSWORD", "ANTHROPIC_API_KEY"):
        print(f"  {name}: {'설정됨' if optional(name) else '없음 (선택)'}")

    rules = load_rules(RULES_PATH)
    print(f"  분류 규칙: 카테고리 {len(rules.categories)}개, 규칙 {len(rules.rules)}개")
    months = store.months()
    span = f" ({months[0]} ~ {months[-1]})" if months else ""
    print(f"  저장된 명세서: {len(months)}개월{span}")


def _dump_message(message, index: int, samples_dir: Path) -> None:
    samples_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{index:02d}-uid{message.uid}"
    written = [samples_dir / f"{stem}-body.txt"]
    written[0].write_text(message.body_text(), encoding="utf-8")
    if message.html_body:
        html = samples_dir / f"{stem}-body.html"
        html.write_text(message.html_body, encoding="utf-8")
        written.append(html)
    for order, attachment in enumerate(message.attachments, start=1):
        target = samples_dir / f"{stem}-att{order}{Path(attachment.filename).suffix or '.bin'}"
        target.write_bytes(attachment.content)
        written.append(target)
    print(f"\n샘플 저장 ({len(written)}개):")
    for path in written:
        print(f"  {path}")
    print("  이 폴더는 커밋되지 않습니다. 개인정보가 담겨 있으니 공유하지 마세요.")


def _scan_mail(config, args, samples_dir: Path) -> None:
    pdf_password = optional("SAMSUNG_STATEMENT_PASSWORD")
    with _open_mailbox(config) as mailbox:
        uids = mailbox.search_uids(args.since)
        window = args.since if args.since is not None else config.mail.since
        print(f"발신자 {', '.join(config.mail.senders)} / {window or '전체 기간'} 기준 메일 {len(uids)}통")
        if not uids:
            print()
            print(verdict([], pdf_password))
            return

        recent = uids[-args.limit :] if args.limit > 0 else uids
        print(f"최근 {len(recent)}통을 자세히 봅니다.\n")

        messages = []
        for index, uid in enumerate(recent, start=1):
            message = mailbox.fetch(uid)
            matched = mailbox.matches_subject(message)
            if matched:
                messages.append(message)
            if matched or args.all_senders:
                print(describe_message(message, index, pdf_password, subject_matched=matched))
                print()
            if args.dump == index:
                _dump_message(message, index, samples_dir)

        skipped = len(recent) - len(messages)
        if skipped and not args.all_senders:
            print(f"제목 키워드가 맞지 않아 {skipped}통을 건너뛰었습니다 (--all-senders로 볼 수 있습니다).\n")
        print(verdict(messages, pdf_password))


def _fetch(config, store: StatementStore, args) -> None:
    """Read every statement mail and store the months it yields.

    One statement that fails to parse does not stop the rest — the failure is
    named and the run continues, so a single format change never blocks months
    that are still readable.
    """
    password = require_secret("SAMSUNG_STATEMENT_PASSWORD", STATEMENT_HINT)
    existing = set(store.months())
    saved, skipped, failed = [], [], []

    with _open_mailbox(config) as mailbox:
        uids = mailbox.search_uids(args.since)
        print(f"메일 {len(uids)}통을 확인합니다.")
        candidates = []
        for uid in uids:
            message = mailbox.fetch(uid)
            if not mailbox.matches_subject(message):
                continue
            attachments = statement_attachments(message)
            if attachments:
                candidates.append((message, attachments))

    print(f"명세서 첨부가 있는 메일 {len(candidates)}통\n")
    for message, attachments in candidates:
        for attachment in attachments:
            label = f"{message.date[:16]} {attachment.filename}"
            try:
                statement = parse_statement(
                    attachment.content, password, source_ref=message.message_id
                )
            except (StatementParseError, SecureMailError) as exc:
                failed.append(label)
                print(f"  ✗ {label}\n    {exc}")
                continue

            if statement.billing_month in existing and not args.force:
                skipped.append(statement.billing_month)
                print(f"  · {statement.billing_month} 이미 저장됨 (--force로 다시 읽기)")
                continue

            store.save(statement)
            existing.add(statement.billing_month)
            saved.append(statement.billing_month)
            print(
                f"  ✓ {statement.billing_month}  {len(statement.transactions)}건  "
                f"{statement.total_billed_won:,}원  (소계와 일치)"
            )

    print(
        f"\n저장 {len(saved)}개월"
        + (f", 건너뜀 {len(skipped)}개월" if skipped else "")
        + (f", 실패 {len(failed)}건" if failed else "")
    )
    if saved:
        print("  다음: python -m spending_analyzer run")
    elif not skipped:
        print("  저장된 것이 없습니다. scan-mail로 메일 상태를 확인하세요.")


def _demo(store: StatementStore, months: int) -> None:
    statements = build_demo_statements(months)
    for statement in statements:
        store.save(statement)
    total = sum(item.parsed_total_won for item in statements)
    print(f"데모 명세서 {len(statements)}개월치를 만들었습니다: {store.statements_dir}")
    print(f"  기간 {statements[0].billing_month} ~ {statements[-1].billing_month}, 합계 {total:,}원")
    print("  금액은 전부 가짜입니다. 실제 명세서가 들어오면 같은 파일이 덮어써집니다.")
    print("  다음: python -m spending_analyzer run")


def _categorize(config, store: StatementStore, paths: dict[str, Path], use_ai: bool, promote: bool) -> None:
    rules = load_rules(RULES_PATH)
    statements = _require_statements(store)
    cache = load_cache(paths["cache"])
    transactions = [item for statement in statements for item in statement.transactions]

    result = categorize(transactions, rules, cache)
    print(
        f"규칙 {result.by_rule}건, 캐시 {result.by_cache}건, 결제유형 {result.by_payment_type}건 "
        f"→ 미분류 가맹점 {len(result.unmatched)}곳"
    )

    if result.unmatched and use_ai and config.ai.enabled:
        classified = classify_merchants(
            result.unmatched, rules, model=config.ai.model, batch_size=config.ai.batch_size
        )
        print(f"  {describe_usage(classified)}")
        if classified.assignments:
            cache.update(classified.assignments)
            save_cache(paths["cache"], cache)
            categorize(transactions, rules, cache)
            if promote:
                added = promote_to_rules(RULES_PATH, classified.assignments)
                print(f"  rules.yaml에 키워드 {added}개를 추가했습니다.")
    elif result.unmatched:
        print("  자동 분류를 건너뜁니다 (--no-ai 또는 ai.enabled=false).")

    for statement in statements:
        store.save(statement)
    remaining = sum(1 for item in transactions if item.category == "미분류")
    print(f"저장 완료. 남은 미분류 거래 {remaining}건 / 전체 {len(transactions)}건")


def _analyze(config, store: StatementStore, paths: dict[str, Path]) -> None:
    rules = load_rules(RULES_PATH)
    statements = _require_statements(store)
    data = analyze(statements, rules, config.analysis)
    write_json(paths["analysis"], data)
    print(f"집계 완료: {paths['analysis']}")
    print(f"  최근 청구월 {data['latest']}, 청구액 {data['latestTotal']:,}원")
    print(f"  6개월 평균 {data['trailingAverage']:,}원, 미분류 가맹점 {len(data['uncategorized'])}곳")


def _report(paths: dict[str, Path]) -> None:
    data = load_analysis(paths["analysis"])
    target = write_report(data, paths["report"])
    print(f"대시보드 생성: {target}")
    print(f"  브라우저로 열기: {target.as_uri()}")
    print("  또는: python -m spending_analyzer serve")


def _serve(paths: dict[str, Path], port: int, open_browser: bool) -> None:
    import functools
    import http.server
    import socketserver

    if not paths["report"].exists():
        raise RuntimeError(f"대시보드가 없습니다: {paths['report']}\n먼저 report를 실행하세요.")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(paths["report_dir"]))
    # Bound to loopback only: this page holds the whole spending history.
    with socketserver.TCPServer(("127.0.0.1", port), handler) as server:
        url = f"http://127.0.0.1:{port}/"
        print(f"대시보드: {url}  (Ctrl+C로 종료)")
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n종료했습니다.")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    load_env(PROJECT_DIR)
    store = StatementStore(args.data_dir)
    paths = _paths(args.data_dir)
    try:
        config = load_config(_resolve_config(args.config))
        if args.command == "validate-config":
            _validate_config(config, _resolve_config(args.config), store)
        elif args.command == "scan-mail":
            _scan_mail(config, args, paths["samples"])
        elif args.command == "fetch":
            _fetch(config, store, args)
        elif args.command == "demo":
            _demo(store, args.months)
        elif args.command == "categorize":
            _categorize(config, store, paths, not args.no_ai, args.promote)
        elif args.command == "analyze":
            _analyze(config, store, paths)
        elif args.command == "report":
            _report(paths)
        elif args.command == "serve":
            _serve(paths, args.port, not args.no_browser)
        elif args.command == "run":
            _categorize(config, store, paths, not args.no_ai, promote=False)
            _analyze(config, store, paths)
            _report(paths)
    except (ValueError, RuntimeError, MailboxError, MissingCredential, OSError) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
