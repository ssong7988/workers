"""URL routing.

The report and the admin both live under one unguessable path prefix, and the
scanner's API lives under `/api/` behind a bearer token. Everything else 404s.
The prefix matters: this site is published to the internet through Tailscale
Funnel, so a plain `/admin/` would put a login form on a public address.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from report import views

_PRIVATE = f"r/{settings.REPORT_PATH_TOKEN}/"

urlpatterns = [
    path("api/", include("api.urls")),
    path(_PRIVATE, views.index, name="report-index"),
    path(f"{_PRIVATE}stats/", views.stats, name="report-stats"),
    # Operations, not a public screen: the schedule's state says when the
    # machine is idle and what failed, so this one needs an admin login on top
    # of the path token.
    path(f"{_PRIVATE}airflow/", views.airflow, name="report-airflow"),
    # Dagster runs the schedule for now (Airflow above stays parked - see
    # PROJECT_STATE.md); same admin-login requirement and reasoning.
    path(f"{_PRIVATE}dagster/", views.dagster, name="report-dagster"),
    path(f"{_PRIVATE}admin/", admin.site.urls),
]

admin.site.site_header = "관심 매물"
admin.site.site_title = "관심 매물"
admin.site.index_title = "검색 조건과 수집 결과"
