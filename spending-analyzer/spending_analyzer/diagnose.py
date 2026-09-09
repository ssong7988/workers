"""Report what the statement mail actually looks like, without parsing it.

Guessing a statement's shape and writing regexes against the guess produces
code that gets thrown away. This module answers the four questions that decide
whether the mail-based approach works at all, so the parser can be written
against a real message:

  1. Does the PDF arrive as an attachment, or is there only a "view on the web"
     link? A link-only mail rules the approach out.
  2. Is the PDF password-protected?
  3. Does it carry a text layer, or is it scanned images? Images would need OCR.
  4. Does the HTML body already hold the detail, making the PDF unnecessary?
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from .mailbox import Attachment, MailMessage


PREVIEW_CHARS = 800
# Below this much text on the first page, the PDF is almost certainly scanned
# images rather than a text layer we can extract a table from.
TEXT_LAYER_MIN_CHARS = 100


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


def probe_pdf(attachment: Attachment, password: str = "") -> PdfProbe:
    """Open a PDF far enough to answer questions 2 and 3.

    Never raises: a probe that fails is itself a finding worth printing.
    """
    probe = PdfProbe(filename=attachment.filename, size_bytes=len(attachment.content))
    try:
        import pdfplumber
    except ImportError:
        probe.note = "pdfplumber가 설치되지 않았습니다 (pip install -r requirements.txt)"
        return probe

    for candidate, is_retry in ((password, False), ("", True)) if password else (("", False),):
        try:
            with pdfplumber.open(io.BytesIO(attachment.content), password=candidate) as pdf:
                probe.opened = True
                probe.encrypted = bool(candidate) or _looks_encrypted(attachment.content)
                probe.pages = len(pdf.pages)
                if pdf.pages:
                    probe.first_page_chars = len(pdf.pages[0].extract_text() or "")
                if is_retry:
                    probe.note = "설정한 비밀번호 없이 열렸습니다"
                return probe
        except Exception as exc:  # pdfminer raises several unrelated types here
            probe.note = f"{type(exc).__name__}: {exc}"
            if _is_password_error(exc):
                probe.encrypted = True

    if probe.encrypted and not probe.opened:
        probe.note = (
            "암호가 걸려 있고 열리지 않았습니다. "
            ".env의 SAMSUNG_PDF_PASSWORD를 확인하세요. "
            f"(마지막 오류: {probe.note})"
        )
    return probe


def _is_password_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    return "password" in name or "password" in str(exc).lower()


def _looks_encrypted(content: bytes) -> bool:
    """Heuristic for 'was encrypted but our password worked'."""
    return b"/Encrypt" in content


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
            else:
                lines.append(
                    f"    - {attachment.filename} ({attachment.content_type},"
                    f" {len(attachment.content) / 1024:.0f}KB)"
                )
    else:
        lines.append("  첨부: 없음   ← PDF가 없다면 본문 링크 전용 명세서일 수 있습니다")

    body = message.body_text()
    lines.append(f"  본문 텍스트 {len(body)}자 (앞 {PREVIEW_CHARS}자):")
    preview = body[:PREVIEW_CHARS] if body else "(본문 없음)"
    lines += [f"    | {row}" for row in preview.splitlines() or ["(빈 줄)"]]
    return "\n".join(lines)


def verdict(messages: list[MailMessage], pdf_password: str = "") -> str:
    """What the scan implies for the parser, stated plainly."""
    if not messages:
        return (
            "판정: 조건에 맞는 메일이 없습니다.\n"
            "  - config/settings.yaml의 mail.senders가 실제 발신 주소와 맞는지\n"
            "  - mail.since가 첫 명세서보다 앞선 날짜인지\n"
            "  - 명세서가 다른 라벨/폴더로 분류되지는 않았는지 확인하세요."
        )

    with_pdf = [item for item in messages if item.pdf_attachments]
    if not with_pdf:
        return (
            "판정: PDF 첨부가 있는 메일이 없습니다.\n"
            "  본문 링크 전용 명세서라면 메일 파싱으로는 상세 내역을 얻을 수 없습니다.\n"
            "  삼성카드 웹에서 받은 엑셀을 반입하는 경로로 전환해야 합니다."
        )

    probes = [
        probe_pdf(attachment, pdf_password)
        for message in with_pdf
        for attachment in message.pdf_attachments
    ]
    readable = [probe for probe in probes if probe.has_text_layer]
    locked = [probe for probe in probes if probe.encrypted and not probe.opened]

    if readable:
        note = (
            f"판정: PDF {len(readable)}/{len(probes)}개에서 텍스트 레이어를 확인했습니다."
            " 표 추출로 진행할 수 있습니다."
        )
        if locked:
            note += f"\n  다만 {len(locked)}개는 암호를 풀지 못했습니다. SAMSUNG_PDF_PASSWORD를 확인하세요."
        return note
    if locked:
        return (
            f"판정: PDF {len(locked)}개 모두 암호가 걸려 열리지 않았습니다.\n"
            "  .env에 SAMSUNG_PDF_PASSWORD를 넣고 다시 실행하세요."
        )
    return (
        "판정: PDF는 열리지만 텍스트가 거의 없습니다. 스캔 이미지 명세서로 보입니다.\n"
        "  표 추출이 불가능하므로 OCR을 붙이거나 엑셀 반입 경로로 전환해야 합니다."
    )
