"""Re-judge stored observations against the current search conditions.

The observations imported from the old JSONL history arrived without a per-row
exclusion reason: their `Scan` carries correct matched/excluded counts, but
every row reads as if it matched. That is invisible in the report, which only
renders `Listing`, and fatal to the statistics, which read `Observation` and
would pool a 59m2 unit with a 137m2 one.

This walks the observations and fills in what `record_scan()` computes for a
live scan. It is also the way to refresh history after editing a condition in
admin, since past rows were judged against the old rule.

Re-judging uses today's conditions, not the ones in force at scan time. That is
a deliberate trade: the alternative is leaving rows labelled as matched when
they never were.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from properties.matching import classify_exclusion, explain_condition
from properties.models import GlobalRule, Observation


BATCH = 500
UPDATED_FIELDS = (
    "exclusion_reason",
    "exclusion_code",
    "floor",
    "is_low_floor",
    "effective_max_price_won",
    "effective_urgent_price_won",
)


class Command(BaseCommand):
    help = "저장된 수집 원본을 현재 검색 조건으로 다시 판정해 제외 사유를 채웁니다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="바꾸지 않고 달라지는 건수만 출력합니다.",
        )
        parser.add_argument(
            "--only-unjudged",
            action="store_true",
            help="제외 사유가 비어 있는 행만 다시 판정합니다.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        rule = GlobalRule.objects.get(pk=1)
        query = Observation.objects.filter(condition__isnull=False).select_related(
            "condition"
        )
        if options["only_unjudged"]:
            query = query.filter(exclusion_reason="")

        pending: list[Observation] = []
        changed = 0
        counts: dict[str, int] = {}
        for observation in query.iterator(chunk_size=BATCH):
            before = (observation.exclusion_reason, observation.exclusion_code)
            # Start from a clean slate: explain_condition returns early for a
            # name, area or type mismatch and would otherwise leave the stale
            # floor and threshold values in place.
            observation.floor = None
            observation.is_low_floor = False
            observation.effective_max_price_won = None
            observation.effective_urgent_price_won = None

            reason = explain_condition(observation, observation.condition, rule)
            observation.exclusion_reason = reason or ""
            observation.exclusion_code = classify_exclusion(reason)
            counts[observation.exclusion_code] = (
                counts.get(observation.exclusion_code, 0) + 1
            )
            if before != (observation.exclusion_reason, observation.exclusion_code):
                changed += 1

            pending.append(observation)
            if len(pending) >= BATCH and not options["dry_run"]:
                Observation.objects.bulk_update(pending, UPDATED_FIELDS)
                pending.clear()

        if pending and not options["dry_run"]:
            Observation.objects.bulk_update(pending, UPDATED_FIELDS)

        total = sum(counts.values())
        breakdown = ", ".join(
            f"{code or '조건충족'} {count}" for code, count in sorted(counts.items())
        )
        prefix = "다시 판정하면" if options["dry_run"] else "다시 판정 완료:"
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix} 대상 {total}건 · 변경 {changed}건 · {breakdown}"
            )
        )
        if options["dry_run"]:
            transaction.set_rollback(True)
