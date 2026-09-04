"""URL routing.

The public screens have explicit top-level names. An optional token can be
prepended to every non-API route, while the scanner API stays at `/api/` behind
a bearer token.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from report import views

_PREFIX = settings.ROUTE_PREFIX

urlpatterns = [
    path("api/", include("api.urls")),
    path(f"{_PREFIX}report/", views.index, name="report-index"),
    path(f"{_PREFIX}statistics/", views.stats, name="report-stats"),
    # Operations, not a public screen: the schedule's state says when the
    # machine is idle and what failed, so this one needs an admin login on top
    # of the path token.
    path(f"{_PREFIX}airflow/", views.airflow, name="report-airflow"),
    # Dagster runs the schedule for now (Airflow above stays parked - see
    # PROJECT_STATE.md); same admin-login requirement and reasoning.
    # Django owns the concise summary. The native UI is mounted by Funnel one
    # level deeper at /dagster/console/, so the routes no longer conflict.
    path(f"{_PREFIX}dagster/", views.dagster, name="report-dagster"),
    path(f"{_PREFIX}admin/", admin.site.urls),
]

admin.site.site_header = "관심 매물"
admin.site.site_title = "관심 매물"
admin.site.index_title = "검색 조건과 수집 결과"
