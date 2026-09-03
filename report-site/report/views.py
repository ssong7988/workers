"""Render the property report straight from `real_estate_finder`'s saved state.

Every request re-reads `data/state.json` — the same file `send-digest` reads
— so the page always reflects the last successful scan. There is no build or
deploy step in between; a page refresh is enough.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.http import HttpResponse
from django.shortcuts import render

from real_estate_finder.config import load_config
from real_estate_finder.models import Listing
from real_estate_finder.report import build_report_payload
from real_estate_finder.storage import FileStore

FINDER_DIR = Path(__file__).resolve().parent.parent.parent / "real-estate-finder"

_store = FileStore(FINDER_DIR / "data")

_local_config = FINDER_DIR / "config" / "searches.local.yaml"
_config_path = _local_config if _local_config.exists() else FINDER_DIR / "config" / "searches.yaml"
_config = load_config(_config_path)


def _load_state_with_retry(store: FileStore, attempts: int = 3, delay: float = 0.05) -> dict:
    """`save_state()` swaps the file in with `os.replace`, which can briefly
    race an open handle on Windows. Retry rather than 500 on a scan in
    progress."""
    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            return store.load_state()
        except OSError as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def _display_time(observed_at: str | None) -> str:
    if not observed_at:
        return "기록 없음"
    try:
        moment = datetime.fromisoformat(observed_at).astimezone(ZoneInfo("Asia/Seoul"))
    except ValueError:
        return observed_at
    return moment.strftime("%Y.%m.%d %H:%M")


def index(request) -> HttpResponse:
    state = _load_state_with_retry(_store)
    listings = [
        Listing.from_dict(payload)
        for payload in state.get("listings", {}).values()
        if payload.get("active")
    ]
    observed_at = (
        max((listing.observed_at for listing in listings), default=None)
        or state.get("last_successful_scan")
    )
    complexes = (
        build_report_payload(listings, _config, observed_at=observed_at or "")["complexes"]
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
            "observed_at": observed_at or "",
            "observed_at_display": _display_time(observed_at),
            "complexes": complexes,
            "total": total,
            "urgent": urgent,
        },
    )
    response["Cache-Control"] = "no-store"
    return response
