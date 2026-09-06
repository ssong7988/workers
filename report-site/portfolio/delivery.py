"""금융자산 요약 한 통을 카카오톡으로 보낸다.

부동산 쪽 `properties/delivery.py`와 같은 규칙을 따른다 - **이미지는 보내지
않고, 텍스트 한 통에 버튼 두 개만 붙인다.** 버튼은 리포트 서버가 그 기준일을
실제로 서빙하고 있을 때만 붙인다. 낡은 화면으로 보내는 버튼은 없느니만 못하다.

카카오 어댑터는 `properties/notifier.py`의 것을 그대로 쓴다. 그건 부동산 도메인
지식이 아니라 카카오 모듈을 불러오는 공용 배선이라 두 벌로 만들 이유가 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum

from properties.notifier import KakaoNotifier
from properties.publish import is_public_report_url

from .allocation import build_allocation
from .display import man_won_text, percent_text, signed_man_won_text, signed_percent_text
from .importing import latest_complete_date
from .models import DailyPortfolioMetric, PositionSnapshot


# 카카오 기본 텍스트 템플릿의 본문 한도.
TEXT_LIMIT = 200
ALLOCATION_BUTTON = "비중·리밸런싱"
PERFORMANCE_BUTTON = "수익률·MDD"


class StockDeliveryError(RuntimeError):
    """보낼 것이 없거나 보내지 못했을 때."""


@dataclass(frozen=True)
class Digest:
    as_of: date
    message: str
    buttons: list[tuple[str, str]]

    @property
    def has_buttons(self) -> bool:
        return bool(self.buttons)


def unrealized_totals(as_of: date) -> tuple[Decimal, Decimal | None]:
    """매입 대비 평가손익과 그 비율.

    `DailyPortfolioMetric`이 들고 있는 수익률은 **수집을 시작한 뒤**의 성과라
    첫날은 정의상 0이다. 그것만 보내면 수익이 없는 것처럼 읽히므로, 증권사
    화면과 같은 누적 평가손익을 함께 보낸다.

    매입금액이 있는 줄만 쓴다. 평가액과 매입액을 같은 줄 집합에서 끊어야
    비율이 섞이지 않는다.
    """
    totals = PositionSnapshot.objects.filter(
        as_of=as_of, cost_amount__isnull=False
    ).aggregate(cost=Sum("cost_amount"), value=Sum("market_value_krw"))
    cost = totals["cost"] or Decimal("0")
    value = totals["value"] or Decimal("0")
    if cost <= Decimal("0"):
        return Decimal("0"), None
    profit = value - cost
    return profit, profit / cost


def _largest_rebalance(rows) -> str:
    """리밸런싱이 가장 큰 항목 한 줄. 목표가 없으면 빈 문자열."""
    candidates = [row for row in rows if row.rebalance_value is not None]
    if not candidates:
        return ""
    row = max(candidates, key=lambda item: abs(item.rebalance_value))
    if row.rebalance_value == Decimal("0"):
        return ""
    return f"{row.name} {signed_man_won_text(row.rebalance_value)}"


def build_digest(as_of: date | None = None) -> Digest:
    """보낼 요약과 버튼을 만든다. 완전 수집일이 없으면 거절한다."""
    as_of = as_of or latest_complete_date()
    if as_of is None:
        raise StockDeliveryError(
            "완전한 수집 결과가 아직 없습니다. 필수 계좌의 잔고가 모두 들어와야 보냅니다."
        )
    metric = DailyPortfolioMetric.objects.filter(as_of=as_of).first()
    if metric is None:
        raise StockDeliveryError(
            f"{as_of}의 성과가 계산돼 있지 않습니다. manage.py rebuild_portfolio_metrics를 먼저 실행하세요."
        )

    view = build_allocation(as_of)
    unrealized, unrealized_ratio = unrealized_totals(as_of)
    lines = [
        f"💰 금융자산 {as_of:%Y.%m.%d}",
        f"평가 {man_won_text(metric.market_value)} · "
        f"평가손익 {signed_man_won_text(unrealized)} "
        f"({signed_percent_text(unrealized_ratio)})",
        f"수집후 {signed_percent_text(metric.cumulative_return)} · "
        f"MDD {percent_text(metric.max_drawdown, digits=2)} · "
        f"낙폭 {percent_text(metric.drawdown, digits=2)}",
    ]
    rebalance = _largest_rebalance(view.rows)
    if rebalance:
        lines.append(f"리밸런싱 {rebalance}")
    if view.unclassified_value > Decimal("0"):
        lines.append(f"미분류 {man_won_text(view.unclassified_value)} 제외")

    message = "\n".join(lines)[:TEXT_LIMIT]
    return Digest(as_of=as_of, message=message, buttons=_buttons(as_of))


def _buttons(as_of: date) -> list[tuple[str, str]]:
    """두 화면이 그 기준일을 실제로 서빙할 때만 버튼을 붙인다."""
    allocation = settings.STOCK_ALLOCATION_URL
    performance = settings.STOCK_PERFORMANCE_URL
    if not allocation or not performance:
        return []
    if not is_public_report_url(allocation):
        return []
    if not _serves(allocation, as_of):
        return []
    return [(ALLOCATION_BUTTON, allocation), (PERFORMANCE_BUTTON, performance)]


def _serves(url: str, as_of: date, timeout: float = 20.0) -> bool:
    """공개 주소가 그 기준일을 내보내고 있는지 확인한다."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "stock-digest"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False
    return f'data-as-of="{as_of.isoformat()}"' in html


def send_digest(as_of: date | None = None, notifier: KakaoNotifier | None = None) -> str:
    """요약 한 통을 보낸다. 무엇을 보냈는지 사람이 읽을 문장으로 돌려준다."""
    digest = build_digest(as_of)
    sender = notifier or KakaoNotifier()
    try:
        if digest.has_buttons:
            sender.send_links(digest.message, digest.buttons)
        else:
            # 버튼 없이라도 숫자는 보낸다. 다만 왜 없는지 남긴다.
            sender.send_links(digest.message, [])
    except Exception as exc:  # 카카오 모듈이 올리는 예외 종류가 넓다
        raise StockDeliveryError(f"카카오 전송에 실패했습니다: {exc}") from exc
    if digest.has_buttons:
        return f"{digest.as_of} 요약을 버튼 2개와 함께 보냈습니다."
    return (
        f"{digest.as_of} 요약을 보냈습니다. 버튼은 붙이지 않았습니다 - "
        "공개 주소가 아직 그 기준일을 서빙하지 않습니다."
    )
