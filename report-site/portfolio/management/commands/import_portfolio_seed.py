"""빈 DB에 자산분류·계좌·국민연금 기준 비중을 넣는다.

다시 돌려도 안전하다. 이미 있는 행은 갱신만 하고, 종목 분류는 아직 미분류인
종목만 옮긴다 - admin에서 손으로 정한 분류를 시드가 되돌리면 안 된다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from portfolio.models import (
    UNCLASSIFIED_ASSET_CLASS_ID,
    AssetClass,
    BenchmarkAllocation,
    Instrument,
    InvestmentAccount,
)


DEFAULT_PATH = Path(__file__).resolve().parents[2] / "seed" / "portfolio.yaml"


class Command(BaseCommand):
    help = "금융자산 포트폴리오의 초기 자산분류·계좌·국민연금 기준 비중을 넣습니다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--path",
            type=Path,
            help="시드 YAML 경로 (기본값: portfolio/seed/portfolio.yaml)",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        path = options["path"] or DEFAULT_PATH
        if not path.exists():
            raise CommandError(f"시드 파일이 없습니다: {path}")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise CommandError(f"시드 파일을 읽을 수 없습니다: {exc}") from exc

        classes = self._load_asset_classes(raw.get("asset_classes", []))
        accounts = self._load_accounts(raw.get("accounts", []))
        benchmarks = self._load_benchmark(raw.get("benchmark") or {})
        reclassified = self._apply_instrument_names(raw.get("instrument_names") or {})

        self.stdout.write(
            self.style.SUCCESS(
                f"시드 완료: 자산분류 {classes}개, 계좌 {accounts}개, "
                f"국민연금 기준 {benchmarks}개, 종목 재분류 {reclassified}개"
            )
        )

    def _load_asset_classes(self, rows: list[dict]) -> int:
        for row in rows:
            try:
                class_id = str(row["id"])
                name = str(row["name"])
            except (KeyError, TypeError) as exc:
                raise CommandError("각 자산분류에는 id와 name이 필요합니다.") from exc
            values = {
                "name": name,
                "benchmark_category": str(row.get("benchmark_category") or ""),
                "display_order": int(row.get("display_order", 100)),
            }
            candidate = AssetClass(id=class_id, **values)
            candidate.full_clean(validate_unique=False, validate_constraints=False)
            AssetClass.objects.update_or_create(id=class_id, defaults=values)
        return len(rows)

    def _load_accounts(self, rows: list[dict]) -> int:
        for row in rows:
            try:
                account_id = str(row["id"])
                values = {
                    "institution": str(row.get("institution", "KB증권")),
                    "alias": str(row["alias"]),
                    "account_type": str(row["account_type"]),
                    "masked_number": str(row.get("masked_number", "")),
                    "required": bool(row.get("required", True)),
                    "active": bool(row.get("active", True)),
                }
            except (KeyError, TypeError) as exc:
                raise CommandError(
                    "각 계좌에는 id, alias, account_type이 필요합니다."
                ) from exc
            candidate = InvestmentAccount(id=account_id, **values)
            candidate.full_clean(validate_unique=False, validate_constraints=False)
            # 이미 있는 계좌의 마스킹 번호는 수집기가 채운 실제 값이므로,
            # 비어 있는 시드 값으로 덮어쓰지 않는다.
            existing = InvestmentAccount.objects.filter(pk=account_id).first()
            if existing is not None and not values["masked_number"]:
                values.pop("masked_number")
            InvestmentAccount.objects.update_or_create(id=account_id, defaults=values)
        return len(rows)

    def _load_benchmark(self, block: dict) -> int:
        rows = block.get("rows") or []
        if not rows:
            return 0
        try:
            as_of = date.fromisoformat(str(block["as_of"]))
        except (KeyError, ValueError) as exc:
            raise CommandError("benchmark.as_of는 YYYY-MM-DD여야 합니다.") from exc
        source = str(block.get("source", ""))
        for row in rows:
            try:
                category = str(row["source_category"])
                values = {
                    "benchmark_category": str(row["benchmark_category"]),
                    "source_percent": Decimal(str(row["source_percent"])),
                    "source": source,
                }
            except (KeyError, TypeError) as exc:
                raise CommandError(
                    "각 국민연금 행에는 source_category, benchmark_category, "
                    "source_percent가 필요합니다."
                ) from exc
            candidate = BenchmarkAllocation(
                as_of=as_of, source_category=category, **values
            )
            candidate.full_clean(validate_unique=False, validate_constraints=False)
            BenchmarkAllocation.objects.update_or_create(
                as_of=as_of, source_category=category, defaults=values
            )
        return len(rows)

    def _apply_instrument_names(self, mapping: dict[str, list[str]]) -> int:
        """이름이 시드에 있는 미분류 종목만 옮긴다."""
        moved = 0
        for class_id, names in mapping.items():
            if not AssetClass.objects.filter(pk=class_id).exists():
                raise CommandError(f"instrument_names에 없는 자산분류입니다: {class_id}")
            moved += Instrument.objects.filter(
                asset_class_id=UNCLASSIFIED_ASSET_CLASS_ID,
                name__in=[str(name) for name in names],
            ).update(asset_class_id=class_id)
        return moved
