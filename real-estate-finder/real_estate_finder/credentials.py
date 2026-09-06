"""Naver sign-in credentials, read from .env.

The health check runs at 06:00 with nobody watching, so it has to be able to
sign in on its own rather than only warn about being signed out. That needs the
account password, and the one place this project keeps secrets is `.env` -
never the code, the documents, or a log.

Everything here is a pure function over a mapping and a list of paths, so it is
testable without a real `.env` and without ever printing a value.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, NamedTuple, Sequence

ROOT_DIR = Path(__file__).resolve().parents[2]
# The root file already holds the shared Kakao link; the collector's own .env is
# accepted too, for anyone who would rather keep browser credentials next to the
# collector. Both are in .gitignore.
ENV_FILES: tuple[Path, ...] = (ROOT_DIR / ".env", ROOT_DIR / "real-estate-finder" / ".env")
USERNAME_KEY = "NAVER_ID"
PASSWORD_KEY = "NAVER_PASSWORD"


class NaverCredentials(NamedTuple):
    username: str
    password: str

    def __repr__(self) -> str:
        """Keep the password out of tracebacks and repr-based logging."""
        return f"NaverCredentials(username={self.username!r}, password=<hidden>)"


def parse_env_file(text: str) -> dict[str, str]:
    """Read KEY=VALUE lines, stripping one layer of matching quotes.

    The API client's reader does not strip quotes because a URL never needs
    them. A password does: quoting is the only way to write one that starts or
    ends with a space, and `#` inside a quoted value is not a comment.
    """
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def naver_credentials(
    environ: Mapping[str, str] | None = None,
    env_files: Sequence[Path] | None = None,
) -> NaverCredentials | None:
    """Return the configured credentials, or None when they are not set.

    Absent credentials are not an error here: a person at a keyboard can still
    sign in by hand. Only the unattended path treats it as one.
    """
    environ = os.environ if environ is None else environ
    files = ENV_FILES if env_files is None else env_files

    username = (environ.get(USERNAME_KEY) or "").strip()
    password = environ.get(PASSWORD_KEY) or ""
    for path in files:
        if username and password:
            break
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            continue
        values = parse_env_file(text)
        username = username or values.get(USERNAME_KEY, "").strip()
        password = password or values.get(PASSWORD_KEY, "")

    if not username or not password:
        return None
    return NaverCredentials(username, password)
