"""Render the current property report directly from PostgreSQL."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from properties.models import GlobalRule, Listing, Scan, SearchCondition
from properties.report import build_report_payload


def _local_iso(moment: datetime | None, timezone_name: str) -> str:
    if moment is None:
        return ""
    return timezone.localtime(moment, ZoneInfo(timezone_name)).isoformat()


def _display_time(moment: datetime | None, timezone_name: str) -> str:
    if moment is None:
        return "기록 없음"
    return timezone.localtime(moment, ZoneInfo(timezone_name)).strftime(
        "%Y.%m.%d %H:%M"
    )


def index(request) -> HttpResponse:
    rule = GlobalRule.objects.filter(pk=1).first()
    timezone_name = rule.timezone if rule else settings.TIME_ZONE
    conditions = list(
        SearchCondition.objects.filter(enabled=True).order_by("created_at", "id")
    )
    listings = list(
        Listing.objects.filter(active=True, condition__enabled=True).select_related(
            "condition"
        )
    )
    observed_moment = max(
        (listing.observed_at for listing in listings),
        default=None,
    )
    if observed_moment is None:
        latest_scan = (
            Scan.objects.exclude(successful_conditions=[])
            .order_by("-started_at")
            .only("started_at", "finished_at")
            .first()
        )
        if latest_scan is not None:
            observed_moment = latest_scan.finished_at or latest_scan.started_at
    observed_at = _local_iso(observed_moment, timezone_name)
    complexes = (
        build_report_payload(listings, conditions, observed_at=observed_at)["complexes"]
        if listings
        else []
    )
    total = sum(len(item["listings"]) for item in complexes)
    urgent = [
        {"complex": item["name"], **listing}
        for item in complexes
        for listing in item["listings"]
        if listing["urgent"]
    ]

    response = render(
        request,
        "report/index.html",
        {
            "observed_at": observed_at,
            "observed_at_display": _display_time(observed_moment, timezone_name),
            "complexes": complexes,
            "total": total,
            "urgent": urgent,
        },
    )
    response["Cache-Control"] = "no-store"
    return response
