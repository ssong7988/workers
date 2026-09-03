"""Django settings for the property report application.

This site is the application, not a view onto someone else's files. It keeps
every scraped listing in PostgreSQL, owns the search conditions, decides which
listings match and which are urgent or new, renders the public report, and
builds and sends the KakaoTalk card. `real-estate-finder/` only collects and
posts what it scraped to the API here.

Two secrets gate it, both from `report-site/.env` and neither in Git:

* `REPORT_PATH_TOKEN` - the unguessable path the public report (and the admin)
  live under. There is no login on the report itself, because everything behind
  it is the same listing data already sent to KakaoTalk.
* `FINDER_API_TOKEN` - the bearer token `real-estate-finder` sends. The site is
  published to the internet through Tailscale Funnel, so `/api/` is reachable
  from outside and must not be open.

See `.agent/docs/RUNBOOK.md` for how this is run and tunneled.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent


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
# The public report URL lives in the repo-root .env, shared with the scanner
# through load-env.ps1. Kakao card delivery moved here, so Django needs it too.
_load_env(ROOT_DIR / ".env")


def _required(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name}이(가) 설정되지 않았습니다. {BASE_DIR / '.env'}에 {name}={hint}을(를) 추가하세요."
        )
    return value


REPORT_PATH_TOKEN = _required("REPORT_PATH_TOKEN", "<추측 불가 문자열>")
# The scanner authenticates with `Authorization: Bearer <FINDER_API_TOKEN>`.
FINDER_API_TOKEN = _required("FINDER_API_TOKEN", "<추측 불가 문자열>")

# Where the Kakao card links to. Falls back to the local address only so a
# misconfigured setup fails visibly rather than sending a broken link; the
# card's live check refuses to attach a loopback URL anyway.
REPORT_PUBLIC_URL = os.environ.get("KAKAO_REPORT_URL", "").strip()
# The statistics screen sits beside the report under the same token prefix, so
# the second Kakao button is the report URL plus one segment.
REPORT_STATS_URL = (
    f"{REPORT_PUBLIC_URL.rstrip('/')}/stats/" if REPORT_PUBLIC_URL else ""
)

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "django-insecure-report-site-local-only-not-public"
)
DEBUG = False
# Tailscale Funnel hostnames are `<pc>.<tailnet>.ts.net`; 127.0.0.1/localhost
# are for local checks before the tunnel is up.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", ".ts.net"]
# Admin login posts a form, and Django checks the Origin against this list on
# HTTPS. Funnel terminates TLS and forwards the original scheme.
CSRF_TRUSTED_ORIGINS = ["https://*.ts.net"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "api",
    "properties",
    "report",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the admin's own CSS/JS: waitress does not serve static files and
    # this never runs with DEBUG on.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "report_site.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "report_site.wsgi.application"

# PostgreSQL only. Everything but the password has a working local default, so
# `.env` normally carries just POSTGRES_PASSWORD.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "property_report"),
        "USER": os.environ.get("POSTGRES_USER", "property_report"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Compressed, but not manifest-hashed: a missing file should not take the
    # whole report down over the admin's stylesheet.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Card images and other generated artifacts. Git-ignored.
DATA_DIR = BASE_DIR / "data"

USE_TZ = True
TIME_ZONE = "Asia/Seoul"
LANGUAGE_CODE = "ko"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
