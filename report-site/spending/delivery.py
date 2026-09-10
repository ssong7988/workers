"""카드 소비 요약 한 통을 카카오톡으로 보낸다.

`portfolio/delivery.py`와 같은 규칙이다 — **이미지는 보내지 않고, 텍스트 한
통에 버튼 두 개만 붙인다.** 버튼은 리포트 서버가 그 청구월을 실제로 서빙하고
있을 때만 붙인다. 낡은 화면으로 보내는 버튼은 없느니만 못하다.

카카오 어댑터는 `properties/notifier.py`의 것을 그대로 쓴다. 카카오 모듈을
불러오는 공용 배선이라 도메인마다 두 벌로 만들 이유가 없다.

보내는 시점은 명세서가 도착한 달에 한 번이다. 수집기가 새 청구월을 저장한
직후 `send_spending_digest`를 부르며, 같은 달을 두 번 보내지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from properties.notifier import KakaoNotifier
from properties.publish import is_public_report_url

from .analysis import (
    category_rows,
    group_rows,
    month_view,
    trailing_average,
)
from .display import man_text, month_text, signed_percent_text
from .models import Statement


# 카카오 기본 텍스트 템플릿의 본문 한도.
TEXT_LIMIT = 200
REPORT_BUTTON = "소비 리포트"
TRANSACTIONS_BUTTON = "전체 거래"


class SpendingDeliveryError(RuntimeError):
    """보낼 것이 없거나 보내지 못했을 때."""


@dataclass(frozen=True)
class Digest:
    billing_month: str
    message: str
    buttons: list[tuple[str, str]]

    @property
    def has_buttons(self) -> bool:
        return bool(self.buttons)


def build_digest(billing_month: str | None = None) -> Digest:
    """보낼 요약과 버튼을 만든다. 저장된 명세서가 없으면 거절한다."""
    view = month_view(billing_month)
    if view is None:
        raise SpendingDeliveryError(
            "저장된 명세서가 아직 없습니다. spending-analyzer가 먼저 보내야 합니다."
        )

    statement = view.statement
    totals = view.totals
    current = next((item for item in totals if item.month == statement.billing_month), None)
    average = trailing_average(totals)

    lines = [f"💳 {month_text(statement.billing_month)} 카드 {man_text(view.total)}원"]

    parts = []
    if current and current.delta is not None:
        parts.append(f"전월 {signed_percent_text(current.percent)}")
    # 명세서가 한 통뿐이면 평균이 이번 달 자신이라 "평균 대비 0"이 된다.
    if average and len(totals) > 1:
        parts.append(f"평균 대비 {man_text(view.total - average)}")
    if parts:
        lines.append(" · ".join(parts))

    # 카테고리 열여섯 개는 200자에 담기지도 않고 담아도 성격이 안 보인다.
    # 대분류는 다섯 줄이면 한 달이 어떤 달이었는지 말해 준다.
    groups = [row for row in group_rows(statement, view.previous) if row["total"] > 0]
    groups.sort(key=lambda row: -row["total"])
    for chunk in (groups[:3], groups[3:]):
        if chunk:
            lines.append(
                " · ".join(f"{row['name']} {man_text(row['total'])}" for row in chunk)
            )

    unclassified = next(
        (
            row
            for row in category_rows(statement, view.previous)
            if row["unclassified"] and row["total"] > 0
        ),
        None,
    )
    if unclassified:
        # 미분류가 남아 있으면 대분류 숫자를 곧이곧대로 읽으면 안 된다.
        lines.append(f"미분류 {man_text(unclassified['total'])} 포함")

    message = "\n".join(lines)[:TEXT_LIMIT]
    return Digest(
        billing_month=statement.billing_month,
        message=message,
        buttons=_buttons(statement),
    )


def _buttons(statement: Statement) -> list[tuple[str, str]]:
    """공개 주소가 설정돼 있을 때만 버튼을 붙인다.

    주식 쪽은 공개 주소를 실제로 열어 기준일이 서빙되는지까지 확인하지만,
    여기서는 그럴 수 없다. 두 화면 모두 admin 로그인을 요구하므로 인증 없이
    가져오면 로그인 화면이 돌아오고, 그것으로는 청구월이 맞는지 알 수 없다.
    대신 저장이 성공한 뒤에만 요약을 보내므로 화면은 이미 그 달을 들고 있다.
    """
    report = getattr(settings, "SPENDING_REPORT_URL", "")
    transactions = getattr(settings, "SPENDING_TRANSACTIONS_URL", "")
    if not report or not transactions:
        return []
    if not is_public_report_url(report):
        return []
    return [(REPORT_BUTTON, report), (TRANSACTIONS_BUTTON, transactions)]


def send_digest(
    billing_month: str | None = None, notifier: KakaoNotifier | None = None
) -> str:
    """요약 한 통을 보낸다. 무엇을 보냈는지 사람이 읽을 문장으로 돌려준다."""
    digest = build_digest(billing_month)
    sender = notifier or KakaoNotifier()
    try:
        sender.send_links(digest.message, digest.buttons)
    except Exception as exc:  # 카카오 모듈이 올리는 예외 종류가 넓다
        raise SpendingDeliveryError(f"카카오 전송에 실패했습니다: {exc}") from exc

    if digest.has_buttons:
        return f"{digest.billing_month} 소비 요약을 버튼 2개와 함께 보냈습니다."
    return (
        f"{digest.billing_month} 소비 요약을 보냈습니다. 버튼은 붙이지 않았습니다 - "
        "공개 주소가 설정되지 않았거나 로컬 주소입니다."
    )
