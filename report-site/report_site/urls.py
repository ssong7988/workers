"""URL routing.

Property screens live below `/property/`, financial-asset screens below
`/stock/`, and shared operations below `/common/`. An optional token can be
prepended to all three namespaces, while each collector's API stays outside
them behind its own bearer token.

Django admin sits at the root (`/admin/`, or `/<TOKEN>/admin/`) instead of
inside a namespace: it owns every model of both services, so hanging it off one
of them made the other's tables look like guests. The old namespaced addresses
stay as redirects so saved bookmarks keep working.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from report import spending_views, stock_views, views

_ROUTE_PREFIX = settings.ROUTE_PREFIX
_PROPERTY_PREFIX = settings.PROPERTY_ROUTE_PREFIX
_STOCK_PREFIX = settings.STOCK_ROUTE_PREFIX
_COMMON_PREFIX = settings.COMMON_ROUTE_PREFIX
_SPENDING_PREFIX = settings.SPENDING_ROUTE_PREFIX

# When a path token is configured, the public root explains the services but
# does not disclose protected destinations. The linked directory lives at the
# token root. With today's empty token, `/` is the complete linked directory.
if _ROUTE_PREFIX:
    _landing_patterns = [
        path("", views.landing, {"show_links": False}, name="site-home-public"),
        path(_ROUTE_PREFIX, views.landing, name="site-home"),
    ]
else:
    _landing_patterns = [path("", views.landing, name="site-home")]

urlpatterns = _landing_patterns + [
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
    # 카드 소비. 두 화면이고 카카오 버튼 두 개가 각각 이 주소로 간다. 가맹점
    # 하나하나가 그대로 보이는 화면이라 경로 토큰만으로는 부족하고, 두 화면
    # 모두 admin 로그인을 요구한다.
    path(f"{_SPENDING_PREFIX}api/", include("spending.api_urls")),
    path(
        f"{_SPENDING_PREFIX}report/", spending_views.report, name="spending-report"
    ),
    path(
        f"{_SPENDING_PREFIX}transactions/",
        spending_views.transactions,
        name="spending-transactions",
    ),
    # admin은 한 벌이고 두 서비스의 모델을 모두 들고 있다. 그래서 namespace
    # 안이 아니라 뿌리에 둔다. 토큰을 채우면 `/<TOKEN>/admin/`이다.
    path(f"{_ROUTE_PREFIX}admin/", admin.site.urls),
    # 옛 주소 둘은 리다이렉트로 남긴다. `admin.site.urls`를 두 번 마운트하면
    # `admin:` URL namespace가 갈라지므로 마운트가 아니라 리다이렉트다.
    path(
        f"{_PROPERTY_PREFIX}admin/",
        RedirectView.as_view(url=f"/{_ROUTE_PREFIX}admin/", permanent=False),
    ),
    path(
        f"{_STOCK_PREFIX}admin/",
        RedirectView.as_view(url=f"/{_ROUTE_PREFIX}admin/", permanent=False),
    ),
]

admin.site.site_header = "관심 매물 · 금융자산"
admin.site.site_title = "관심 매물 · 금융자산"
admin.site.index_title = "검색 조건과 수집 결과, 계좌와 자산분류"
