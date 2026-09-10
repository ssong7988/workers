"""삼성카드 소비의 영속 모델.

부동산(`properties/`)·금융자산(`portfolio/`)과 같은 Django/PostgreSQL 위에
있지만 도메인은 분리돼 있다. 여기 저장되는 것은 카드 청구 내역뿐이다.

수집기(`spending-analyzer/`)는 이용대금명세서 메일을 열어 거래를 정규화해
넘기기만 한다. 카테고리 규칙, 분류, 집계, 카카오 요약은 전부 여기가 소유한다.

**집계는 청구 기준이다.** 그 달 명세서가 청구한 금액을 그대로 쓰므로 할부는
이번 달 회차 금액만 잡히고, 월 합계가 통장에서 실제로 빠진 돈과 일치한다.
이용일이 8월인 거래도 9월 명세서가 청구했다면 9월에 들어간다.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.db import models


# 규칙에 걸리지 않은 가맹점이 모이는 자리. 임의로 분류하지 않고 여기 모아두었다가
# admin에서 규칙을 만들며, 그 전까지는 화면에 미분류 금액으로 명시한다.
# `portfolio`의 UNCLASSIFIED_ASSET_CLASS_ID와 같은 규칙이다.
UNCLASSIFIED_CATEGORY_ID = "unclassified"

# 명세서가 구분을 나누는 방식 그대로다. 연회비와 이자는 가맹점 소비가 아니라
# 청구라서, 가맹점 이름이 무엇이든 규칙을 태우지 않고 금융비용으로 보낸다.
PAYMENT_TYPES = (
    ("lump", "일시불"),
    ("installment", "할부"),
    ("cash_advance", "현금서비스"),
    ("overseas", "해외"),
    ("annual_fee", "연회비"),
    ("interest", "이자"),
    ("other", "기타"),
)
PAYMENT_TYPE_LABELS = dict(PAYMENT_TYPES)
FINANCIAL_COST_TYPES = ("annual_fee", "interest")

CATEGORY_SOURCES = (
    ("rule", "규칙"),
    ("payment_type", "결제유형"),
    ("manual", "직접 지정"),
    ("", "미분류"),
)

BILLING_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_billing_month(value: str) -> None:
    if not BILLING_MONTH.match(value or ""):
        raise ValidationError("청구월은 YYYY-MM 형식이어야 합니다.")


class SpendingGroup(models.Model):
    """카테고리를 묶는 대분류.

    카테고리 열여섯 개는 한 달 지출의 성격을 한눈에 말해 주지 못한다. 대분류는
    "줄일 수 없는 돈이 얼마고 내가 조절하는 돈이 얼마인가"를 답하는 축이라,
    다섯에서 여섯 개를 넘기지 않는다. 늘어나면 그 질문에 답하지 못한다.

    `color`는 차트의 조각 색이다. 대분류마다 고정이라 달이 바뀌어도 같은
    성격이 같은 색으로 보인다 - 색이 순위를 따라다니면 비교가 안 된다.
    """

    id = models.SlugField("코드", primary_key=True, max_length=40)
    name = models.CharField("이름", max_length=40)
    order = models.PositiveSmallIntegerField("정렬", default=100)
    color = models.CharField(
        "색", max_length=7, default="#94a3b8", help_text="#rrggbb"
    )
    note = models.CharField("설명", max_length=120, blank=True)

    class Meta:
        verbose_name = "대분류"
        verbose_name_plural = "대분류"
        ordering = ("order", "name")

    def __str__(self) -> str:
        return self.name


class SpendingCategory(models.Model):
    """소비 카테고리. admin에서 더하고 이름을 바꿀 수 있다."""

    id = models.SlugField("코드", primary_key=True, max_length=40)
    name = models.CharField("이름", max_length=40)
    group = models.ForeignKey(
        SpendingGroup,
        on_delete=models.PROTECT,
        related_name="categories",
        verbose_name="대분류",
        null=True,
        blank=True,
    )
    order = models.PositiveSmallIntegerField("정렬", default=100)
    is_financial_cost = models.BooleanField(
        "금융비용", default=False, help_text="연회비·이자가 자동으로 들어갈 카테고리"
    )

    class Meta:
        verbose_name = "소비 카테고리"
        verbose_name_plural = "소비 카테고리"
        ordering = ("order", "name")

    def __str__(self) -> str:
        return self.name

    @property
    def is_unclassified(self) -> bool:
        return self.pk == UNCLASSIFIED_CATEGORY_ID


class MerchantRule(models.Model):
    """가맹점명 키워드 하나를 카테고리에 붙인다.

    정규화된 가맹점명에 `keyword`가 들어 있으면 그 카테고리가 된다. 위에서부터
    먼저 맞는 규칙이 이기므로 좁은 규칙을 위에 둔다 — `이마트24`(편의점)가
    `이마트`(마트)보다 먼저 와야 하는 이유다.
    """

    keyword = models.CharField("키워드", max_length=80, unique=True)
    category = models.ForeignKey(
        SpendingCategory,
        on_delete=models.PROTECT,
        related_name="rules",
        verbose_name="카테고리",
    )
    order = models.PositiveSmallIntegerField(
        "우선순위", default=100, help_text="작을수록 먼저 검사한다"
    )
    note = models.CharField("메모", max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "가맹점 규칙"
        verbose_name_plural = "가맹점 규칙"
        ordering = ("order", "-keyword")

    def __str__(self) -> str:
        return f"{self.keyword} → {self.category_id}"

    def save(self, *args, **kwargs):
        # 저장 시점에 정규화해 두면 매칭할 때마다 다시 다듬을 필요가 없고,
        # admin에서 공백을 넣어 입력해도 규칙이 조용히 죽지 않는다.
        self.keyword = normalize_merchant(self.keyword)
        super().save(*args, **kwargs)


class Statement(models.Model):
    """명세서 한 통 = 한 청구월.

    명세서는 월 단위 스냅샷이라 재발송·정정본이 오면 그 달을 통째로 바꾼다.
    그래서 청구월이 유일 키이고, 거래 단위 중복 판정이 필요 없다.
    """

    billing_month = models.CharField(
        "청구월", max_length=7, unique=True, validators=[validate_billing_month]
    )
    payment_date = models.DateField("결제일", null=True, blank=True)
    total_billed_won = models.BigIntegerField("청구총액")
    source_ref = models.CharField("원본 메일", max_length=200, blank=True)
    parsed_at = models.DateTimeField("파싱 시각", null=True, blank=True)
    received_at = models.DateTimeField("수신 시각", auto_now=True)
    # 카카오 요약은 청구월당 한 번이다. 스케줄러가 매일 돌아도 이미 보낸 달은
    # 다시 보내지 않으며, 다시 보내고 싶으면 admin에서 이 값을 비우면 된다.
    digest_sent_at = models.DateTimeField("카카오 발송", null=True, blank=True)

    class Meta:
        verbose_name = "명세서"
        verbose_name_plural = "명세서"
        ordering = ("-billing_month",)

    def __str__(self) -> str:
        return f"{self.billing_month} {self.total_billed_won:,}원"

    @property
    def parsed_total_won(self) -> int:
        """명세서 대조용 합계. 제외한 줄도 포함한다.

        카드사가 청구한 금액과 견주는 값이라, 내가 집계에서 뺀 줄이라고 해서
        빼면 대조가 성립하지 않는다.
        """
        return sum(item.billed_won for item in self.transactions.all())

    @property
    def analysed_total_won(self) -> int:
        """화면과 요약이 쓰는 합계. 제외한 줄은 빠진다."""
        return sum(
            item.billed_won for item in self.transactions.all() if not item.excluded
        )

    @property
    def excluded_total_won(self) -> int:
        return self.parsed_total_won - self.analysed_total_won

    @property
    def discrepancy_won(self) -> int:
        """행 합계와 명세서가 스스로 적은 청구총액의 차이."""
        return self.parsed_total_won - self.total_billed_won


class Transaction(models.Model):
    """청구된 거래 한 줄."""

    statement = models.ForeignKey(
        Statement,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name="명세서",
    )
    used_at = models.DateField("이용일")
    merchant = models.CharField("가맹점", max_length=200)
    merchant_norm = models.CharField("정규화명", max_length=200, db_index=True)
    billed_won = models.BigIntegerField("청구액", help_text="취소는 음수")
    total_won = models.BigIntegerField("원 이용금액")
    payment_type = models.CharField(
        "결제유형", max_length=20, choices=PAYMENT_TYPES, default="lump"
    )
    installment_seq = models.PositiveSmallIntegerField("할부 회차", default=0)
    installment_months = models.PositiveSmallIntegerField("할부 개월", default=0)
    card_last4 = models.CharField("카드 뒤 4자리", max_length=4, blank=True)
    category = models.ForeignKey(
        SpendingCategory,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name="카테고리",
    )
    category_source = models.CharField(
        "분류 근거", max_length=20, choices=CATEGORY_SOURCES, blank=True
    )
    # 대신 결제해 주고 돌려받는 돈처럼, 청구는 됐지만 내 소비가 아닌 줄이 있다.
    # 지우지 않고 표시만 해 둔다 - 명세서의 청구총액과 대조하려면 그 줄도
    # 그대로 있어야 하고, 언제든 되돌릴 수 있어야 한다.
    excluded = models.BooleanField(
        "집계 제외", default=False, help_text="체크하면 분석에서 빼지만 명세서 대조에는 남는다"
    )

    class Meta:
        verbose_name = "거래"
        verbose_name_plural = "거래"
        ordering = ("-used_at", "-billed_won")
        indexes = [
            models.Index(fields=["statement", "category"]),
            models.Index(fields=["used_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.used_at} {self.merchant} {self.billed_won:,}원"

    @property
    def billing_month(self) -> str:
        return self.statement.billing_month

    @property
    def is_installment(self) -> bool:
        return self.installment_months > 1

    @property
    def remaining_installments(self) -> int:
        """이번 회차 뒤로 아직 청구될 회차 수."""
        if not self.is_installment:
            return 0
        return max(0, self.installment_months - self.installment_seq)


# 법인 표기는 정보가 없고 같은 가맹점인데도 명세서마다 다르게 찍힌다.
_CORPORATE = re.compile(r"\(주\)|\(유\)|㈜|주식회사|유한회사")
_WHITESPACE = re.compile(r"\s+")


def normalize_merchant(raw: str) -> str:
    """가맹점명을 매칭용 키로 다듬는다.

    지점 접미사는 일부러 남긴다. 규칙이 부분 문자열로 맞으므로 `스타벅스`가
    이미 `스타벅스과천점`을 잡고, 접미사를 짐작해 떼면 그 글자로 끝나는
    멀쩡한 이름이 망가진다.
    """
    text = _CORPORATE.sub("", raw or "")
    text = _WHITESPACE.sub("", text)
    return text.upper()
