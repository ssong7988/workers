"""KB증권 금융자산 포트폴리오의 영속 모델.

부동산(`properties/`)과 같은 Django/PostgreSQL 위에 있지만 도메인은 완전히
분리돼 있다. 여기에 저장되는 것은 오직 금융자산이며, 부동산 평가액은 비중·
수익률·국민연금 비교 어디에도 섞이지 않는다.

수집기(`stock-importer/`)는 H-able 파일을 읽어 정규화한 원본을 넘기기만
한다. 자산분류, 목표 비중, 국민연금 매핑, 성과, 리밸런싱은 전부 여기가
소유한다 — `.agent/PROJECT_STATE.md`의 "역할 경계와 수집 흐름"을 참고한다.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


# 국민연금과 비교할 때만 쓰는 공통분류. 개인의 자산분류(`AssetClass`)는 이보다
# 세분화돼 있고, 파이차트는 개인 분류 그대로 그린다.
BENCHMARK_CATEGORIES = (
    ("domestic_stock", "국내주식"),
    ("foreign_stock", "해외주식"),
    ("bond", "채권"),
    ("alternative", "대체투자"),
)
BENCHMARK_LABELS = dict(BENCHMARK_CATEGORIES)
BENCHMARK_ORDER = [key for key, _ in BENCHMARK_CATEGORIES]

# 처음 보는 종목이 들어가는 자리. 임의로 분류하지 않고 여기에 모아두었다가
# admin에서 옮기며, 그 전까지는 화면에 제외 금액으로 명시한다.
UNCLASSIFIED_ASSET_CLASS_ID = "unclassified"

ACCOUNT_TYPES = (
    ("brokerage", "종합위탁"),
    ("isa", "ISA"),
    ("pension", "개인연금"),
    ("retirement", "퇴직연금"),
)

DOCUMENT_TYPES = (
    ("balance", "잔고"),
    ("cash", "예수금"),
    ("trade", "거래"),
    ("transfer", "입출금"),
)

IMPORT_STATUSES = (
    ("success", "성공"),
    ("incomplete", "불완전"),
    ("failed", "실패"),
)

# 부호는 계좌 순자산 기준이다. 입금·배당·이자는 양수, 출금·수수료·세금은 음수로
# 저장한다. 매수·매도는 계좌 안에서 현금과 종목이 자리를 바꾸는 것이라 순자산을
# 바꾸지 않는다(금액은 기록하되 `is_external`이 False다).
FLOW_TYPES = (
    ("deposit", "입금"),
    ("withdrawal", "출금"),
    ("dividend", "배당"),
    ("interest", "이자"),
    ("fee", "수수료"),
    ("tax", "세금"),
    ("buy", "매수"),
    ("sell", "매도"),
    ("transfer_in", "계좌 간 입고"),
    ("transfer_out", "계좌 간 출고"),
)

# 수익률의 분모를 조정하는 것은 실제 외부 입출금뿐이다. 매매와 포함 계좌 사이
# 이체는 내부 이동이고, 배당·이자·수수료·세금은 투자성과다.
EXTERNAL_FLOW_TYPES = frozenset({"deposit", "withdrawal"})


def _validate_masked_account_number(value: str) -> None:
    """계좌번호 원문이 DB에 들어오는 것을 막는다.

    마스킹은 수집 단계의 책임이지만, 실수로 원문이 넘어오면 admin·화면·로그
    어디로든 새어나간다. 자릿수만 보고 거르는 값싼 방어선이다.
    """
    digits = [character for character in value if character.isdigit()]
    if len(digits) > 6 and "*" not in value:
        raise ValidationError("계좌번호는 마스킹한 형태로만 저장합니다.")


class AssetClass(models.Model):
    """사용자 자산분류. 목표 비중과 국민연금 공통분류가 붙는 단위다."""

    id = models.SlugField("분류 ID", primary_key=True, max_length=40)
    name = models.CharField("이름", max_length=50, unique=True)
    # 비어 있으면 국민연금 비교에서 빠진다. 미분류가 그런 경우다.
    benchmark_category = models.CharField(
        "국민연금 공통분류", max_length=20, blank=True, choices=BENCHMARK_CATEGORIES
    )
    display_order = models.PositiveSmallIntegerField("표시 순서", default=100)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)
    updated_at = models.DateTimeField("수정 시각", auto_now=True)

    class Meta:
        ordering = ("display_order", "name")
        verbose_name = "자산분류"
        verbose_name_plural = "자산분류"

    @property
    def is_unclassified(self) -> bool:
        return self.pk == UNCLASSIFIED_ASSET_CLASS_ID

    def __str__(self) -> str:
        return self.name


class InvestmentAccount(models.Model):
    """수집 대상 계좌 하나. `required`가 그날 스냅샷의 완결 조건을 정한다."""

    id = models.SlugField("계좌 ID", primary_key=True, max_length=40)
    institution = models.CharField("금융기관", max_length=50, default="KB증권")
    alias = models.CharField("별칭", max_length=50)
    masked_number = models.CharField(
        "마스킹 계좌번호",
        max_length=40,
        blank=True,
        validators=[_validate_masked_account_number],
    )
    account_type = models.CharField("계좌 유형", max_length=20, choices=ACCOUNT_TYPES)
    required = models.BooleanField("완전 수집 필수", default=True)
    active = models.BooleanField("사용", default=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)
    updated_at = models.DateTimeField("수정 시각", auto_now=True)

    class Meta:
        ordering = ("account_type", "alias")
        verbose_name = "투자 계좌"
        verbose_name_plural = "투자 계좌"

    def __str__(self) -> str:
        return self.alias


class Instrument(models.Model):
    """종목 하나. 현금·예수금도 `is_cash` 종목으로 같은 표에 들어간다."""

    # 화면에 종목코드가 없으면 수집기가 종목명에서 슬러그를 만든다. 한글이
    # 그대로 들어오므로 unicode 슬러그를 허용한다.
    code = models.SlugField(
        "종목코드", primary_key=True, max_length=40, allow_unicode=True
    )
    name = models.CharField("종목명", max_length=100)
    currency = models.CharField("통화", max_length=3, default="KRW")
    asset_class = models.ForeignKey(
        AssetClass,
        on_delete=models.PROTECT,
        related_name="instruments",
        verbose_name="자산분류",
    )
    # 채워두면 자산분류의 공통분류보다 이 값이 우선한다. 같은 분류 안에서 한
    # 종목만 다르게 봐야 할 때 쓴다.
    benchmark_category = models.CharField(
        "국민연금 공통분류 (종목 지정)",
        max_length=20,
        blank=True,
        choices=BENCHMARK_CATEGORIES,
    )
    is_cash = models.BooleanField("현금성", default=False)
    # 수집기가 닿지 않는 자산의 시세를 어디서 가져올지. `업체:심볼` 형식이며
    # 지금은 `upbit:KRW-BTC`처럼 업비트만 안다. 비어 있으면 시세를 찾지 않는다.
    price_source = models.CharField("시세 출처", max_length=64, blank=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)
    updated_at = models.DateTimeField("수정 시각", auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "종목"
        verbose_name_plural = "종목"

    @property
    def effective_benchmark_category(self) -> str:
        return self.benchmark_category or self.asset_class.benchmark_category

    def __str__(self) -> str:
        return self.name


class ImportRun(models.Model):
    """계좌 하나의 자료 하나를 받아들인 기록.

    `file_hash`는 같은 다운로드를 다시 넘겼는지 판별하고, `(계좌, 자료종류,
    기준일)`은 같은 날 다시 받은 자료가 덮어쓸 대상을 정한다.
    """

    as_of = models.DateField("기준일", db_index=True)
    account = models.ForeignKey(
        InvestmentAccount,
        on_delete=models.PROTECT,
        related_name="import_runs",
        verbose_name="계좌",
    )
    document_type = models.CharField("자료 종류", max_length=20, choices=DOCUMENT_TYPES)
    file_hash = models.CharField("파일 해시", max_length=64)
    source_name = models.CharField("원본 파일명", max_length=200, blank=True)
    row_count = models.PositiveIntegerField("행 수", default=0)
    status = models.CharField(
        "상태", max_length=20, choices=IMPORT_STATUSES, default="success"
    )
    error = models.TextField("오류", blank=True)
    created_at = models.DateTimeField("기록 시각", auto_now_add=True)

    class Meta:
        ordering = ("-as_of", "account_id", "document_type")
        verbose_name = "수집 실행"
        verbose_name_plural = "수집 실행"
        constraints = [
            models.UniqueConstraint(
                fields=("account", "document_type", "as_of"),
                name="unique_import_per_account_document_date",
            ),
            models.UniqueConstraint(
                fields=("account", "document_type", "file_hash"),
                name="unique_import_per_account_document_hash",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.as_of} {self.account_id} {self.get_document_type_display()}"


class ManualHolding(models.Model):
    """사람이 admin에 넣는 보유 수량.

    KB 밖의 코인처럼 [1285]에 나오지 않는 자산이다. **수량만 사람이 정하고
    가격은 매일 시세에서 가져온다** - 수량은 자주 바뀌지 않고 가격은 매일
    바뀌므로 이렇게 나누는 편이 손이 덜 간다.

    여기 적은 수량으로 매일 `PositionSnapshot`을 만들기 때문에, 사고팔면 이
    숫자를 고쳐야 한다.
    """

    account = models.ForeignKey(
        InvestmentAccount,
        on_delete=models.PROTECT,
        related_name="manual_holdings",
        verbose_name="계좌",
    )
    instrument = models.ForeignKey(
        Instrument,
        on_delete=models.PROTECT,
        related_name="manual_holdings",
        verbose_name="종목",
    )
    quantity = models.DecimalField("보유수량", max_digits=20, decimal_places=8)
    cost_amount = models.DecimalField(
        "매입금액", max_digits=18, decimal_places=2, null=True, blank=True
    )
    active = models.BooleanField("사용", default=True)
    note = models.CharField("메모", max_length=200, blank=True)
    updated_at = models.DateTimeField("수정 시각", auto_now=True)

    class Meta:
        ordering = ("account_id", "instrument_id")
        verbose_name = "직접 입력 보유"
        verbose_name_plural = "직접 입력 보유"
        constraints = [
            models.UniqueConstraint(
                fields=("account", "instrument"), name="unique_manual_holding"
            )
        ]

    def __str__(self) -> str:
        return f"{self.account_id} {self.instrument_id} {self.quantity}"


class PositionSnapshot(models.Model):
    """기준일 하나, 계좌 하나, 종목 하나의 보유 상태.

    금액은 원 단위 원본을 보존한다. 만원 단위 반올림은 화면에서만 한다.
    """

    as_of = models.DateField("기준일", db_index=True)
    account = models.ForeignKey(
        InvestmentAccount,
        on_delete=models.PROTECT,
        related_name="positions",
        verbose_name="계좌",
    )
    instrument = models.ForeignKey(
        Instrument,
        on_delete=models.PROTECT,
        related_name="positions",
        verbose_name="종목",
    )
    import_run = models.ForeignKey(
        ImportRun,
        on_delete=models.SET_NULL,
        related_name="positions",
        verbose_name="수집 실행",
        null=True,
        blank=True,
    )
    quantity = models.DecimalField("보유수량", max_digits=20, decimal_places=8)
    average_cost = models.DecimalField(
        "평균단가", max_digits=18, decimal_places=4, null=True, blank=True
    )
    cost_amount = models.DecimalField(
        "매입금액", max_digits=18, decimal_places=2, null=True, blank=True
    )
    price = models.DecimalField(
        "현재가", max_digits=18, decimal_places=4, null=True, blank=True
    )
    market_value = models.DecimalField("평가금액", max_digits=18, decimal_places=2)
    unrealized_pl = models.DecimalField(
        "평가손익", max_digits=18, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField("통화", max_length=3, default="KRW")
    # 해외주식은 H-able이 준 원화평가액을 그대로 쓴다. 환율을 임의로 섞지
    # 않는다 — 없으면 수집기가 그 계좌를 실패로 넘긴다.
    market_value_krw = models.DecimalField(
        "원화평가액", max_digits=18, decimal_places=2
    )

    class Meta:
        ordering = ("-as_of", "account_id", "instrument_id")
        verbose_name = "보유 스냅샷"
        verbose_name_plural = "보유 스냅샷"
        indexes = [models.Index(fields=("as_of", "account"))]
        constraints = [
            models.UniqueConstraint(
                fields=("as_of", "account", "instrument"),
                name="unique_position_per_day_account_instrument",
            )
        ]

    def __str__(self) -> str:
        return f"{self.as_of} {self.instrument_id}"


class CashFlow(models.Model):
    """계좌 하나의 현금 이동 한 건.

    `is_external`만이 수익률 분모를 움직인다. 나머지는 전부 투자성과 또는
    내부 이동으로 계산에 들어간다.
    """

    occurred_on = models.DateField("발생일", db_index=True)
    account = models.ForeignKey(
        InvestmentAccount,
        on_delete=models.PROTECT,
        related_name="cash_flows",
        verbose_name="계좌",
    )
    instrument = models.ForeignKey(
        Instrument,
        on_delete=models.PROTECT,
        related_name="cash_flows",
        verbose_name="종목",
        null=True,
        blank=True,
    )
    import_run = models.ForeignKey(
        ImportRun,
        on_delete=models.SET_NULL,
        related_name="cash_flows",
        verbose_name="수집 실행",
        null=True,
        blank=True,
    )
    flow_type = models.CharField("구분", max_length=20, choices=FLOW_TYPES)
    amount = models.DecimalField("금액", max_digits=18, decimal_places=2)
    # 매매와 입출고에만 있다. 실현손익을 평균단가로 계산하려면 수량과 단가가
    # 필요한데, 금액만으로는 몇 주를 얼마에 샀는지 알 수 없다.
    quantity = models.DecimalField(
        "수량", max_digits=20, decimal_places=8, null=True, blank=True
    )
    unit_price = models.DecimalField(
        "단가", max_digits=18, decimal_places=4, null=True, blank=True
    )
    currency = models.CharField("통화", max_length=3, default="KRW")
    amount_krw = models.DecimalField("원화금액", max_digits=18, decimal_places=2)
    is_external = models.BooleanField("외부 현금흐름", default=False)
    memo = models.CharField("메모", max_length=200, blank=True)
    # 수집기가 원본 행에서 만든 안정적인 키. 겹치는 거래기간을 다시 받아도
    # 같은 행이 두 번 저장되지 않게 한다.
    external_key = models.CharField("원본 키", max_length=100)
    created_at = models.DateTimeField("기록 시각", auto_now_add=True)

    class Meta:
        ordering = ("-occurred_on", "account_id", "id")
        verbose_name = "현금흐름"
        verbose_name_plural = "현금흐름"
        indexes = [models.Index(fields=("occurred_on", "account"))]
        constraints = [
            models.UniqueConstraint(
                fields=("account", "external_key"),
                name="unique_cash_flow_per_account_key",
            )
        ]

    def __str__(self) -> str:
        return f"{self.occurred_on} {self.get_flow_type_display()}"


class PortfolioTarget(models.Model):
    """적용일 하나의 자산분류별 목표 비중(%).

    같은 적용일의 활성 행 합계가 100%일 때만 화면이 그 세트를 쓴다. 합계가
    맞지 않으면 리밸런싱을 계산하지 않고 그 사실을 화면에 적는다.
    """

    effective_from = models.DateField("적용 시작일", db_index=True)
    asset_class = models.ForeignKey(
        AssetClass,
        on_delete=models.PROTECT,
        related_name="targets",
        verbose_name="자산분류",
    )
    target_percent = models.DecimalField("목표 비중(%)", max_digits=6, decimal_places=3)
    active = models.BooleanField("사용", default=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)
    updated_at = models.DateTimeField("수정 시각", auto_now=True)

    class Meta:
        ordering = ("-effective_from", "asset_class_id")
        verbose_name = "목표 비중"
        verbose_name_plural = "목표 비중"
        constraints = [
            models.UniqueConstraint(
                fields=("effective_from", "asset_class"),
                name="unique_target_per_date_asset_class",
            ),
            models.CheckConstraint(
                condition=Q(target_percent__gte=0) & Q(target_percent__lte=100),
                name="target_percent_within_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.effective_from} {self.asset_class_id} {self.target_percent}%"


class BenchmarkAllocation(models.Model):
    """국민연금 기준 포트폴리오 한 줄.

    원본 분류(국내채권/해외채권처럼 세분화된 것)와 원본 비중을 그대로 남기고,
    비교 화면에서만 공통분류로 합치고 100%로 정규화한다.
    """

    as_of = models.DateField("기준일", db_index=True)
    source_category = models.CharField("원본 분류", max_length=50)
    benchmark_category = models.CharField(
        "공통분류", max_length=20, choices=BENCHMARK_CATEGORIES
    )
    source_percent = models.DecimalField("원본 비중(%)", max_digits=6, decimal_places=3)
    source = models.CharField("출처", max_length=200, blank=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        ordering = ("-as_of", "source_category")
        verbose_name = "국민연금 기준 비중"
        verbose_name_plural = "국민연금 기준 비중"
        constraints = [
            models.UniqueConstraint(
                fields=("as_of", "source_category"),
                name="unique_benchmark_per_date_category",
            )
        ]

    def __str__(self) -> str:
        return f"{self.as_of} {self.source_category} {self.source_percent}%"


class DailyPortfolioMetric(models.Model):
    """완전 스냅샷이 있는 날 하나의 현금흐름 보정 성과.

    `index_value`는 외부 입출금을 제거한 누적 성과지수다. MDD는 평가액이
    아니라 이 지수의 직전 고점 대비 하락률에서 나온다 — 입금이 많은 달에는
    평가액만 보면 낙폭이 사라져 보이기 때문이다.
    """

    as_of = models.DateField("기준일", primary_key=True)
    market_value = models.DecimalField("평가액", max_digits=18, decimal_places=2)
    external_flow = models.DecimalField(
        "당일 순외부입금", max_digits=18, decimal_places=2, default=Decimal("0")
    )
    cumulative_external_flow = models.DecimalField(
        "누적 순외부입금", max_digits=18, decimal_places=2, default=Decimal("0")
    )
    investment_pl = models.DecimalField(
        "누적 투자손익", max_digits=18, decimal_places=2, default=Decimal("0")
    )
    daily_return = models.DecimalField(
        "일간 수익률", max_digits=12, decimal_places=8, default=Decimal("0")
    )
    cumulative_return = models.DecimalField(
        "누적 수익률", max_digits=12, decimal_places=8, default=Decimal("0")
    )
    index_value = models.DecimalField(
        "성과지수", max_digits=18, decimal_places=8, default=Decimal("1")
    )
    peak_index = models.DecimalField(
        "성과지수 고점", max_digits=18, decimal_places=8, default=Decimal("1")
    )
    drawdown = models.DecimalField(
        "현재 낙폭", max_digits=12, decimal_places=8, default=Decimal("0")
    )
    max_drawdown = models.DecimalField(
        "MDD", max_digits=12, decimal_places=8, default=Decimal("0")
    )
    computed_at = models.DateTimeField("계산 시각", auto_now=True)

    class Meta:
        ordering = ("-as_of",)
        verbose_name = "일별 성과"
        verbose_name_plural = "일별 성과"

    def __str__(self) -> str:
        return f"{self.as_of}"
