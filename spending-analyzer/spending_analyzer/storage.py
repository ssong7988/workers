"""Atomic per-month storage designed behind a future PostgreSQL-compatible interface."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .models import Statement


BILLING_MONTH = re.compile(r"^\d{4}-\d{2}$")


class StatementStore:
    """One JSON file per billing month.

    A statement is a monthly snapshot, so saving replaces the month outright —
    a re-sent or corrected statement simply overwrites its own file, and no
    transaction-level deduplication is needed anywhere in the pipeline.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.statements_dir = data_dir / "statements"

    def ensure(self) -> None:
        self.statements_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, billing_month: str) -> Path:
        if not BILLING_MONTH.match(billing_month):
            raise ValueError(f"청구월 형식이 잘못되었습니다: {billing_month}")
        return self.statements_dir / f"{billing_month}.json"

    def save(self, statement: Statement) -> Path:
        self.ensure()
        target = self.path_for(statement.billing_month)
        write_json(target, statement.to_dict())
        return target

    def load(self, billing_month: str) -> Statement | None:
        target = self.path_for(billing_month)
        if not target.exists():
            return None
        return Statement.from_dict(json.loads(target.read_text(encoding="utf-8")))

    def months(self) -> list[str]:
        if not self.statements_dir.exists():
            return []
        return sorted(
            path.stem for path in self.statements_dir.glob("*.json") if BILLING_MONTH.match(path.stem)
        )

    def load_all(self) -> list[Statement]:
        return [statement for month in self.months() if (statement := self.load(month))]


def write_json(target: Path, payload: object) -> None:
    """Write JSON atomically so a crash never leaves a half-written file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
