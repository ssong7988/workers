"""소비 화면의 admin.

카테고리와 가맹점 규칙을 여기서 고친다. 규칙을 바꾸면 그 자리에서 전체를
다시 분류하므로, 명세서를 다시 수집할 필요가 없다.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import Count, Sum

from .categorize import recategorize_all
from .models import (
    CardHolder,
    MerchantRule,
    SpendingCategory,
    SpendingGroup,
    Statement,
    Transaction,
)


@admin.action(description="규칙으로 전체 거래를 다시 분류")
def recategorize(modeladmin, request, queryset):
    result = recategorize_all()
    messages.success(
        request,
        f"규칙 {result.by_rule}건, 결제유형 {result.by_payment_type}건으로 분류했습니다. "
        f"미분류 가맹점 {len(result.unmatched)}곳이 남았습니다.",
    )


@admin.register(SpendingGroup)
class SpendingGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "id", "order", "swatch", "category_names", "note")
    list_editable = ("order",)
    ordering = ("order", "name")

    @admin.display(description="색")
    def swatch(self, obj) -> str:
        from django.utils.html import format_html

        return format_html(
            '<span style="display:inline-block;width:1.1rem;height:1.1rem;'
            'border-radius:3px;background:{}"></span> {}',
            obj.color,
            obj.color,
        )

    @admin.display(description="포함 카테고리")
    def category_names(self, obj) -> str:
        return ", ".join(obj.categories.values_list("name", flat=True)) or "—"


@admin.register(SpendingCategory)
class SpendingCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "id", "group", "order", "is_financial_cost", "rule_count", "spent")
    list_editable = ("group", "order", "is_financial_cost")
    list_filter = ("group",)
    ordering = ("order", "name")
    actions = [recategorize]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_rules=Count("rules", distinct=True), _spent=Sum("transactions__billed_won"))
        )

    @admin.display(description="규칙", ordering="_rules")
    def rule_count(self, obj) -> int:
        return obj._rules

    @admin.display(description="누적 청구액", ordering="_spent")
    def spent(self, obj) -> str:
        return f"{obj._spent or 0:,}원"


@admin.register(MerchantRule)
class MerchantRuleAdmin(admin.ModelAdmin):
    list_display = ("keyword", "category", "order", "note")
    list_editable = ("category", "order", "note")
    list_filter = ("category",)
    search_fields = ("keyword", "note")
    ordering = ("order", "keyword")
    actions = [recategorize]
    # 좁은 규칙이 위에 와야 이마트24가 이마트에 먹히지 않는다.
    list_display_links = None

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        result = recategorize_all()
        messages.info(
            request,
            f"규칙을 반영했습니다. 미분류 가맹점 {len(result.unmatched)}곳이 남았습니다.",
        )


@admin.register(CardHolder)
class CardHolderAdmin(admin.ModelAdmin):
    list_display = ("name", "card_last4")
    list_editable = ("card_last4",)
    ordering = ("name", "card_last4")


class TransactionInline(admin.TabularInline):
    model = Transaction
    extra = 0
    can_delete = False
    fields = ("used_at", "merchant", "billed_won", "payment_type", "category", "category_source")
    readonly_fields = ("used_at", "merchant", "billed_won", "payment_type", "category_source")
    ordering = ("-billed_won",)

    def has_add_permission(self, request, obj=None) -> bool:
        # 거래는 수집기가 넣는다. 손으로 더하면 명세서 소계와 어긋난다.
        return False


@admin.register(Statement)
class StatementAdmin(admin.ModelAdmin):
    list_display = ("billing_month", "payment_date", "billed", "rows", "gap")
    ordering = ("-billing_month",)
    inlines = [TransactionInline]
    readonly_fields = ("billing_month", "payment_date", "total_billed_won", "source_ref", "parsed_at")

    @admin.display(description="청구총액")
    def billed(self, obj) -> str:
        return f"{obj.total_billed_won:,}원"

    @admin.display(description="거래")
    def rows(self, obj) -> int:
        return obj.transactions.count()

    @admin.display(description="소계 대조")
    def gap(self, obj) -> str:
        difference = obj.discrepancy_won
        return "일치" if difference == 0 else f"{difference:+,}원 어긋남"

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "used_at", "merchant", "billed", "payment_type", "category",
        "category_source", "excluded", "note",
    )
    list_editable = ("category", "excluded", "note")
    list_filter = ("excluded", "category", "payment_type", "statement__billing_month")
    search_fields = ("merchant", "merchant_norm")
    ordering = ("-used_at", "-billed_won")
    list_display_links = ("used_at",)
    actions = [recategorize]

    @admin.display(description="청구액", ordering="billed_won")
    def billed(self, obj) -> str:
        return f"{obj.billed_won:,}원"

    def save_model(self, request, obj, form, change):
        # 손으로 고른 카테고리는 규칙이 덮지 않도록 근거를 바꿔 둔다.
        obj.category_source = "manual"
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request) -> bool:
        return False
