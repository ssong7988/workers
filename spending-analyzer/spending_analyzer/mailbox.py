"""IMAP access to the statement mailbox, using only the standard library.

`kakao-notifier` runs on zero third-party packages, and `imaplib` covers
everything needed here, so this avoids pulling in the Gmail API's OAuth stack
for what is a read-only mailbox scan. Gmail wants an app password rather than
the account password.
"""

from __future__ import annotations

import email
import email.utils
import html as html_module
import imaplib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email.header import decode_header, make_header
from email.message import Message
from typing import Iterator

from .models import MailConfig


IMAP_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

_TAG = re.compile(r"<[^>]+>")
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_WHITESPACE = re.compile(r"[ \t]*\n[ \t\n]*")


class MailboxError(RuntimeError):
    """Any failure talking to the mail server."""


@dataclass
class Attachment:
    filename: str
    content_type: str
    content: bytes

    @property
    def is_pdf(self) -> bool:
        return self.filename.lower().endswith(".pdf") or "pdf" in self.content_type.lower()


@dataclass
class MailMessage:
    uid: str
    message_id: str
    sender: str
    subject: str
    date: str
    html_body: str = ""
    text_body: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    part_tree: list[str] = field(default_factory=list)

    @property
    def pdf_attachments(self) -> list[Attachment]:
        return [item for item in self.attachments if item.is_pdf]

    def body_text(self) -> str:
        """Readable text from whichever body part the mail actually carries."""
        if self.text_body.strip():
            return self.text_body
        return html_to_text(self.html_body)


def decode_mime_header(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except (UnicodeDecodeError, LookupError, ValueError):
        # A malformed header is not worth failing a whole scan over.
        return raw


def html_to_text(html: str) -> str:
    if not html:
        return ""
    stripped = _SCRIPT_OR_STYLE.sub(" ", html)
    stripped = re.sub(r"<br\s*/?>|</p>|</tr>|</div>", "\n", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"</t[dh]>", "\t", stripped, flags=re.IGNORECASE)
    stripped = _TAG.sub("", stripped)
    stripped = html_module.unescape(stripped)
    return _WHITESPACE.sub("\n", stripped).strip()


def _imap_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.day:02d}-{IMAP_MONTHS[parsed.month - 1]}-{parsed.year}"


def _decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _walk_parts(message: Message) -> Iterator[tuple[int, Message]]:
    """Yield every part with its nesting depth, for the diagnostic part tree."""
    stack: list[tuple[int, Message]] = [(0, message)]
    while stack:
        depth, part = stack.pop()
        yield depth, part
        if part.is_multipart():
            for child in reversed(part.get_payload()):
                if isinstance(child, Message):
                    stack.append((depth + 1, child))


def parse_message(uid: str, raw: bytes) -> MailMessage:
    """Turn a fetched RFC822 blob into the fields the diagnostics and parser need."""
    message = email.message_from_bytes(raw)
    result = MailMessage(
        uid=uid,
        message_id=(message.get("Message-ID") or "").strip(),
        sender=decode_mime_header(message.get("From")),
        subject=decode_mime_header(message.get("Subject")),
        date=(message.get("Date") or "").strip(),
    )

    for depth, part in _walk_parts(message):
        content_type = part.get_content_type()
        filename = decode_mime_header(part.get_filename())
        disposition = (part.get_content_disposition() or "").lower()
        label = "  " * depth + content_type
        if filename:
            label += f"  [{filename}]"
        if disposition:
            label += f"  ({disposition})"
        result.part_tree.append(label)

        if part.is_multipart():
            continue
        if disposition == "attachment" or filename:
            content = part.get_payload(decode=True) or b""
            result.attachments.append(
                Attachment(
                    filename=filename or "(이름 없음)",
                    content_type=content_type,
                    content=content,
                )
            )
        elif content_type == "text/html" and not result.html_body:
            result.html_body = _decode_payload(part)
        elif content_type == "text/plain" and not result.text_body:
            result.text_body = _decode_payload(part)

    return result


class Mailbox:
    """Read-only IMAP session over the statement mailbox."""

    def __init__(self, config: MailConfig, user: str, password: str) -> None:
        self.config = config
        self.user = user
        self.password = password
        self._connection: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "Mailbox":
        try:
            connection = imaplib.IMAP4_SSL(self.config.host, self.config.port)
            connection.login(self.user, self.password)
            # Read-only: a diagnostic scan must never mark statements as seen.
            status, _ = connection.select(self.config.folder, readonly=True)
        except imaplib.IMAP4.error as exc:
            raise MailboxError(
                f"메일 서버 로그인에 실패했습니다: {exc}\n"
                "Gmail은 계정 비밀번호가 아니라 앱 비밀번호를 요구합니다."
            ) from exc
        except OSError as exc:
            raise MailboxError(f"메일 서버에 접속하지 못했습니다: {exc}") from exc
        if status != "OK":
            raise MailboxError(f"메일함을 열지 못했습니다: {self.config.folder}")
        self._connection = connection
        return self

    def __exit__(self, *_exc_info: object) -> None:
        if not self._connection:
            return
        try:
            self._connection.close()
            self._connection.logout()
        except (imaplib.IMAP4.error, OSError):
            # The session is being torn down anyway; a noisy logout is not an error.
            pass
        finally:
            self._connection = None

    def _require(self) -> imaplib.IMAP4_SSL:
        if not self._connection:
            raise MailboxError("메일함이 열려 있지 않습니다. with 문 안에서 사용하세요.")
        return self._connection

    def search_uids(self, since: str | None = None) -> list[str]:
        """UIDs of mail from any configured sender.

        Only the sender and date are pushed to the server. Subject filtering
        happens in `matches_subject` after decoding, because IMAP SEARCH on a
        non-ASCII subject needs CHARSET negotiation that servers handle
        inconsistently — decoding locally is both simpler and more reliable.
        """
        connection = self._require()
        window = since if since is not None else self.config.since
        found: list[str] = []
        seen: set[str] = set()
        for sender in self.config.senders:
            criteria = ["FROM", f'"{sender}"']
            if window:
                criteria += ["SINCE", _imap_date(window)]
            status, data = connection.uid("SEARCH", None, *criteria)
            if status != "OK":
                raise MailboxError(f"메일 검색에 실패했습니다 (발신자 {sender}): {status}")
            for uid in (data[0] or b"").split():
                text = uid.decode("ascii")
                if text not in seen:
                    seen.add(text)
                    found.append(text)
        return sorted(found, key=int)

    def fetch(self, uid: str) -> MailMessage:
        connection = self._require()
        status, data = connection.uid("FETCH", uid, "(RFC822)")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            raise MailboxError(f"메일을 가져오지 못했습니다: uid={uid}")
        return parse_message(uid, data[0][1])

    def matches_subject(self, message: MailMessage) -> bool:
        """Whether the decoded subject carries any configured keyword."""
        if not self.config.subject_keywords:
            return True
        subject = message.subject.replace(" ", "")
        return any(keyword.replace(" ", "") in subject for keyword in self.config.subject_keywords)


def parse_mail_date(value: str) -> datetime | None:
    """Best-effort parse of an RFC 2822 Date header."""
    try:
        return email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
