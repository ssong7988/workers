"""Persistent domain models for collection, matching, and notification."""

from __future__ import annotations

from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q


def _default_low_floor_numbers() -> list[int]:
    return [1, 2, 3]


def _default_low_floor_labels() -> list[str]:
    return ["저", "저층"]


def _default_digest_weekdays() -> list[int]:
    return [0, 1, 2, 3, 4]


def _validate_int_list(value: object) -> None:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in value
    ):
        raise ValidationError("정수 배열이어야 합니다.")


def _validate_string_list(value: object) -> None:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValidationError("하나 이상의 빈 값이 없는 문자열 배열이어야 합니다.")


def _validate_weekdays(value: object) -> None:
    _validate_int_list(value)
    if any(day < 0 or day > 6 for day in value):
        raise ValidationError("요일은 월요일 0부터 일요일 6 사이여야 합니다.")


def _validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError("유효한 IANA 시간대를 입력하세요.") from exc


class GlobalRule(models.Model):
    """The single row containing application-wide matching and schedule rules."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    trade_type = models.CharField(
        "거래 유형", max_length=16, choices=(("sale", "매매"),), default="sale"
    )
    low_floor_numeric_floors = models.JSONField(
        "저층 숫자", default=_default_low_floor_numbers, validators=[_validate_int_list]
    )
    low_floor_labels = models.JSONField(
        "저층 표기", default=_default_low_floor_labels, validators=[_validate_string_list]
    )
    low_floor_price_discount_won = models.PositiveBigIntegerField(
        "저층 가격 차감액", default=100_000_000
    )
    timezone = models.CharField(
        "시간대", max_length=64, default="Asia/Seoul", validators=[_validate_timezone]
    )
    digest_weekdays = models.JSONField(
        "정기 보고 요일", default=_default_digest_weekdays, validators=[_validate_weekdays]
    )
    digest_hour = models.PositiveSmallIntegerField(
        "정기 보고 시각", default=8, validators=[MaxValueValidator(23)]
    )
    updated_at = models.DateTimeField("수정 시각", auto_now=True)

    class Meta:
        verbose_name = "공통 규칙"
        verbose_name_plural = "공통 규칙"

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return "공통 규칙"


class SearchCondition(models.Model):
    """An editable search/matching condition formerly stored in YAML."""

    id = models.SlugField("조건 ID", primary_key=True, max_length=100)
    name = models.CharField("이름", max_length=200)
    # Groups conditions for the statistics screen. Free text so a new area needs
    # no migration; the screen offers whatever values the table already holds.
    region = models.CharField("지역", max_length=50, blank=True, db_index=True)
    complex_names = models.JSONField(
        "단지명 별칭", default=list, validators=[_validate_string_list]
    )
    search_url = models.URLField("검색 URL", max_length=2048, blank=True)
    exclusive_area_m2 = models.DecimalField(
        "기준 전용면적(㎡)", max_digits=7, decimal_places=3, null=True, blank=True
    )
    exclusive_area_min_m2 = models.DecimalField(
        "최소 전용면적(㎡)", max_digits=7, decimal_places=3, null=True, blank=True
    )
    exclusive_area_max_m2 = models.DecimalField(
        "최대 전용면적(㎡)", max_digits=7, decimal_places=3, null=True, blank=True
    )
    # NULL means every type is accepted, matching `allowed_types: all` in YAML.
    allowed_types = models.JSONField(
        "허용 타입", null=True, blank=True, validators=[_validate_string_list]
    )
    max_price_won = models.PositiveBigIntegerField(
        "조사 상한가", null=True, blank=True
    )
    urgent_price_won = models.PositiveBigIntegerField(
        "급매 기준가", null=True, blank=True
    )
    notify_new = models.BooleanField("신규 매물 알림", default=False)
    apply_low_floor_discount = models.BooleanField("저층 차감 적용", default=True)
    enabled = models.BooleanField("사용", default=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)
    updated_at = models.DateTimeField("수정 시각", auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "검색 조건"
        verbose_name_plural = "검색 조건"
        constraints = [
            models.CheckConstraint(
                condition=Q(max_price_won__isnull=True)
                | Q(urgent_price_won__isnull=True)
                | Q(urgent_price_won__lte=models.F("max_price_won")),
                name="urgent_price_not_above_max",
            ),
            models.CheckConstraint(
                condition=Q(exclusive_area_min_m2__isnull=True)
                | Q(exclusive_area_max_m2__isnull=True)
                | Q(exclusive_area_min_m2__lte=models.F("exclusive_area_max_m2")),
                name="area_min_not_above_max",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if (
            self.max_price_won is not None
            and self.urgent_price_won is not None
            and self.urgent_price_won > self.max_price_won
        ):
            errors["urgent_price_won"] = "급매 기준가는 조사 상한가보다 높을 수 없습니다."
        if (
            self.exclusive_area_min_m2 is not None
            and self.exclusive_area_max_m2 is not None
            and self.exclusive_area_min_m2 > self.exclusive_area_max_m2
        ):
            errors["exclusive_area_max_m2"] = "최대 면적은 최소 면적보다 작을 수 없습니다."
        if self.search_url:
            parsed = urlparse(self.search_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or not parsed.hostname.endswith("naver.com")
            ):
                errors["search_url"] = "네이버 HTTPS 검색 URL만 허용합니다."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return self.name


class Scan(models.Model):
    """One collector run and its persisted outcome, including no-send reasons."""

    started_at = models.DateTimeField("시작 시각", db_index=True)
    finished_at = models.DateTimeField("종료 시각", null=True, blank=True)
    success = models.BooleanField("성공", default=False)
    successful_conditions = models.JSONField("성공 조건", default=list)
    failed_conditions = models.JSONField("실패 조건", default=dict)
    collected_count = models.PositiveIntegerField("수집 수", default=0)
    matched_count = models.PositiveIntegerField("조건 충족 수", default=0)
    urgent_count = models.PositiveIntegerField("급매 수", default=0)
    excluded_count = models.PositiveIntegerField("제외 수", default=0)
    notification = models.TextField("알림 결과 또는 미전송 사유", blank=True)
    created_at = models.DateTimeField("기록 시각", auto_now_add=True)

    class Meta:
        ordering = ("-started_at",)
        verbose_name = "수집 실행"
        verbose_name_plural = "수집 실행"
        constraints = [
            models.UniqueConstraint(fields=("started_at",), name="unique_scan_started_at")
        ]

    def __str__(self) -> str:
        status = "성공" if self.success else "실패"
        return f"{self.started_at:%Y-%m-%d %H:%M:%S} ({status})"


class PropertyFields(models.Model):
    """Fields shared by immutable observations and current listings."""

    listing_id = models.CharField("매물 ID", max_length=100)
    complex_name = models.CharField("단지명", max_length=255)
    building = models.CharField("동", max_length=50, blank=True)
    type_name = models.CharField("타입", max_length=100, blank=True)
    exclusive_area_m2 = models.DecimalField(
        "전용면적(㎡)", max_digits=7, decimal_places=3
    )
    price_won = models.PositiveBigIntegerField("가격")
    floor_text = models.CharField("층", max_length=100, blank=True)
    floor = models.IntegerField("숫자 층", null=True, blank=True)
    direction = models.CharField("방향", max_length=100, blank=True)
    description = models.TextField("설명", blank=True)
    url = models.URLField("원본 URL", max_length=2048, blank=True)
    observed_at = models.DateTimeField("관측 시각", db_index=True)
    is_low_floor = models.BooleanField("저층", default=False)
    effective_max_price_won = models.PositiveBigIntegerField(
        "적용 조사 상한가", null=True, blank=True
    )
    effective_urgent_price_won = models.PositiveBigIntegerField(
        "적용 급매 기준가", null=True, blank=True
    )

    class Meta:
        abstract = True


class Observation(PropertyFields):
    """Every raw listing received in a scan, whether it matched or not."""

    scan = models.ForeignKey(
        Scan, on_delete=models.CASCADE, related_name="observations", verbose_name="수집 실행"
    )
    condition = models.ForeignKey(
        SearchCondition,
        on_delete=models.PROTECT,
        related_name="observations",
        verbose_name="검색 조건",
        null=True,
        blank=True,
    )
    exclusion_reason = models.TextField("제외 사유", blank=True)
    # Stable machine-readable form of `exclusion_reason`, which is a Korean
    # display string. Statistics filter on this, never on the text.
    exclusion_code = models.CharField(
        "제외 구분",
        max_length=16,
        blank=True,
        db_index=True,
        choices=(
            ("", "조건 충족"),
            ("complex", "단지명 불일치"),
            ("area", "면적"),
            ("type", "타입"),
            ("floor", "층 해석 실패"),
            ("price", "가격 초과"),
        ),
    )
    raw_payload = models.JSONField("수집 원본", default=dict, blank=True)

    class Meta:
        ordering = ("-observed_at", "listing_id")
        verbose_name = "수집 원본"
        verbose_name_plural = "수집 원본"
        indexes = [models.Index(fields=("scan", "condition"))]
        constraints = [
            models.UniqueConstraint(
                fields=("scan", "condition", "listing_id"),
                name="unique_observation_per_scan_condition",
            )
        ]

    def __str__(self) -> str:
        return f"{self.complex_name} {self.listing_id}"


class Listing(PropertyFields):
    """Current state of a listing that passed one search condition."""

    condition = models.ForeignKey(
        SearchCondition,
        on_delete=models.PROTECT,
        related_name="listings",
        verbose_name="검색 조건",
    )
    first_seen_at = models.DateTimeField("최초 확인 시각")
    last_seen_at = models.DateTimeField("최근 확인 시각", db_index=True)
    active = models.BooleanField("현재 노출", default=True)
    last_urgent_alert_price_won = models.PositiveBigIntegerField(
        "마지막 급매 알림 가격", null=True, blank=True
    )
    # 네이버가 같은 집을 중개사별로 두 건으로 보여줄 때, 늦게 본 쪽이 먼저 본
    # 쪽을 가리킨다. 행은 지우지 않는다 - 무엇이 왜 묶였는지 남겨야 한다.
    # 화면과 카카오는 대표만 센다.
    duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="duplicates",
        verbose_name="대표 매물",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("price_won", "floor", "listing_id")
        verbose_name = "조건 충족 매물"
        verbose_name_plural = "조건 충족 매물"
        constraints = [
            models.UniqueConstraint(
                fields=("condition", "listing_id"), name="unique_listing_per_condition"
            )
        ]
        indexes = [models.Index(fields=("condition", "active"))]

    @property
    def key(self) -> str:
        return f"{self.condition_id}:{self.listing_id}"

    @property
    def is_urgent(self) -> bool:
        return (
            self.effective_urgent_price_won is not None
            and self.price_won <= self.effective_urgent_price_won
        )

    def __str__(self) -> str:
        return f"{self.complex_name} {self.listing_id}"


class NotificationFailure(models.Model):
    """A failed Kakao delivery retained for diagnosis or a later retry."""

    scan = models.ForeignKey(
        Scan,
        on_delete=models.SET_NULL,
        related_name="notification_failures",
        verbose_name="수집 실행",
        null=True,
        blank=True,
    )
    message = models.TextField("메시지")
    link_url = models.URLField("링크 URL", max_length=2048, blank=True)
    error = models.TextField("오류")
    attempts = models.PositiveIntegerField("시도 횟수", default=1)
    created_at = models.DateTimeField("발생 시각", auto_now_add=True)
    last_attempt_at = models.DateTimeField("마지막 시도 시각", null=True, blank=True)
    resolved_at = models.DateTimeField("처리 완료 시각", null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "알림 실패"
        verbose_name_plural = "알림 실패"

    def __str__(self) -> str:
        return f"알림 실패 #{self.pk or '-'}"
