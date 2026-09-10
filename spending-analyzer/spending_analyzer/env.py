"""Credential loading, reusing the shared `kakao-notifier` helper."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
KAKAO_DIR = ROOT_DIR / "kakao-notifier"


class MissingCredential(RuntimeError):
    """A required secret is not present in the environment."""


def _load_env_helper():
    """`kakao-notifier/common.py:load_env`, loaded the way notifier.py does it."""
    module_path = KAKAO_DIR / "common.py"
    spec = importlib.util.spec_from_file_location("project_kakao_common", module_path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(KAKAO_DIR))
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    finally:
        sys.path.pop(0)
    return getattr(module, "load_env", None)


def load_env(project_dir: Path) -> None:
    """Read the app's own .env, then the shared kakao-notifier one.

    `load_env` uses `setdefault`, so a real environment variable always wins
    and the first file read wins over the second.
    """
    helper = _load_env_helper()
    if helper is None:
        return
    for candidate in (project_dir / ".env", KAKAO_DIR / ".env"):
        if candidate.exists():
            helper(str(candidate))


def require(name: str, hint: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise MissingCredential(f"{name}가 설정되지 않았습니다.\n  {hint}")
    return value


def optional(name: str) -> str:
    return (os.environ.get(name) or "").strip()
