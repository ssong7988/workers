"""Admin screens for operating the property application without editing files."""

from django.contrib import admin

from .models import (
    GlobalRule,
    Listing,
    NotificationFailure,
    Observation,
    Scan,
    SearchCondition,
)


@admin.register(GlobalRule)
class GlobalRuleAdmin(admin.ModelAdmin):
    fieldsets = (
        ("거래", {"fields": ("trade_type",)}),
        (
            "저층",
            {
                "fields": (
                    "low_floor_numeric_floors",
                    "low_floor_labels",
                    "low_floor_price_discount_won",
                )
            },
        ),
        ("정기 보고", {"fields": ("timezone", "digest_weekdays", "digest_hour")}),
    )

    def has_add_permission(self, request) -> bool:
        return not GlobalRule.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(SearchCondition)
class SearchConditionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "region",
        "max_price_won",
        "urgent_price_won",
        "notify_new",
        "enabled",
        "updated_at",
    )
    list_filter = ("region", "enabled", "notify_new", "apply_low_floor_discount")
    search_fields = ("id", "name", "region")
    ordering = ("name",)


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "success",
        "collected_count",
        "matched_count",
        "urgent_count",
        "excluded_count",
    )
    list_filter = ("success",)
    date_hierarchy = "started_at"
    readonly_fields = tuple(field.name for field in Scan._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    list_display = (
        "observed_at",
        "complex_name",
        "listing_id",
        "condition",
        "price_won",
        "excluded",
        "exclusion_code",
    )
    list_filter = ("exclusion_code", "condition", "is_low_floor")
    search_fields = ("listing_id", "complex_name", "description", "exclusion_reason")
    date_hierarchy = "observed_at"
    readonly_fields = tuple(field.name for field in Observation._meta.fields)

    @admin.display(boolean=True, description="제외")
    def excluded(self, obj: Observation) -> bool:
        return bool(obj.exclusion_reason)

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "complex_name",
        "listing_id",
        "condition",
        "price_won",
        "floor_text",
        "active",
        "urgent",
        "last_seen_at",
    )
    list_filter = ("active", "is_low_floor", "condition")
    search_fields = ("listing_id", "complex_name", "description")
    date_hierarchy = "last_seen_at"
    readonly_fields = ("first_seen_at", "last_seen_at", "observed_at")

    @admin.display(boolean=True, description="급매")
    def urgent(self, obj: Listing) -> bool:
        return obj.is_urgent


@admin.register(NotificationFailure)
class NotificationFailureAdmin(admin.ModelAdmin):
    list_display = ("created_at", "scan", "attempts", "resolved_at", "short_error")
    list_filter = ("resolved_at",)
    search_fields = ("message", "error", "link_url")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)

    @admin.display(description="오류")
    def short_error(self, obj: NotificationFailure) -> str:
        return obj.error[:100]
