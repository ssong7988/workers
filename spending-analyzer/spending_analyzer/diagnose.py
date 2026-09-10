"""Report what the statement mail actually looks like, without decrypting it.

Guessing a statement's shape and writing regexes against the guess produces code
that gets thrown away. This module answers the questions that decide how the
parser has to work, so it can be written against a real message.

What the first real scan found: 삼성카드 sends the statement as an **encrypted
HTML attachment** (YettieSoft VestMail), not a PDF. The statement is inside the
file and the page's own JavaScript decrypts it once a password is typed; nothing
is fetched from the network. The PDF probe below is kept because other issuers
do attach PDFs, but the secure-mail path is the one that matters here.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from .mailbox import Attachment, MailMessage


PREVIEW_CHARS = 800
# Below this much text on the first page, a PDF is images rather than a text
# layer we could extract a table from.
TEXT_LAYER_MIN_CHARS = 100

# Markers of a VestMail self-decrypting attachment.
SECURE_MAIL_MARKERS = ("vestmail", "decform", 'id="password"', "var b_p")
NETWORK_MARKERS = ("XMLHttpRequest", "fetch(", "WebSocket")


@dataclass
class PdfProbe:
    filename: str
    size_bytes: int
    encrypted: bool = False
    opened: bool = False
    pages: int = 0
    first_page_chars: int = 0
    note: str = ""

    @property
    def has_text_layer(self) -> bool:
        return self.opened and self.first_page_chars >= TEXT_LAYER_MIN_CHARS

    def summary(self) -> str:
        size = f"{self.size_bytes / 1024:.0f}KB"
        if not self.opened:
            return f"{self.filename} ({size}) — 열지 못함: {self.note}"
        layer = (
            f"1페이지 텍스트 {self.first_page_chars}자"
            if self.has_text_layer
            else f"1페이지 텍스트 {self.first_page_chars}자 — 이미지 PDF로 보입니다 (OCR 필요)"
        )
        lock = "암호 있음(해제됨)" if self.encrypted else "암호 없음"
        return f"{self.filename} ({size}) — {lock}, {self.pages}페이지, {layer}"


@dataclass
class SecureMailProbe:
    filename: str
    size_bytes: int
    is_secure_mail: bool = False
    needs_network: bool = False
    markers: tuple[str, ...] = ()

    def summary(self) -> str:
        size = f"{self.size_bytes / 1024:.0f}KB"
        if not self.is_secure_mail:
            return f"{self.filename} ({size}) — 일반 HTML (보안메일 아님)"
        network = (
            "복호화에 서버 통신이 필요해 보입니다 — 오프라인 파싱 불가"
            if self.needs_network
            else "복호화가 파일 안에서 끝납니다 — 오프라인 파싱 가능"
        )
        return f"{self.filename} ({size}) — VestMail 보안메일, {network}"


def probe_pdf(attachment: Attachment, password: str = "") -> PdfProbe:
    """Open a PDF far enough to say whether its table could be extracted.

    Never raises: a probe that fails is itself a finding worth printing.
    """
    probe = PdfProbe(filename=attachment.filename, size_bytes=len(attachment.content))
    try:
        import pdfplumber
    except ImportError:
        probe.note = "pdfplumber가 설치되지 않았습니다 (pip install -r requirements.txt)"
        return probe

    attempts = ((password, False), ("", True)) if password else (("", False),)
    for candidate, is_retry in attempts:
        try:
            with pdfplumber.open(io.BytesIO(attachment.content), password=candidate) as pdf:
                probe.opened = True
                probe.encrypted = bool(candidate) or b"/Encrypt" in attachment.content
                probe.pages = len(pdf.pages)
                if pdf.pages:
                    probe.first_page_chars = len(pdf.pages[0].extract_text() or "")
                if is_retry:
                    probe.note = "설정한 비밀번호 없이 열렸습니다"
                return probe
        except Exception as exc:  # pdfminer raises several unrelated types here
            probe.note = f"{type(exc).__name__}: {exc}"
            if "password" in type(exc).__name__.lower() or "password" in str(exc).lower():
                probe.encrypted = True

    if probe.encrypted and not probe.opened:
        probe.note = (
            "암호가 걸려 있고 열리지 않았습니다. "
            ".env의 SAMSUNG_STATEMENT_PASSWORD를 확인하세요. "
            f"(마지막 오류: {probe.note})"
        )
    return probe


def probe_secure_mail(attachment: Attachment) -> SecureMailProbe:
    """Decide whether an HTML attachment is a self-decrypting statement.

    Only the markup is inspected — nothing is decrypted, so no password is
    needed and no statement content is read.
    """
    probe = SecureMailProbe(filename=attachment.filename, size_bytes=len(attachment.content))
    text = attachment.content.decode("utf-8", "replace")
    lowered = text.lower()

    found = tuple(marker for marker in SECURE_MAIL_MARKERS if marker in lowered)
    probe.markers = found
    # Two independent markers, so a mail that merely mentions the product does
    # not get mistaken for the encrypted document itself.
    probe.is_secure_mail = len(found) >= 2
    probe.needs_network = any(marker in text for marker in NETWORK_MARKERS)
    return probe


def describe_message(
    message: MailMessage, index: int, pdf_password: str = "", subject_matched: bool = True
) -> str:
    """One message's full diagnostic block."""
    lines = [
        f"[{index}] uid={message.uid}",
        f"  보낸사람 : {message.sender}",
        f"  제목     : {message.subject}" + ("" if subject_matched else "   ← 제목 키워드 불일치"),
        f"  날짜     : {message.date}",
        f"  Message-ID: {message.message_id or '(없음)'}",
        "  MIME 구조:",
    ]
    lines += [f"    {row}" for row in message.part_tree]

    if message.attachments:
        lines.append(f"  첨부 {len(message.attachments)}개:")
        for attachment in message.attachments:
            if attachment.is_pdf:
                lines.append(f"    - {probe_pdf(attachment, pdf_password).summary()}")
            elif _is_html(attachment):
                lines.append(f"    - {probe_secure_mail(attachment).summary()}")
            else:
                lines.append(
                    f"    - {attachment.filename} ({attachment.content_type},"
                    f" {len(attachment.content) / 1024:.0f}KB)"
                )
    else:
        lines.append("  첨부: 없음   ← 명세서 본문이 아니라 안내 메일일 수 있습니다")

    body = message.body_text()
    lines.append(f"  본문 텍스트 {len(body)}자 (앞 {PREVIEW_CHARS}자):")
    preview = body[:PREVIEW_CHARS] if body else "(본문 없음)"
    lines += [f"    | {row}" for row in preview.splitlines() or ["(빈 줄)"]]
    return "\n".join(lines)


