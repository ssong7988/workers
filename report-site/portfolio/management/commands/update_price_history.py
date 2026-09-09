"""외부 시세 종목의 최근 일 종가를 저장한다."""

import time
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from portfolio.models import Instrument, InstrumentDailyPrice, PositionSnapshot
from portfolio.prices import KNOWN_HISTORY_SOURCES, PriceError, fetch_daily_prices


class Command(BaseCommand):
    help = "직접 입력 보유 종목의 외부 일봉을 저장합니다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--days", type=int, default=365, help="가져올 과거 일수")
        parser.add_argument("--end", default=None, help="마지막 기준일 YYYY-MM-DD")

    def handle(self, *args, **options) -> None:
        days = options["days"]
        if days < 1 or days > 3660:
            raise CommandError("--days는 1~3660 사이여야 합니다.")
        end = date.fromisoformat(options["end"]) if options["end"] else date.today()
        start = end - timedelta(days=days)
        latest = PositionSnapshot.objects.filter(
            account__active=True, as_of__lte=end
        ).aggregate(day=Max("as_of"))["day"]
        if latest is None:
            self.stdout.write("보유 스냅샷이 없습니다.")
            return
        instrument_ids = PositionSnapshot.objects.filter(
            account__active=True, as_of=latest
        ).values_list("instrument_id", flat=True)
        instruments = list(
            Instrument.objects.filter(pk__in=instrument_ids)
            .order_by("pk")
        )
        requested = [
            (instrument, instrument.price_source or KNOWN_HISTORY_SOURCES.get(instrument.name, ""))
            for instrument in instruments
        ]
        requested = [(instrument, source) for instrument, source in requested if source]
        if not requested:
            self.stdout.write("외부 일봉 심볼이 연결된 보유 종목이 없습니다.")
            return

        total = 0
        for instrument, source in requested:
            try:
                rows = fetch_daily_prices(source, start=start, end=end)
            except PriceError as error:
                raise CommandError(f"{instrument.name} 일봉 수집 실패: {error}") from error
            for day, close in rows:
                InstrumentDailyPrice.objects.update_or_create(
                    as_of=day,
                    instrument=instrument,
                    defaults={"close": close, "source": source},
                )
            total += len(rows)
            self.stdout.write(
                f"{instrument.name}: {len(rows)}일 ({rows[0][0]} ~ {rows[-1][0]})"
                if rows else f"{instrument.name}: 받은 일봉 없음"
            )
            time.sleep(0.15)
        self.stdout.write(self.style.SUCCESS(f"외부 일봉 {total}건을 저장했습니다."))
