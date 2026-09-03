"""URL routing: the report lives at one unguessable path, nothing else does."""

from __future__ import annotations

from django.conf import settings
from django.urls import path

from report import views

urlpatterns = [
    path(f"r/{settings.REPORT_PATH_TOKEN}/", views.index, name="report-index"),
]