def _is_html(attachment: Attachment) -> bool:
    return attachment.filename.lower().endswith((".html", ".htm")) or "html" in (
        attachment.content_type or ""
    ).lower()


def statement_attachments(message: MailMessage) -> list[Attachment]:
    """Attachments that look like a statement this project can open."""
    return [
        attachment
        for attachment in message.attachments
        if attachment.is_pdf
        or (_is_html(attachment) and probe_secure_mail(attachment).is_secure_mail)
    ]


def verdict(messages: list[MailMessage], pdf_password: str = "") -> str:
    """What the scan implies for the parser, stated plainly."""
    if not messages:
        return (
            "판정: 조건에 맞는 메일이 없습니다.\n"
            "  - config/settings.yaml의 mail.senders가 실제 발신 주소와 맞는지\n"
            "  - mail.since가 첫 명세서보다 앞선 날짜인지\n"
            "  - 명세서가 다른 라벨/폴더로 분류되지는 않았는지 확인하세요."
        )

    secure = [
        probe_secure_mail(attachment)
        for message in messages
        for attachment in message.attachments
        if _is_html(attachment)
    ]
    usable_secure = [probe for probe in secure if probe.is_secure_mail]
    pdfs = [
        probe_pdf(attachment, pdf_password)
        for message in messages
        for attachment in message.attachments
        if attachment.is_pdf
    ]
    readable_pdfs = [probe for probe in pdfs if probe.has_text_layer]

    if usable_secure:
        offline = [probe for probe in usable_secure if not probe.needs_network]
        if offline:
            return (
                f"판정: VestMail 보안메일 첨부 {len(offline)}건을 확인했습니다.\n"
                "  명세서가 첨부 안에 들어 있고 복호화가 파일 안에서 끝나므로 파싱할 수 있습니다.\n"
                "  .env에 SAMSUNG_STATEMENT_PASSWORD를 넣으세요 "
                "(생년월일 6자리 또는 사업자번호 뒤 7자리)."
            )
        return (
            "판정: 보안메일 첨부는 있으나 복호화에 서버 통신이 필요해 보입니다.\n"
            "  오프라인 파싱이 어려우므로 다른 경로를 검토해야 합니다."
        )

    if readable_pdfs:
        return (
            f"판정: PDF {len(readable_pdfs)}/{len(pdfs)}개에서 텍스트 레이어를 확인했습니다."
            " 표 추출로 진행할 수 있습니다."
        )
    if pdfs:
        return (
            "판정: PDF는 있으나 텍스트를 얻지 못했습니다.\n"
            "  암호가 걸려 있다면 SAMSUNG_STATEMENT_PASSWORD를 확인하고,\n"
            "  스캔 이미지라면 OCR이나 엑셀 반입 경로가 필요합니다."
        )
    return (
        "판정: 명세서로 볼 만한 첨부가 없습니다.\n"
        "  안내 메일만 잡혔을 수 있습니다. --all-senders와 --limit을 늘려 다시 확인하거나,\n"
        "  삼성카드 웹에서 받은 엑셀을 반입하는 경로로 전환해야 합니다."
    )
