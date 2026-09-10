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
    baseline_average,
    category_comparison,
    category_rows,
    group_comparison,
    group_rows,
    group_series,
    installment_outlook,
    month_view,
    monthly_totals,
    payment_type_rows,
    top_merchants,
    unclassified_merchants,
)
from spending.display import man_text, month_text, signed_percent_text, won_text
from spending.categorize import recategorize_all
from spending.models import (
    UNCLASSIFIED_CATEGORY_ID,
    MerchantRule,
    SpendingCategory,
    Transaction,
)

# 이보다 낮은 조각에는 안에 숫자를 적을 수 없다.
STACK_LABEL_MIN_HEIGHT = 15
# 가맹점 TOP에서 고를 수 있는 개수.
TOP_CHOICES = (5, 10, 20)
DEFAULT_TOP = 10
# 무엇과 견줄지. 한 화면에서 점선·요약·증감 비교가 모두 같은 창을 쓴다 -
# 기준이 자리마다 다르면 숫자끼리 이야기가 안 맞는다.
WINDOW_CHOICES = (1, 3, 6)
DEFAULT_WINDOW = 3


def _pick(request, name: str, choices: tuple[int, ...], default: int) -> int:
    """고를 수 있는 값만 받는다. 주소로 아무 숫자나 넣지 못한다."""
    try:
        value = int(request.GET.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value in choices else default


def _links(page: str) -> dict[str, str]:
    return {
        "page": page,
        "report_url": f"{settings.SPENDING_REPORT_URL_PATH}/",
        "transactions_url": f"{settings.SPENDING_TRANSACTIONS_URL_PATH}/",
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


def _group_trend(average: int, window: int, months_used: int) -> dict | None:
    """달마다의 청구액을 대분류로 쌓은 막대.

    한 달만 있으면 추이가 아니라 같은 정보의 반복이라 그리지 않는다.

    점선은 이 화면이 견주는 기준(직전 N개월 월평균)이다. 막대만 있으면 어느
    달이 많이 쓴 달인지 눈으로 재야 하고, 요약과 증감 비교가 말하는 기준선이
    차트 어디에 있는지도 보이지 않는다.
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
                    "percent": f"{part['share'] * 100:.0f}%",
                    # 조각이 글자보다 낮으면 안에 적을 수 없다. 그런 조각은
                    # 숫자를 빼고 색과 마우스 올림으로만 읽게 둔다.
                    "show_label": piece_height >= STACK_LABEL_MIN_HEIGHT,
                    "label_y": top + piece_height / 2 + 3.5,
                    "centre": slot * (index + 0.5),
                    "title": (
                        f"{month['month']} {part['name']} {won_text(part['total'])} "
                        f"({part['share'] * 100:.1f}%)"
                    ),
                }
            )
            top += piece_height
        columns.append(
            {
                "pieces": pieces,
                "label": month["month"][2:].replace("-", "."),
                "centre": slot * (index + 0.5),
                "total": man_text(month["total"]),
                "top": height - height * month["total"] / ceiling,
            }
        )
    # 위쪽 도넛까지 스크롤을 올려야 색을 알 수 있으면 차트가 혼자 설 수 없다.
    # 이 달들에 실제로 나타난 대분류만 싣는다.
    present = {
        part["id"]
        for month in series["months"]
        for part in month["parts"]
        if part["total"]
    }
    legend = [
        {"name": group.name, "color": group.color}
        for group in series["groups"]
        if group.pk in present
    ]
    return {
        "width": width,
        "height": height,
        "columns": columns,
        "legend": legend,
        # 기준선이 차트 위쪽으로 벗어나면 그리지 않는다. 그릴 자리가 없는 선을
        # 억지로 얹으면 다른 막대 위에 걸쳐 엉뚱한 값으로 읽힌다.
        "average_y": (height - height * average / ceiling) if 0 < average <= ceiling else None,
        "average_label": f"최근 {months_used}개월 평균 {man_text(average)}",
    }


@staff_member_required
def report(request: HttpRequest) -> HttpResponse:
    view = month_view(request.GET.get("month"))
    if view is None:
        return render(request, "report/spending_empty.html", _links("report"))

    statement = view.statement
    totals = view.totals
    current = next((item for item in totals if item.month == statement.billing_month), None)

    # 화면 전체가 같은 창을 쓴다 - 점선, 평균 대비 KPI, 증감 비교 표가 서로
    # 다른 기간을 견주면 숫자끼리 이야기가 안 맞는다.
    top = _pick(request, "top", TOP_CHOICES, DEFAULT_TOP)
    window = _pick(request, "window", WINDOW_CHOICES, DEFAULT_WINDOW)
    average, months_used = baseline_average(statement, window)
    against = group_comparison(statement, window)

    categories = category_rows(statement, view.previous)
    # 비교할 앞선 달이 없으면 증감이 아니라 이번 달 금액 그 자체다. 0에서
    # 늘어난 것으로 그리면 첫 달이 전부 급증한 것처럼 읽힌다.
    changed = (
        [row for row in category_comparison(statement, window) if row["delta"]][:8]
        if months_used
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
                "delta_text": (
                    man_text(against.get(row["id"], {}).get("delta", 0))
                    if months_used
                    else ""
                ),
                "up": against.get(row["id"], {}).get("delta", 0) > 0,
            }
            for row in groups
        ],
        "pie": pie,
        "group_trend": _group_trend(average, window, months_used),
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
        "window": window,
        "window_choices": WINDOW_CHOICES,
        "months_used": months_used,
        # 요구한 창보다 실제 달이 적으면 그 사실을 화면이 말해야 한다.
        "window_short": months_used and months_used < window,
        "categories": [
            {
                **row,
                "bar": 100 * row["total"] / ceiling,
                "amount": won_text(row["total"]),
                # 막대만 있으면 "저게 몇 퍼센트지"를 눈으로 재야 한다.
                "percent_text": f"{row['share'] * 100:.1f}%",
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
                # 막대 길이는 이번 달 최대 증감 대비다. 읽을 값은 그게 아니라
                # 직전 달 대비 몇 퍼센트 움직였는가다. 전월에 없던 항목은
                # 증감률이 정의되지 않으므로 그렇다고 말한다 - 빈칸으로 두면
                # 계산에 실패한 것처럼 보인다.
                "percent_text": (
                    "신규"
                    if row["percent"] is None and row["baseline"] == 0
                    else signed_percent_text(row["percent"])
                ),
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
            for row in top_merchants(statement, limit=top)
        ],
        "top": top,
        "top_choices": TOP_CHOICES,
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
        # 미분류 줄에서 고를 목록. 미분류 자신은 고를 수 있으면 안 된다.
        "categories": _category_choices(),
    }
    return render(request, "report/spending_transactions.html", context)


def _save_selection(request: HttpRequest, statement) -> HttpResponse:
    """체크를 푼 줄을 집계에서 빼고, 손으로 고른 분류를 규칙으로 남긴다.

    제외는 지우지 않고 표시만 바꾼다 - 명세서의 청구총액과 대조하려면 그 줄도
    그대로 있어야 하고, 언제든 되돌릴 수 있어야 한다. 체크된 것만 폼으로
    올라오므로, 이 명세서의 줄 중 올라오지 않은 것이 곧 제외 대상이다.
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

    dropped = len(rows) - len(keep)
    notes = [
        f"{dropped}건을 집계에서 제외했습니다." if dropped else "모든 거래를 집계에 넣었습니다."
    ]
    rule_note = _learn_categories(request, rows)
    if rule_note:
        notes.append(rule_note)
    messages.success(request, " ".join(notes))
    return redirect(
        f"{settings.SPENDING_TRANSACTIONS_URL_PATH}/?month={statement.billing_month}"
    )


def _category_choices() -> list[dict]:
    """드롭다운에 담을 카테고리. 대분류로 묶어 이름이 겹치지 않게 한다.

    `필수생활-기타`처럼 이름이 이미 대분류를 품고 있으면 앞에 대분류를 또
    붙이지 않는다 - "필수생활 · 필수생활-기타"는 읽을 것이 없다.
    """
    choices = []
    for category in (
        SpendingCategory.objects.exclude(pk=UNCLASSIFIED_CATEGORY_ID)
        .select_related("group")
        .order_by("group__order", "order", "name")
    ):
        group = category.group.name if category.group else ""
        if group and not category.name.startswith(group):
            label = f"{group} · {category.name}"
        else:
            label = category.name
        choices.append({"id": category.pk, "label": label})
    return choices


def _learn_categories(request: HttpRequest, rows) -> str:
    """손으로 고른 분류를 규칙으로 만들어 다른 달까지 함께 맞춘다.

    한 줄만 고쳐 두면 같은 가맹점이 다음 달에 또 미분류로 온다. 가맹점명을
    그대로 키워드로 삼는 규칙을 만들면 이미 저장된 달과 앞으로 올 명세서가
    한 번에 정리된다 - 그게 이 화면에서 고르는 일의 값이다.
    """
    by_id = {item.pk: item for item in rows}
    picks: dict[str, str] = {}
    for key, value in request.POST.items():
        if not key.startswith("category-") or not value:
            continue
        raw_id = key.removeprefix("category-")
        if not raw_id.isdigit():
            continue
        item = by_id.get(int(raw_id))
        if item and item.merchant_norm:
            picks[item.merchant_norm] = value

    if not picks:
        return ""

    valid = set(SpendingCategory.objects.values_list("pk", flat=True))
    created = 0
    for merchant_norm, category_id in picks.items():
        if category_id not in valid or category_id == UNCLASSIFIED_CATEGORY_ID:
            continue
        # 손으로 고른 것이 규칙보다 위에 오도록 우선순위를 앞에 둔다.
        MerchantRule.objects.update_or_create(
            keyword=merchant_norm,
            defaults={"category_id": category_id, "order": 1, "note": "화면에서 지정"},
        )
        created += 1

    if not created:
        return ""
    result = recategorize_all()
    return (
        f"가맹점 {created}곳을 규칙으로 등록했습니다 - 다른 달과 앞으로 오는 "
        f"명세서에도 적용됩니다. 남은 미분류 가맹점 {len(result.unmatched)}곳."
    )
