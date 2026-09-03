"""Bearer authentication for the collector-only JSON API."""

from __future__ import annotations

from functools import wraps
from secrets import compare_digest
from typing import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse


ApiView = Callable[..., HttpResponse]


def bearer_required(view: ApiView) -> ApiView:
    @wraps(view)
    def wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        authorization = request.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        valid = (
            bool(separator)
            and scheme.lower() == "bearer"
            and bool(token)
            and compare_digest(token, settings.FINDER_API_TOKEN)
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
