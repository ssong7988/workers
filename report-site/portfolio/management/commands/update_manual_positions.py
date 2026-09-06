"""admin에 넣어 둔 보유 수량에 오늘 시세를 붙여 스냅샷을 만든다.

코인처럼 수집기가 닿지 않는 자산을 위한 것이다. 수량은 사람이 정하고 가격은
매일 여기서 가져온다. 만들어진 스냅샷은 H-able에서 온 것과 같은 자리에 들어가므로
비중·수익률 화면이 따로 알 필요가 없다.

시세를 못 받으면 멈춘다. 어제 가격으로 오늘 평가액을 적으면 조용히 틀린다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from portfolio.importing import PortfolioImportError, record_import_run
from portfolio.models import ManualHolding
from portfolio.performance import rebuild_metrics
from portfolio.prices import PriceError, fetch_prices

SOURCE_NAME = "시세 연동 (직접 입력 보유)"


class Command(BaseCommand):
    help = "직접 입력한 보유 수량에 오늘 시세를 붙여 잔고 스냅샷을 만듭니다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--as-of", default=None, help="기준일 YYYY-MM-DD (기본값: 오늘)")
        parser.add_argument(
            "--dry-run", action="store_true", help="저장하지 않고 계산 결과만 보여줍니다"
        )

    def handle(self, *args, **options) -> None:
        as_of = (
            date.fromisoformat(options["as_of"]) if options["as_of"] else date.today()
        )
        holdings = list(
            ManualHolding.objects.filter(active=True, account__active=True)
            .select_related("account", "instrument")
            .order_by("account_id", "instrument_id")
        )
        if not holdings:
            self.stdout.write("직접 입력한 보유가 없습니다.")
            return

        without_source = [
            holding for holding in holdings if not holding.instrument.price_source
        ]
        if without_source:
            names = ", ".join(holding.instrument.name for holding in without_source)
            raise CommandError(
                f"시세 출처가 비어 있는 종목이 있습니다: {names}\n"
                "admin의 종목 화면에서 `upbit:KRW-BTC`처럼 적어 주세요."
            )

        try:
            prices = fetch_prices([h.instrument.price_source for h in holdings])
        except PriceError as error:
            raise CommandError(str(error)) from error

        by_account: dict[str, list[dict]] = {}
        for holding in holdings:
            price = prices[holding.instrument.price_source]
            value = (holding.quantity * price).quantize(Decimal("0.01"))
            row = {
                "code": holding.instrument.pk,
                "name": holding.instrument.name,
                "currency": holding.instrument.currency,
                "quantity": str(holding.quantity),
                "price": str(price),
                "market_value": str(value),
                "market_value_krw": str(value),
            }
            if holding.cost_amount is not None:
                row["cost_amount"] = str(holding.cost_amount)
                row["unrealized_pl"] = str(value - holding.cost_amount)
            by_account.setdefault(holding.account_id, []).append(row)
            self.stdout.write(
                f"  {holding.instrument.name}: {holding.quantity} × {price:,.0f}"
                f" = {value:,.0f}원"
            )

        if options["dry_run"]:
            self.stdout.write("(저장 안 함)")
            return

        for account_id, rows in by_account.items():
            canonical = json.dumps(
                {"account": account_id, "positions": rows},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            payload = {
                "account": account_id,
                "as_of": as_of.isoformat(),
                "document_type": "balance",
                "status": "success",
                # 가격이 그대로면 같은 해시가 되어 서버가 다시 쓰지 않는다.
                "file_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "source_name": SOURCE_NAME,
                "positions": rows,
            }
            try:
                result = record_import_run(payload)
            except PortfolioImportError as error:
                raise CommandError(f"{account_id} 저장 실패: {error}") from error
            state = "중복(그대로)" if result.duplicate else ("신규" if result.created else "갱신")
            self.stdout.write(f"{account_id}: {state} · 보유 {result.position_count}건")

        rebuild_metrics()
        self.stdout.write(self.style.SUCCESS(f"{as_of} 시세 연동을 마쳤습니다."))
