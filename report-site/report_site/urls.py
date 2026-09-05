"""URL routing.

Property screens live below `/property/`, financial-asset screens below
`/stock/`, and shared operations below `/common/`. An optional token can be
prepended to all three namespaces, while each collector's API stays outside
them behind its own bearer token.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from report import stock_views, views

_PROPERTY_PREFIX = settings.PROPERTY_ROUTE_PREFIX
_STOCK_PREFIX = settings.STOCK_ROUTE_PREFIX
_COMMON_PREFIX = settings.COMMON_ROUTE_PREFIX
urlpatterns = [
    path("api/", include("api.urls")),
    path(f"{_STOCK_PREFIX}api/", include("portfolio.api_urls")),
    path(f"{_PROPERTY_PREFIX}report/", views.index, name="report-index"),
    path(f"{_PROPERTY_PREFIX}statistics/", views.stats, name="report-stats"),
    # Operations, not a public screen: the schedule's state says when the
    # machine is idle and what failed, so this one needs an admin login on top
    # of the path token.
    path(f"{_PROPERTY_PREFIX}airflow/", views.airflow, name="report-airflow"),
    # Dagster runs the schedule for now (Airflow above stays parked - see
    # PROJECT_STATE.md); same admin-login requirement and reasoning.
    # Django owns the concise summary. The native UI is mounted by Funnel one
    # level deeper at /common/dagster/console/, so the routes do not conflict.
    path(f"{_COMMON_PREFIX}dagster/", views.dagster, name="report-dagster"),
    # 금융자산. 비중·리밸런싱과 수익률·MDD 두 화면이고, 카카오 버튼 두 개가
    # 각각 이 주소로 간다.
    path(
        f"{_STOCK_PREFIX}allocation/", stock_views.allocation, name="stock-allocation"
    ),
    path(
        f"{_STOCK_PREFIX}performance/",
        stock_views.performance,
        name="stock-performance",
    ),
    path(f"{_PROPERTY_PREFIX}admin/", admin.site.urls),
    # admin은 한 벌이다. 계획서의 `/stock/admin/`은 같은 화면을 가리키는
    # 편의 주소로 두고, `admin:` URL namespace가 둘로 갈라지지 않게 한다.
    path(
        f"{_STOCK_PREFIX}admin/",
        RedirectView.as_view(url=f"/{_PROPERTY_PREFIX}admin/", permanent=False),
    ),
]

admin.site.site_header = "관심 매물 · 금융자산"
admin.site.site_title = "관심 매물 · 금융자산"
admin.site.index_title = "검색 조건과 수집 결과, 계좌와 자산분류"
