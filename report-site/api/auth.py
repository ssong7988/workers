"""Bearer authentication for the collector-only JSON APIs.

Two collectors post here now - `real-estate-finder/` and the stock importer -
and they carry different tokens, so the decorator takes the settings name of
the token it should compare against.
"""

from __future__ import annotations

from functools import wraps
from secrets import compare_digest
from typing import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse


ApiView = Callable[..., HttpResponse]


def bearer_required_for(setting_name: str) -> Callable[[ApiView], ApiView]:
    """Build a decorator checking `Authorization` against one settings value."""

    def decorate(view: ApiView) -> ApiView:
        @wraps(view)
        def wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            expected = getattr(settings, setting_name, "")
            if not expected:
                # An unset token must not degrade into an open endpoint.
                return JsonResponse(
                    {
                        "error": f"{setting_name}이(가) 설정되지 않았습니다.",
                        "code": "token_not_configured",
                    },
                    status=503,
                )
            authorization = request.headers.get("Authorization", "")
            scheme, separator, token = authorization.partition(" ")
            valid = (
                bool(separator)
                and scheme.lower() == "bearer"
                and bool(token)
                and compare_digest(token, expected)
            )
            if not valid:
                response = JsonResponse(
                    {"error": "유효한 Bearer 토큰이 필요합니다.", "code": "unauthorized"},
                    status=401,
                )
                response["WWW-Authenticate"] = "Bearer"
                return response
            return view(request, *args, **kwargs)

        return wrapped

    return decorate


bearer_required = bearer_required_for("FINDER_API_TOKEN")
