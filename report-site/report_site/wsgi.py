"""WSGI entry point used by waitress (`run-site.ps1`)."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "report_site.settings")

application = get_wsgi_application()
