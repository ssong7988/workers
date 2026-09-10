"""Open a VestMail secure-mail attachment and hand back the decrypted HTML.

삼성카드's e-statement does not arrive as a PDF. It is a self-decrypting HTML
file: the statement is encrypted inside the file and the page's own JavaScript
decrypts it in the browser once the reader types a password (생년월일 6자리 or
사업자번호 뒤 7자리). Nothing is fetched from the network — the file carries
everything — so this works offline.

The decryption runs in a real browser rather than being reimplemented in Python.
The vendor's routine is minified and obfuscated; reimplementing it would mean
re-reverse-engineering it every time VestMail ships an update, while driving the
page uses whatever algorithm the file itself carries. Statements arrive once a
month, so the browser's cost is irrelevant.

Microsoft Edge is driven directly, so no Playwright browser download is needed —
`real-estate-finder` already relies on Edge being present on this machine.
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# Browser channels to try, in order. Edge ships with Windows; Chrome is the
# fallback; the bundled Chromium is used only if someone ran `playwright install`.
CHANNELS = ("msedge", "chrome")

WRONG_PASSWORD_MARKERS = ("비밀번호", "password")
DECRYPT_TIMEOUT_MS = 20_000


class SecureMailError(RuntimeError):
    """The attachment could not be opened or decrypted."""


class WrongPassword(SecureMailError):
    """The statement password was rejected by the attachment itself."""


@dataclass
class DecryptedStatement:
    html: str  # the decrypted statement markup
    text: str  # its visible text, for locating sections
    source_name: str


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SecureMailError(
            "playwright가 없습니다. `pip install -r requirements.txt`를 실행하세요."
        ) from exc
    return sync_playwright


def _launch(playwright):
    """Use an installed browser; fall back to a downloaded one."""
    errors = []
    for channel in CHANNELS:
        try:
            return playwright.chromium.launch(channel=channel, headless=True)
        except Exception as exc:
            errors.append(f"{channel}: {type(exc).__name__}")
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        raise SecureMailError(
            "브라우저를 실행하지 못했습니다. Edge 또는 Chrome이 필요합니다.\n"
            f"  시도: {', '.join(errors)}, chromium: {type(exc).__name__}\n"
            "  둘 다 없다면 `python -m playwright install chromium`을 실행하세요."
        ) from exc


@contextmanager
def open_decrypted(content: bytes, password: str, *, source_name: str = "") -> Iterator:
    """Open an attachment, unlock it, and hand back the live page.

    The page stays open for the caller because the statement's detail list
    renders ten rows at a time behind a 더보기 control — reading a static
    snapshot would capture only the first page.
    """
    if not password:
        raise SecureMailError(
            "명세서 비밀번호가 없습니다.\n"
            "  .env에 SAMSUNG_STATEMENT_PASSWORD를 넣으세요 (생년월일 6자리 또는 사업자번호 뒤 7자리)."
        )

    sync_playwright = _load_playwright()
    with tempfile.TemporaryDirectory() as directory:
        # A file:// URL is required — the page's script will not run from a data: URL.
        target = Path(directory) / "statement.html"
        target.write_bytes(content)

        with sync_playwright() as playwright:
            browser = _launch(playwright)
            try:
                page = browser.new_page(viewport={"width": 1000, "height": 1400})
                dialogs: list[str] = []
                page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.accept()))
                page.goto(target.as_uri())

                try:
                    page.wait_for_selector("#password", timeout=DECRYPT_TIMEOUT_MS)
                except Exception as exc:
                    raise SecureMailError(
                        f"비밀번호 입력칸을 찾지 못했습니다: {source_name or '첨부'}\n"
                        "  VestMail 보안메일 형식이 아닐 수 있습니다."
                    ) from exc

                page.fill("#password", password)
                page.click("#confirm")
                page.wait_for_timeout(3_000)

                for message in dialogs:
                    if any(marker in message for marker in WRONG_PASSWORD_MARKERS):
                        raise WrongPassword(
                            f"명세서가 비밀번호를 거부했습니다: {message}\n"
                            "  .env의 SAMSUNG_STATEMENT_PASSWORD를 확인하세요 "
                            "(생년월일 6자리, 예: 900101)."
                        )

                if page.evaluate("() => document.body.textContent.length") < 2_000:
                    raise SecureMailError(
                        "복호화 후에도 내용이 비어 있습니다. 비밀번호가 맞는지 확인하세요."
                    )
                yield page
            finally:
                browser.close()


def decrypt(content: bytes, password: str, *, source_name: str = "") -> DecryptedStatement:
    """Decrypt one attachment and return the statement markup it reveals."""
    with open_decrypted(content, password, source_name=source_name) as page:
        frame = _statement_frame(page)
        return DecryptedStatement(
            html=frame.content(),
            text=frame.inner_text("body"),
            source_name=source_name,
        )


def _statement_frame(page):
    """The frame holding the decrypted statement.

    VestMail renders the decrypted document into an iframe, but a version that
    replaces the page body would leave only the main frame — so pick the richest
    frame rather than assuming either shape.
    """
    candidates = []
    for frame in page.frames:
        try:
            text = frame.inner_text("body")
        except Exception:
            continue
        candidates.append((len(text), frame))
    if not candidates:
        raise SecureMailError("복호화된 내용을 읽지 못했습니다.")

    length, frame = max(candidates, key=lambda pair: pair[0])
    if length < 200:
        raise SecureMailError(
            "복호화 후에도 내용이 비어 있습니다. 비밀번호가 맞는지 확인하세요."
        )
    return frame
