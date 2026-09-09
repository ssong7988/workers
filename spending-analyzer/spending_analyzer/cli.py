"""Command-line interface. Stage 1 covers setup checks and mailbox diagnosis."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .diagnose import describe_message, verdict
from .env import MissingCredential, load_env, optional, require
from .mailbox import Mailbox, MailboxError
from .storage import StatementStore


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_DIR / "config" / "settings.yaml"
LOCAL_CONFIG = PROJECT_DIR / "config" / "settings.local.yaml"
DATA_DIR = PROJECT_DIR / "data"
SAMPLES_DIR = DATA_DIR / "samples"

GMAIL_HINT = (
    "Gmail 앱 비밀번호가 필요합니다 (계정 비밀번호가 아닙니다).\n"
    "  Google 계정 > 보안 > 2단계 인증 > 앱 비밀번호에서 발급한 뒤\n"
    f"  {PROJECT_DIR / '.env'} 에 넣으세요:\n"
    "    GMAIL_USER=본인주소@gmail.com\n"
    "    GMAIL_APP_PASSWORD=발급받은16자리"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="삼성카드 명세서 소비 분석")
    parser.add_argument(
        "--config", type=Path, default=LOCAL_CONFIG, help="설정 YAML 경로"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("validate-config", help="설정과 자격증명을 검증")

    scan = commands.add_parser(
        "scan-mail", help="명세서 메일의 구조를 진단 (파싱하지 않음)"
    )
    scan.add_argument("--limit", type=int, default=5, help="자세히 볼 최근 메일 수")
    scan.add_argument("--since", default=None, help="YYYY-MM-DD, 설정값을 덮어씀")
    scan.add_argument(
        "--dump",
        type=int,
        default=None,
        help="이 번호의 메일 원문과 첨부를 data/samples에 저장",
    )
    scan.add_argument(
        "--all-senders",
        action="store_true",
        help="제목 키워드가 안 맞는 메일도 함께 출력",
    )
    return parser


def _resolve_config(path: Path) -> Path:
    """Fall back to the tracked default when no local override exists."""
    if path == LOCAL_CONFIG and not path.exists():
        return DEFAULT_CONFIG
    return path


def _open_mailbox(config) -> Mailbox:
    user = require("GMAIL_USER", GMAIL_HINT)
    password = require("GMAIL_APP_PASSWORD", GMAIL_HINT)
    return Mailbox(config.mail, user, password)


def _validate_config(config, config_path: Path) -> None:
    print(f"설정 정상: {config_path}")
    print(f"  메일함   : {config.mail.host}:{config.mail.port} / {config.mail.folder}")
    print(f"  발신자   : {', '.join(config.mail.senders)}")
    print(f"  제목 조건: {', '.join(config.mail.subject_keywords) or '(없음 — 모든 메일 통과)'}")
    print(f"  수집 시작: {config.mail.since or '(제한 없음)'}")
    print(f"  분류 모델: {config.ai.model} ({'사용' if config.ai.enabled else '미사용'})")

    for name, hint in (
        ("GMAIL_USER", GMAIL_HINT),
        ("GMAIL_APP_PASSWORD", GMAIL_HINT),
    ):
        try:
            require(name, hint)
            print(f"  {name}: 설정됨")
        except MissingCredential:
            print(f"  {name}: 없음   ← scan-mail을 돌리려면 필요합니다")
    for name in ("SAMSUNG_PDF_PASSWORD", "ANTHROPIC_API_KEY"):
        print(f"  {name}: {'설정됨' if optional(name) else '없음 (선택)'}")

    store = StatementStore(DATA_DIR)
    months = store.months()
    print(f"  저장된 명세서: {len(months)}개월" + (f" ({months[0]} ~ {months[-1]})" if months else ""))


def _dump_message(message, index: int) -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{index:02d}-uid{message.uid}"
    body = SAMPLES_DIR / f"{stem}-body.txt"
    body.write_text(message.body_text(), encoding="utf-8")
    written = [body]
    if message.html_body:
        html = SAMPLES_DIR / f"{stem}-body.html"
        html.write_text(message.html_body, encoding="utf-8")
        written.append(html)
    for order, attachment in enumerate(message.attachments, start=1):
        suffix = Path(attachment.filename).suffix or ".bin"
        target = SAMPLES_DIR / f"{stem}-att{order}{suffix}"
        target.write_bytes(attachment.content)
        written.append(target)
    print(f"\n샘플 저장 ({len(written)}개):")
    for path in written:
        print(f"  {path}")
    print("  이 폴더는 커밋되지 않습니다. 개인정보가 담겨 있으니 공유하지 마세요.")


def _scan_mail(config, args) -> None:
    pdf_password = optional("SAMSUNG_PDF_PASSWORD")
    with _open_mailbox(config) as mailbox:
        uids = mailbox.search_uids(args.since)
        window = args.since if args.since is not None else config.mail.since
        print(
            f"발신자 {', '.join(config.mail.senders)} / "
            f"{window or '전체 기간'} 기준 메일 {len(uids)}통"
        )
        if not uids:
            print()
            print(verdict([], pdf_password))
            return

        recent = uids[-args.limit :] if args.limit > 0 else uids
        print(f"최근 {len(recent)}통을 자세히 봅니다.\n")

        messages = []
        shown = 0
        for index, uid in enumerate(recent, start=1):
            message = mailbox.fetch(uid)
            matched = mailbox.matches_subject(message)
            if matched:
                messages.append(message)
            if matched or args.all_senders:
                shown += 1
                print(describe_message(message, index, pdf_password, subject_matched=matched))
                print()
            if args.dump == index:
                _dump_message(message, index)

        skipped = len(recent) - len(messages)
        if skipped and not args.all_senders:
            print(f"제목 키워드가 맞지 않아 {skipped}통을 건너뛰었습니다 (--all-senders로 볼 수 있습니다).\n")

        print(verdict(messages, pdf_password))


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    load_env(PROJECT_DIR)
    try:
        config_path = _resolve_config(args.config)
        config = load_config(config_path)
        if args.command == "validate-config":
            _validate_config(config, config_path)
            return
        if args.command == "scan-mail":
            _scan_mail(config, args)
            return
    except (ValueError, RuntimeError, MailboxError, MissingCredential) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
