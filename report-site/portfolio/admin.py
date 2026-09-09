"""파일을 고치지 않고 포트폴리오를 운영하기 위한 admin 화면.

여기서 손보는 것은 넷이다: 계좌, 종목 분류, 목표 비중, 국민연금 매핑.
수집 실행·보유 스냅샷·현금흐름은 수집기가 쓰는 기록이라 읽기 전용이다.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib import admin, messages

from portfolio.prices import PriceError, fetch_prices_cached

from .models import (
    ManualHolding,
    AssetClass,
    BenchmarkAllocation,
    CashFlow,
    DailyPortfolioMetric,
    HableAccountDailyMetric,
    ImportRun,
    Instrument,
    InvestmentAccount,
    PortfolioTarget,
    PositionSnapshot,
)


@admin.register(AssetClass)
class AssetClassAdmin(admin.ModelAdmin):
    list_display = ("name", "id", "benchmark_category", "display_order")
    list_editable = ("benchmark_category", "display_order")
    ordering = ("display_order", "name")


@admin.register(InvestmentAccount)
class InvestmentAccountAdmin(admin.ModelAdmin):
    list_display = (
        "alias",
        "id",
        "institution",
        "account_type",
        "masked_number",
        "required",
        "active",
    )
    list_filter = ("account_type", "required", "active")
    search_fields = ("id", "alias", "masked_number")


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "asset_class",
        "benchmark_category",
        "currency",
        "is_cash",
        "price_source",
    )
    # 새 종목이 미분류로 들어오므로 목록에서 바로 옮길 수 있어야 한다.
    list_editable = ("asset_class", "benchmark_category", "price_source")
    list_filter = ("asset_class", "currency", "is_cash")
    search_fields = ("code", "name")


@admin.register(ManualHolding)
class ManualHoldingAdmin(admin.ModelAdmin):
    """코인처럼 수집기가 닿지 않는 자산의 수량을 여기서 넣는다.

    가격은 `manage.py update_manual_positions`가 매일 시세에서 가져온다.
    종목의 `시세 출처`가 비어 있으면 그 종목은 건너뛴다.
    """

    list_display = (
        "account",
        "instrument",
        "quantity",
        "live_price",
        "live_value",
        "active",
        "updated_at",
    )
    list_filter = ("active", "account")
    search_fields = ("instrument__name", "instrument__code", "note")
    autocomplete_fields = ("instrument",)

    def _price(self, obj):
        """이 행의 지금 시세. 못 받으면 None - 목록이 통째로 죽으면 안 된다."""
        source = obj.instrument.price_source
        if not source:
            return None
        try:
            return fetch_prices_cached([source]).get(source)
        except PriceError:
            return None

    @admin.display(description="현재가")
    def live_price(self, obj):
        price = self._price(obj)
        return "-" if price is None else f"{price:,.0f}"

    @admin.display(description="평가액(지금)")
    def live_value(self, obj):
        price = self._price(obj)
        return "-" if price is None else f"{obj.quantity * price:,.0f}원"


@admin.register(PortfolioTarget)
class PortfolioTargetAdmin(admin.ModelAdmin):
    list_display = ("effective_from", "asset_class", "target_percent", "active")
    list_editable = ("target_percent", "active")
    list_filter = ("effective_from", "active")

    def changelist_view(self, request, extra_context=None):
        """합계가 100%가 아닌 적용일을 목록 위에 경고로 띄운다.

        화면이 그 세트를 조용히 무시하는 대신 어디가 어긋났는지 알려준다.
        """
        totals: dict[object, Decimal] = {}
        for row in PortfolioTarget.objects.filter(active=True):
            totals[row.effective_from] = (
                totals.get(row.effective_from, Decimal("0")) + row.target_percent
            )
        broken = [
            f"{day}: {total}%" for day, total in sorted(totals.items()) if total != 100
        ]
        if broken:
            self.message_user(
                request,
                "합계가 100%가 아닌 목표 비중 세트가 있습니다 — " + ", ".join(broken),
                level=messages.WARNING,
            )
        return super().changelist_view(request, extra_context)


@admin.register(BenchmarkAllocation)
class BenchmarkAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "as_of",
        "source_category",
        "benchmark_category",
        "source_percent",
        "source",
    )
    list_editable = ("benchmark_category", "source_percent")
    list_filter = ("as_of", "benchmark_category")


class ReadOnlyAdmin(admin.ModelAdmin):
    """수집기가 소유하는 기록. 보기만 하고 고치지 않는다."""

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ImportRun)
class ImportRunAdmin(ReadOnlyAdmin):
    list_display = (
        "as_of",
        "account",
        "document_type",
        "status",
        "row_count",
        "source_name",
        "created_at",
    )
    list_filter = ("status", "document_type", "account", "as_of")
    search_fields = ("file_hash", "source_name")


@admin.register(PositionSnapshot)
class PositionSnapshotAdmin(ReadOnlyAdmin):
    list_display = (
        "as_of",
        "account",
        "instrument",
        "quantity",
        "market_value_krw",
        "unrealized_pl",
    )
    list_filter = ("as_of", "account")
    search_fields = ("instrument__code", "instrument__name")


@admin.register(CashFlow)
class CashFlowAdmin(ReadOnlyAdmin):
    list_display = (
        "occurred_on",
        "account",
        "flow_type",
        "amount_krw",
        "is_external",
        "instrument",
    )
    list_filter = ("flow_type", "is_external", "account", "occurred_on")
    search_fields = ("external_key", "memo")


@admin.register(DailyPortfolioMetric)
class DailyPortfolioMetricAdmin(ReadOnlyAdmin):
    list_display = (
        "as_of",
        "market_value",
        "cumulative_external_flow",
        "investment_pl",
        "cumulative_return",
        "drawdown",
        "max_drawdown",
    )
    list_filter = ("as_of",)

    def has_delete_permission(self, request, obj=None) -> bool:
        # 재계산이 언제든 다시 만든다.
        return True


@admin.register(HableAccountDailyMetric)
class HableAccountDailyMetricAdmin(ReadOnlyAdmin):
    list_display = (
        "as_of",
        "account",
        "market_value",
        "investment_pl",
        "daily_return",
        "account_cumulative_return",
        "imported_at",
    )
    list_filter = ("account", "as_of")
