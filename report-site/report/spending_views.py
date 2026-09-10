"""카드 소비 두 화면을 PostgreSQL에서 바로 렌더링한다.

금융자산 화면과 같은 구조다 - 빌드도 배포도 없고, 요청마다 DB를 읽어 그린다.
차트 좌표는 서버에서 만들어 내려보낸다.

두 화면 모두 admin 로그인을 요구한다. 가맹점 하나하나가 그대로 보이는 화면이라
경로 토큰만으로는 부족하고, Funnel이 인터넷에 열어두는 주소이기도 하다.
"""

from __future__ import annotations

import math

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

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
from spending.models import SpendingCategory, Transaction

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


PIE_SIZE = 260
PIE_RADIUS = 110
PIE_HOLE = 62
# 이 비중보다 작은 조각은 안에 %를 적지 않는다. 글자가 조각 밖으로 삐져나온다.
PIE_LABEL_MIN_SHARE = 0.06


def _pie(groups: list[dict]) -> dict | None:
    """대분류 구성을 도넛으로.

    조각 순서는 큰 것부터다. 색은 대분류에 묶여 있으므로 순서를 바꿔도 같은
    성격이 달마다 같은 색으로 남는다 - 색이 순위를 따라가면 비교가 깨진다.

    가운데를 비워 총액을 넣는다. 꽉 찬 원보다 각 조각의 호 길이를 견주기 쉽고,
    합계를 따로 둘 자리가 생긴다.
    """
    if not groups:
        return None

    whole = sum(row["total"] for row in groups)
    if whole <= 0:
        return None

    centre = PIE_SIZE / 2
    slices = []
    angle = -math.pi / 2  # 12시에서 시작해 시계 방향
    for row in groups:
        share = row["total"] / whole
        sweep = share * 2 * math.pi
        end = angle + sweep

        # 한 조각이 전부일 때는 호로 원을 그릴 수 없어 원 두 개로 그린다.
        if share >= 0.999:
            slices.append({**row, "full": True, "percent": "100%"})
            break

        large = 1 if sweep > math.pi else 0
        outer_start = (centre + PIE_RADIUS * math.cos(angle), centre + PIE_RADIUS * math.sin(angle))
        outer_end = (centre + PIE_RADIUS * math.cos(end), centre + PIE_RADIUS * math.sin(end))
        inner_end = (centre + PIE_HOLE * math.cos(end), centre + PIE_HOLE * math.sin(end))
        inner_start = (centre + PIE_HOLE * math.cos(angle), centre + PIE_HOLE * math.sin(angle))
        path = (
            f"M{outer_start[0]:.2f},{outer_start[1]:.2f} "
            f"A{PIE_RADIUS},{PIE_RADIUS} 0 {large} 1 {outer_end[0]:.2f},{outer_end[1]:.2f} "
            f"L{inner_end[0]:.2f},{inner_end[1]:.2f} "
            f"A{PIE_HOLE},{PIE_HOLE} 0 {large} 0 {inner_start[0]:.2f},{inner_start[1]:.2f} Z"
        )
        middle = angle + sweep / 2
        label_radius = (PIE_RADIUS + PIE_HOLE) / 2
        slices.append(
            {
                **row,
                "full": False,
                "path": path,
                "percent": f"{share * 100:.0f}%",
                "label_x": centre + label_radius * math.cos(middle),
                "label_y": centre + label_radius * math.sin(middle) + 4,
                "show_label": share >= PIE_LABEL_MIN_SHARE,
                "title": f"{row['name']} {won_text(row['total'])} ({share * 100:.1f}%)",
            }
        )
        angle = end

    return {
        "size": PIE_SIZE,
        "centre": centre,
        "radius": PIE_RADIUS,
        "hole": PIE_HOLE,
        "slices": slices,
        "total": man_text(whole),
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

    # 비중이 큰 것부터 읽는다. 색은 대분류에 묶여 있으므로 순서를 바꿔도
    # 조각 색이 달마다 자리를 옮기지 않는다.
    groups = sorted(
        (row for row in group_rows(statement, view.previous) if row["total"] > 0),
        key=lambda row: -row["total"],
    )
    group_colors = {
        category.pk: category.group.color
        for category in SpendingCategory.objects.select_related("group")
        if category.group
    }
    pie = _pie(groups)

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
        "pie": pie,
        "group_trend": _group_trend(),
        "month_label": month_text(statement.billing_month),
        "total": view.total,
        "total_text": won_text(view.total),
        "billed_text": won_text(statement.parsed_total_won),
        "excluded_text": won_text(statement.excluded_total_won),
        "count": statement.transactions.filter(excluded=False).count(),
        "delta_text": man_text(current.delta) if current and current.delta is not None else "—",
        "percent_text": signed_percent_text(current.percent) if current else "—",
        "delta_up": bool(current and current.delta and current.delta > 0),
        "average_text": won_text(average),
        "gap_text": man_text(view.total - average) if average else "—",
        "gap_up": bool(average and view.total > average),
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
    view = month_view(request.GET.get("month") or request.POST.get("month"))
    if view is None:
        return render(request, "report/spending_empty.html", _links("transactions"))

    statement = view.statement
    if request.method == "POST":
        return _save_selection(request, statement)

    rows = statement.transactions.select_related("category").order_by("-billed_won")
    excluded_count = sum(1 for item in rows if item.excluded)
    context = {
        **_links("transactions"),
        "statement": statement,
        "month_label": month_text(statement.billing_month),
        "total_text": won_text(statement.analysed_total_won),
        "billed_text": won_text(statement.parsed_total_won),
        "excluded_count": excluded_count,
        "excluded_text": won_text(statement.excluded_total_won),
        "count": len(rows),
        "rows": [
            {
                "id": item.pk,
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
                "selected": not item.excluded,
            }
            for item in rows
        ],
        "months": [
            {"month": row.month, "label": month_text(row.month)}
            for row in reversed(monthly_totals())
        ],
    }
    return render(request, "report/spending_transactions.html", context)


def _save_selection(request: HttpRequest, statement) -> HttpResponse:
    """체크를 푼 줄을 집계에서 뺀다.

    지우지 않고 표시만 바꾼다 - 명세서의 청구총액과 대조하려면 그 줄도 그대로
    있어야 하고, 언제든 되돌릴 수 있어야 한다. 체크된 것만 폼으로 올라오므로,
    이 명세서의 줄 중 올라오지 않은 것이 곧 제외 대상이다.
    """
    keep = {int(value) for value in request.POST.getlist("keep") if value.isdigit()}
    rows = list(statement.transactions.all())
    changed = []
    for item in rows:
        excluded = item.pk not in keep
        if item.excluded != excluded:
            item.excluded = excluded
            changed.append(item)
    if changed:
        Transaction.objects.bulk_update(changed, ["excluded"])

    messages.success(
        request,
        f"{len(rows) - len(keep)}건을 집계에서 제외했습니다."
        if len(keep) < len(rows)
        else "모든 거래를 집계에 넣었습니다.",
    )
    return redirect(
        f"{settings.SPENDING_TRANSACTIONS_URL_PATH}/?month={statement.billing_month}"
    )
