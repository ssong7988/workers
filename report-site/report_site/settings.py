"""Minimal Django settings for the property report site.

Reads `real-estate-finder/data/state.json` on every request via the `report`
app; there is no database, no admin, no sessions. The report is exposed at a
single unguessable path (`REPORT_PATH_TOKEN`) rather than requiring a login,
because the only thing behind it is the same listing data already sent to
KakaoTalk. See `.agent/docs/RUNBOOK.md` for how this is run and tunneled.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
FINDER_DIR = ROOT_DIR / "real-estate-finder"

# Make `real_estate_finder` importable so the report reuses its models,
# storage, and price/area formatting instead of re-implementing them here.
if str(FINDER_DIR) not in sys.path:
    sys.path.insert(0, str(FINDER_DIR))


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env(BASE_DIR / ".env")

REPORT_PATH_TOKEN = os.environ.get("REPORT_PATH_TOKEN", "").strip()
if not REPORT_PATH_TOKEN:
    raise RuntimeError(
        "REPORT_PATH_TOKEN이 설정되지 않았습니다. "
        f"{BASE_DIR / '.env'}에 REPORT_PATH_TOKEN=<추측 불가 문자열>을 추가하세요."
    )

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "django-insecure-report-site-local-only-not-public"
)
DEBUG = False
# Tailscale Funnel hostnames are `<pc>.<tailnet>.ts.net`; 127.0.0.1/localhost
# are for local checks before the tunnel is up.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", ".ts.net"]

INSTALLED_APPS = ["report"]
MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "report_site.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]
WSGI_APPLICATION = "report_site.wsgi.application"

# No models, no migrations, no database file.
DATABASES = {}

USE_TZ = True
TIME_ZONE = "Asia/Seoul"
LANGUAGE_CODE = "ko"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
