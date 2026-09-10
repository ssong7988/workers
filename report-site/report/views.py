"""Render the current property report directly from PostgreSQL."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from properties.models import GlobalRule, Listing, Scan, SearchCondition
from properties.report import build_report_payload
from properties.statistics import (
    build_chart,
    collect_series,
    eok_text,
    summarize_period,
    table_rows,
)

from .airflow_client import fetch_status as fetch_airflow_status
from .dagster_client import JOBS as DAGSTER_JOBS
from .dagster_client import fetch_status as fetch_dagster_status
from .stats_params import resolve_range, resolve_scope


def landing(request, *, show_links: bool = True) -> HttpResponse:
    """Render the public service directory without touching the database."""
    sections = [
        {
            "index": "01",
            "namespace": "common",
            "name": "공통 운영",
            "description": "부동산과 금융자산 수집 작업의 일정과 최근 실행 상태를 확인합니다.",
            "tone": "common",
            "links": [
                {
                    "label": "운영 현황",
                    "path": reverse("report-dagster"),
                    "note": "관리자 로그인",
                }
            ],
        },
        {
            "index": "02",
            "namespace": "spending",
            "name": "소비 분석",
            "description": "카드 명세서를 읽어 대분류별 구성과 가맹점을 보고, 매달 요약을 카카오톡으로 받습니다.",
            "tone": "spending",
            "links": [
                {
                    "label": "소비 리포트",
                    "path": reverse("spending-report"),
                    "note": "관리자 로그인",
                },
                {
                    "label": "전체 거래",
                    "path": reverse("spending-transactions"),
                    "note": "관리자 로그인",
                },
            ],
        },
        {
            "index": "03",
            "namespace": "property",
            "name": "부동산",
            "description": "관심 단지의 조건 충족 매물과 급매, 지역·단지별 호가 추이를 살펴봅니다.",
            "tone": "property",
            "links": [
                {"label": "매물 리포트", "path": reverse("report-index")},
                {"label": "가격 통계", "path": reverse("report-stats")},
            ],
        },
        {
            "index": "04",
            "namespace": "stock",
            "name": "금융자산",
            "description": "자산 비중과 목표 대비 리밸런싱, 기간별 수익률과 낙폭을 확인합니다.",
            "tone": "stock",
            "links": [
                {
                    "label": "비중·리밸런싱",
                    "path": reverse("stock-allocation"),
                    "note": "관리자 로그인",
                },
                {
                    "label": "수익률·MDD",
                    "path": reverse("stock-performance"),
                    "note": "관리자 로그인",
                },
            ],
        },
    ]
    response = render(
        request,
        "report/landing.html",
        {"sections": sections, "show_links": show_links},
    )
    response["Cache-Control"] = "no-store"
    return response


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


def _timezone_name() -> str:
    rule = GlobalRule.objects.filter(pk=1).only("timezone").first()
    return rule.timezone if rule else settings.TIME_ZONE


def _grouped_conditions(
    conditions: list[SearchCondition], region: str
) -> list[tuple[str, list[SearchCondition]]]:
    """Group conditions into (region, items) pairs, scoped to one region.

    An empty `region` means "every region" (unfiltered), matching how the
    지역 select's "전체 지역" option resolves to `scope.region == ""`.
    """
    scoped = [c for c in conditions if c.region == region] if region else conditions
    regions = [r for r in dict.fromkeys(c.region for c in scoped) if r]
    grouped = [(r, [c for c in scoped if c.region == r]) for r in regions]
    unassigned = [c for c in scoped if not c.region]
    if unassigned:
        grouped.append(("지역 미지정", unassigned))
    return grouped


def index(request) -> HttpResponse:
    rule = GlobalRule.objects.filter(pk=1).first()
    timezone_name = rule.timezone if rule else settings.TIME_ZONE
    conditions = list(
        SearchCondition.objects.filter(enabled=True).order_by("created_at", "id")
    )

    scope = resolve_scope(request.GET, conditions, default_region="")
    if scope.condition_id:
        conditions = [c for c in conditions if c.pk == scope.condition_id]
    elif scope.region:
        conditions = [c for c in conditions if c.region == scope.region]

    listings_qs = Listing.objects.filter(
        active=True, condition__enabled=True, duplicate_of__isnull=True
    ).select_related("condition")
    if scope.condition_id:
        listings_qs = listings_qs.filter(condition_id=scope.condition_id)
    elif scope.region:
        listings_qs = listings_qs.filter(condition__region=scope.region)
    listings = list(listings_qs)

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

    all_conditions = list(
        SearchCondition.objects.filter(enabled=True).order_by("region", "name")
    )
    regions = [
        region for region in dict.fromkeys(c.region for c in all_conditions) if region
    ]
    grouped = _grouped_conditions(all_conditions, scope.region)

    response = render(
        request,
        "report/index.html",
        {
            "observed_at": observed_at,
            "observed_at_display": _display_time(observed_moment, timezone_name),
            "complexes": complexes,
            "total": total,
            "urgent": urgent,
            "scope": scope,
            "selected_region": scope.region or "all",
            "regions": regions,
            "grouped_conditions": grouped,
        },
    )
    response["Cache-Control"] = "no-store"
    return response


def stats(request) -> HttpResponse:
    """Daily asking-price distributions for a date range and a region or complex."""
    timezone_name = _timezone_name()
    today = timezone.localtime(timezone.now(), ZoneInfo(timezone_name)).date()
    conditions = list(
        SearchCondition.objects.filter(enabled=True).order_by("region", "name")
    )

    date_range = resolve_range(request.GET, today)
    scope = resolve_scope(request.GET, conditions)
    series = collect_series(
        start_day=date_range.start,
        end_day=date_range.end,
        region=scope.region,
        condition_id=scope.condition_id,
        timezone_name=timezone_name,
    )
    period = summarize_period(series)

    regions = [
        region for region in dict.fromkeys(c.region for c in conditions) if region
    ]
    grouped = _grouped_conditions(conditions, scope.region)

    response = render(
        request,
        "report/stats.html",
        {
            "range": date_range,
            "scope": scope,
            "selected_region": scope.region or "all",
            "regions": regions,
            "grouped_conditions": grouped,
            "chart": build_chart(series),
            "rows": table_rows(series),
            "period": period,
            "period_min": eok_text(period.minimum) if period.samples else "-",
            "period_max": eok_text(period.maximum) if period.samples else "-",
            "latest_mean": eok_text(period.latest.mean) if period.latest else "-",
            "report_url": reverse("report-index"),
        },
    )
    response["Cache-Control"] = "no-store"
    return response


@staff_member_required
def airflow(request) -> HttpResponse:
    """Show what the Airflow schedule has been doing, for operators only.

    Read-only, and it never 500s on Airflow's account: when the scheduler is
    down the point of this page is to say so, which a stack trace does not.
    """
    status = fetch_airflow_status()
    timezone_name = _timezone_name()
    latest_scan = Scan.objects.order_by("-started_at").first()

    response = render(
        request,
        "report/airflow.html",
        {
            "status": status,
            "failed_runs": status.failed_runs,
            "latest_scan_at": _display_time(
                latest_scan.started_at if latest_scan else None, timezone_name
            ),
            "report_url": reverse("report-index"),
            "stats_url": reverse("report-stats"),
        },
    )
    response["Cache-Control"] = "no-store"
    return response


@staff_member_required
def dagster(request) -> HttpResponse:
    """Show what the Dagster schedule has been doing, for operators only.

    Read-only, and it never 500s on Dagster's account: when the scheduler is
    down the point of this page is to say so, which a stack trace does not.
    Dagster drives the schedule for now; Airflow's equivalent screen at
    r[/<TOKEN>]/property/airflow/ stays in place but parked (see PROJECT_STATE.md).
    """
    status = fetch_dagster_status()
    timezone_name = _timezone_name()
    latest_scan = Scan.objects.order_by("-started_at").first()

    response = render(
        request,
        "report/dagster.html",
        {
            "status": status,
            "jobs": DAGSTER_JOBS,
            "failed_runs": status.failed_runs,
            "latest_scan_at": _display_time(
                latest_scan.started_at if latest_scan else None, timezone_name
            ),
            "report_url": reverse("report-index"),
            "stats_url": reverse("report-stats"),
            "home_url": reverse("site-home"),
            "dagster_runs_url": f"{settings.DAGSTER_PATH_PREFIX}/runs",
        },
    )
    response["Cache-Control"] = "no-store"
    return response
