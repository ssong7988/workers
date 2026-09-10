"""카드 소비 두 화면을 PostgreSQL에서 바로 렌더링한다.

금융자산 화면과 같은 구조다 - 빌드도 배포도 없고, 요청마다 DB를 읽어 그린다.
차트 좌표는 서버에서 만들어 내려보낸다.

두 화면 모두 admin 로그인을 요구한다. 가맹점 하나하나가 그대로 보이는 화면이라
경로 토큰만으로는 부족하고, Funnel이 인터넷에 열어두는 주소이기도 하다.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from spending.analysis import (
    category_rows,
    group_rows,
    group_series,
    installment_outlook,
    month_view,
    monthly_totals,
    payment_type_rows,
    top_merchants,
    trailing_average,
    unclassified_merchants,
)
from spending.display import man_text, month_text, signed_percent_text, won_text
from spending.models import SpendingCategory

MONTH_TREND_LIMIT = 12


def _links(page: str) -> dict[str, str]:
    return {
        "page": page,
        "report_url": f"{settings.SPENDING_REPORT_URL_PATH}/",
        "transactions_url": f"{settings.SPENDING_TRANSACTIONS_URL_PATH}/",
    }


def _trend(totals, latest_month: str) -> dict | None:
    """막대 좌표를 서버에서 만든다. 브라우저는 차트 라이브러리를 받지 않는다."""
    rows = totals[-MONTH_TREND_LIMIT:]
    if not rows:
        return None
    ceiling = max(row.total for row in rows) or 1
    width, height = 720, 200
    slot = width / len(rows)
    bar = min(48.0, slot - 14)
    bars = []
    for index, row in enumerate(rows):
        length = height * row.total / ceiling
        bars.append(
            {
                "x": slot * (index + 0.5) - bar / 2,
                "y": height - length,
                "width": bar,
                "height": length,
                "label": row.month[2:].replace("-", "."),
                "centre": slot * (index + 0.5),
                "value": man_text(row.total),
                "current": row.month == latest_month,
                "title": f"{row.month} {won_text(row.total)} · {row.count}건",
            }
        )
    average = trailing_average(totals)
    return {
        "width": width,
        "height": height,
        "bars": bars,
        "average_y": height - (height * average / ceiling) if average else None,
        "average_label": man_text(average),
    }


def _group_trend() -> dict | None:
    """달마다 대분류 구성을 쌓은 막대.

    한 달만 있으면 추이가 아니라 같은 정보의 반복이라 그리지 않는다.
    """
    series = group_series()
    if len(series["months"]) < 2:
        return None

    width, height = 720, 190
    ceiling = max((month["total"] for month in series["months"]), default=0) or 1
    slot = width / len(series["months"])
    bar = min(54.0, slot - 16)

    columns = []
    for index, month in enumerate(series["months"]):
        x = slot * (index + 0.5) - bar / 2
        top = height - height * month["total"] / ceiling
        pieces = []
        for part in month["parts"]:
            if not part["total"]:
                continue
            piece_height = height * part["total"] / ceiling
            pieces.append(
                {
                    "x": x,
                    "y": top,
                    "width": bar,
                    "height": piece_height,
                    "color": part["color"],
                    "title": f"{month['month']} {part['name']} {won_text(part['total'])}",
                }
            )
            top += piece_height
        columns.append(
            {
                "pieces": pieces,
                "label": month["month"][2:].replace("-", "."),
                "centre": slot * (index + 0.5),
            }
        )
    return {"width": width, "height": height, "columns": columns}


@staff_member_required
def report(request: HttpRequest) -> HttpResponse:
    view = month_view(request.GET.get("month"))
    if view is None:
        return render(request, "report/spending_empty.html", _links("report"))

    statement = view.statement
    totals = view.totals
    current = next((item for item in totals if item.month == statement.billing_month), None)
    average = trailing_average(totals)
    categories = category_rows(statement, view.previous)
    # 직전 달이 없으면 증감이 아니라 이번 달 금액 그 자체다. 0에서 늘어난 것으로
    # 그리면 첫 달이 전부 급증한 것처럼 읽힌다.
    changed = (
        sorted(
            (row for row in categories if row["delta"]),
            key=lambda row: -abs(row["delta"]),
        )[:8]
        if view.previous
        else []
    )
    ceiling = max((row["total"] for row in categories), default=0) or 1
    delta_ceiling = max((abs(row["delta"]) for row in changed), default=0) or 1

    groups = [row for row in group_rows(statement, view.previous) if row["total"] > 0]
    group_colors = {
        category.pk: category.group.color
        for category in SpendingCategory.objects.select_related("group")
        if category.group
    }
    # 한 줄짜리 100% 막대. 조각 폭이 곧 비중이라 눈금이 필요 없다.
    offset = 0.0
    segments = []
    for row in groups:
        width = row["share"] * 100
        segments.append({**row, "x": offset, "width": width, "percent": f"{width:.0f}%"})
        offset += width

    context = {
        **_links("report"),
        "statement": statement,
        "groups": [
            {
                **row,
                "amount": won_text(row["total"]),
                "percent": f"{row['share'] * 100:.1f}%",
                "delta_text": man_text(row["delta"]) if row["previous"] else "",
                "up": row["delta"] > 0,
            }
            for row in groups
        ],
        "segments": segments,
        "group_trend": _group_trend(),
        "month_label": month_text(statement.billing_month),
        "total": statement.parsed_total_won,
        "total_text": won_text(statement.parsed_total_won),
        "count": statement.transactions.count(),
        "delta_text": man_text(current.delta) if current and current.delta is not None else "—",
        "percent_text": signed_percent_text(current.percent) if current else "—",
        "delta_up": bool(current and current.delta and current.delta > 0),
        "average_text": won_text(average),
        "gap_text": man_text(statement.parsed_total_won - average) if average else "—",
        "gap_up": bool(average and statement.parsed_total_won > average),
        # 달이 하나뿐이면 추이가 아니라 막대 한 개다. 대분류 추이와 같은 기준.
        "trend": _trend(totals, statement.billing_month) if len(totals) > 1 else None,
        "categories": [
            {
                **row,
                "bar": 100 * row["total"] / ceiling,
                "amount": won_text(row["total"]),
                # 카테고리 막대에 대분류 색을 쓴다. 어느 성격의 지출인지 표를
                # 따라 내려가지 않고도 보인다.
                "color": group_colors.get(row["id"], "#16a34a"),
            }
            for row in categories
            if row["total"] > 0
        ],
        "changes": [
            {
                **row,
                "bar": 100 * abs(row["delta"]) / delta_ceiling,
                "amount": f"{row['delta']:+,}원",
                "up": row["delta"] > 0,
            }
            for row in changed
        ],
        "payment_types": [
            {**row, "amount": won_text(row["total"]), "percent": f"{row['share'] * 100:.0f}%"}
            for row in payment_type_rows(statement)
        ],
        "installments": installment_outlook(statement),
        "merchants": [
            {**row, "amount": won_text(row["total"]), "mean": won_text(row["average"])}
            for row in top_merchants(statement)
        ],
        "unclassified": [
            {**row, "amount": won_text(row["total"])} for row in unclassified_merchants()
        ],
        "months": [
            {"month": row.month, "label": month_text(row.month)} for row in reversed(totals)
        ],
    }
    return render(request, "report/spending_report.html", context)


@staff_member_required
def transactions(request: HttpRequest) -> HttpResponse:
    view = month_view(request.GET.get("month"))
    if view is None:
        return render(request, "report/spending_empty.html", _links("transactions"))

    statement = view.statement
    rows = statement.transactions.select_related("category").order_by("-billed_won")
    context = {
        **_links("transactions"),
        "statement": statement,
        "month_label": month_text(statement.billing_month),
        "total_text": won_text(statement.parsed_total_won),
        "count": rows.count(),
        "rows": [
            {
                "used_at": item.used_at,
                "merchant": item.merchant,
                "category": item.category.name,
                "unclassified": item.category.is_unclassified,
                "payment": item.get_payment_type_display(),
                "installment": (
                    f"{item.installment_seq}/{item.installment_months}"
                    if item.is_installment
                    else ""
                ),
                "card": item.card_last4,
                "amount": won_text(item.billed_won),
            }
            for item in rows
        ],
        "months": [
            {"month": row.month, "label": month_text(row.month)}
            for row in reversed(monthly_totals())
        ],
    }
    return render(request, "report/spending_transactions.html", context)
