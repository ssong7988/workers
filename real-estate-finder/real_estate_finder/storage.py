"""Atomic local storage designed behind a future PostgreSQL-compatible interface."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import Listing, ScanResult


class FileStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.state_path = data_dir / "state.json"
        self.observations_path = data_dir / "observations.jsonl"
        self.runs_path = data_dir / "scan-runs.jsonl"
        self.queue_path = data_dir / "notification-queue.jsonl"
        self.lock_path = data_dir / "run.lock"

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def run_lock(self) -> Iterator[None]:
        self.ensure()
        try:
            handle = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError("이전 실행이 아직 진행 중입니다.") from exc
        try:
            os.write(handle, str(os.getpid()).encode("ascii"))
            os.close(handle)
            yield
        finally:
            self.lock_path.unlink(missing_ok=True)

    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {"listings": {}, "last_successful_scan": None}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save_state(self, state: dict) -> None:
        self.ensure()
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def append_observations(self, listings: list[Listing]) -> None:
        self.ensure()
        with self.observations_path.open("a", encoding="utf-8") as handle:
            for listing in listings:
                handle.write(json.dumps(listing.to_dict(), ensure_ascii=False) + "\n")

    def append_run(self, result: ScanResult) -> None:
        self.ensure()
        payload = {
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "success": result.success,
            "successful_conditions": result.successful_conditions,
            "failed_conditions": result.failed_conditions,
            "collected_count": result.collected_count,
            "matched_count": len(result.matched),
            "urgent_count": len(result.urgent),
            "excluded_count": result.excluded_count,
        }
        with self.runs_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def enqueue_notification(self, message: str, link_url: str, error: str) -> None:
        self.ensure()
        payload = {"message": message, "link_url": link_url, "error": error}
        with self.queue_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
