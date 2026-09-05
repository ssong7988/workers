"""Django settings for the property report application.

This site is the application, not a view onto someone else's files. It keeps
every scraped listing in PostgreSQL, owns the search conditions, decides which
listings match and which are urgent or new, renders the public report, and
builds and sends the KakaoTalk card. `real-estate-finder/` only collects and
posts what it scraped to the API here.

Configuration comes from `report-site/.env` and is never committed:

* `REPORT_PATH_TOKEN` - optional leading path segment. Empty uses the explicit
  namespaces `/property/`, `/stock/` and `/common/`; a value prepends
  `/<TOKEN>` to all three.
* `FINDER_API_TOKEN` - the bearer token `real-estate-finder` sends. The site is
  published to the internet through Tailscale Funnel, so `/api/` is reachable
  from outside and must not be open.
* `STOCK_API_TOKEN` - the same for the KB stock importer's `/stock/api/`.

See `.docs/RUNBOOK.md` for how this is run and tunneled.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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


REPORT_PATH_TOKEN = os.environ.get("REPORT_PATH_TOKEN", "").strip().strip("/")
if "/" in REPORT_PATH_TOKEN or "\\" in REPORT_PATH_TOKEN:
    raise RuntimeError("REPORT_PATH_TOKEN에는 경로 구분자를 사용할 수 없습니다.")
ROUTE_PREFIX = f"{REPORT_PATH_TOKEN}/" if REPORT_PATH_TOKEN else ""
PROPERTY_ROUTE_PREFIX = f"{ROUTE_PREFIX}property/"
STOCK_ROUTE_PREFIX = f"{ROUTE_PREFIX}stock/"
COMMON_ROUTE_PREFIX = f"{ROUTE_PREFIX}common/"
REPORT_URL_PATH = f"/{PROPERTY_ROUTE_PREFIX}report"
STATISTICS_URL_PATH = f"/{PROPERTY_ROUTE_PREFIX}statistics"
ALLOCATION_URL_PATH = f"/{STOCK_ROUTE_PREFIX}allocation"
PERFORMANCE_URL_PATH = f"/{STOCK_ROUTE_PREFIX}performance"
DAGSTER_SUMMARY_PATH = f"/{COMMON_ROUTE_PREFIX}dagster"
DAGSTER_PATH_PREFIX = f"{DAGSTER_SUMMARY_PATH}/console"
# The scanner authenticates with `Authorization: Bearer <FINDER_API_TOKEN>`.
FINDER_API_TOKEN = _required("FINDER_API_TOKEN", "<추측 불가 문자열>")
# The stock importer carries its own token so one leaked collector does not
# open the other domain. Optional on purpose: an install that has not started
# collecting KB data yet should not fail to boot, and `/stock/api/` answers
# 503 until it is set rather than degrading into an open endpoint.
STOCK_API_TOKEN = os.environ.get("STOCK_API_TOKEN", "").strip()

# Where the Kakao card links to. Falls back to the local address only so a
# misconfigured setup fails visibly rather than sending a broken link; the
# card's live check refuses to attach a loopback URL anyway.
REPORT_PUBLIC_URL = os.environ.get("KAKAO_REPORT_URL", "").strip()
# The statistics screen is a sibling of `/property/report/`, not a child of it. Reuse
# the configured public origin and replace only the path so host changes stay
# in one environment variable.
if REPORT_PUBLIC_URL:
    _public_parts = urlsplit(REPORT_PUBLIC_URL)
    REPORT_STATS_URL = urlunsplit(
        (_public_parts.scheme, _public_parts.netloc, f"{STATISTICS_URL_PATH}/", "", "")
    )
    STOCK_ALLOCATION_URL = urlunsplit(
        (_public_parts.scheme, _public_parts.netloc, f"{ALLOCATION_URL_PATH}/", "", "")
    )
    STOCK_PERFORMANCE_URL = urlunsplit(
        (_public_parts.scheme, _public_parts.netloc, f"{PERFORMANCE_URL_PATH}/", "", "")
    )
else:
    REPORT_STATS_URL = ""
    STOCK_ALLOCATION_URL = ""
    STOCK_PERFORMANCE_URL = ""

# Airflow runs the schedule from WSL2 and drives this machine through interop.
# Django only reads its status for the operations screen, so every value here
# is optional: unset simply means the screen says it is not configured yet.
AIRFLOW_API_URL = os.environ.get("AIRFLOW_API_URL", "").strip()
AIRFLOW_USERNAME = os.environ.get("AIRFLOW_USERNAME", "").strip()
AIRFLOW_PASSWORD = os.environ.get("AIRFLOW_PASSWORD", "").strip()
AIRFLOW_API_TOKEN = os.environ.get("AIRFLOW_API_TOKEN", "").strip()
try:
    AIRFLOW_TIMEOUT_SECONDS = float(os.environ.get("AIRFLOW_TIMEOUT_SECONDS", "5"))
except ValueError:
    AIRFLOW_TIMEOUT_SECONDS = 5.0

# Dagster (dagster_project/, its own venv) drives the schedule natively on
# this machine while the Airflow/WSL2 plan above stays parked - see
# .agent/PROJECT_STATE.md, "Active Work: Dagster로 스케줄 구동". Unlike
# Airflow's, this address has one predictable local default: `dagster dev`
# always binds 127.0.0.1:3000 below the same optional route prefix the way
# run-dagster.ps1 starts it, so no second secret or .env entry is required.
DAGSTER_GRAPHQL_URL = os.environ.get(
    "DAGSTER_GRAPHQL_URL",
    f"http://127.0.0.1:3000{DAGSTER_PATH_PREFIX}/graphql",
).strip()
try:
    DAGSTER_TIMEOUT_SECONDS = float(os.environ.get("DAGSTER_TIMEOUT_SECONDS", "5"))
except ValueError:
    DAGSTER_TIMEOUT_SECONDS = 5.0

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

# DEBUG=False mutes Django's default console handler for the `django` logger
# (see require_debug_true) and routes 5xx to AdminEmailHandler, which is a
# silent no-op with no email backend configured - so without this, an
# unhandled view exception leaves no trace anywhere. Send it to stdout
# instead: every run-*.ps1 already wraps stdout in Start-Transcript
# (start-logging.ps1), so this lands in .logs/report-site/<date>.log with no
# separate file handler needed here. A file handler here would collide with
# manage.py commands (send_digest, scan_status, ...) that load these same
# settings as short-lived separate processes and would fight over one file.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "timestamped": {
            "format": "{asctime} {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "timestamped",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "api",
    "properties",
    "portfolio",
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
