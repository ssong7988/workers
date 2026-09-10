"""대분류를 심고 카테고리를 붙인다.

축은 "줄일 수 없는 돈과 내가 조절하는 돈"이다. 고정비와 필수생활은 그 달에
안 쓰기로 결정할 수 없는 쪽이고, 외식·여가쇼핑은 결정할 수 있는 쪽이다.
교통은 둘 사이라 따로 둔다 - 출퇴근은 못 줄여도 주유·정비는 달마다 흔들린다.

정기치료를 의료에서 떼어내 고정비로 보낸다. 매달 같은 금액이 정해진 횟수만큼
나가므로 통신·구독과 성격이 같고, 의료에 두면 나중에 감기로 병원 한 번 간 것이
고정비로 잡힌다.

색은 대분류마다 고정이다. 달이 바뀌어도 같은 성격이 같은 색이라야 비교가
되고, 색이 순위를 따라다니면 그게 깨진다.
"""

from django.db import migrations


GROUPS = [
    ("fixed", "고정비", 10, "#2a78d6", "매달 정해진 금액이 반드시 나가는 돈"),
    ("essential", "필수생활", 20, "#1baf7a", "장보기·병원·교육처럼 안 쓸 수 없는 실물"),
    ("dining", "외식", 30, "#eb6834", "밖에서 사 먹은 식사와 카페"),
    ("transport", "교통", 40, "#eda100", "대중교통·주유·차량 유지"),
    ("leisure", "여가·쇼핑", 50, "#e87ba4", "내가 줄일 수 있는 재량 지출"),
    ("other", "기타", 90, "#94a3b8", "위 어디에도 들지 않는 것"),
]

# 대분류 → 카테고리
MEMBERSHIP = {
    "fixed": ["telecom", "subscription", "housing", "finance_cost", "care"],
    "essential": ["grocery", "medical", "education"],
    "dining": ["food", "cafe"],
    "transport": ["transport", "fuel", "car"],
    "leisure": ["shopping", "culture"],
    "other": ["gift", "etc", "unclassified"],
}

# 정기치료는 새 카테고리다. 규칙도 같이 넣어 다음 명세서부터 자동으로 잡힌다.
CARE_KEYWORDS = ["내인생봄날"]


def seed(apps, schema_editor):
    Group = apps.get_model("spending", "SpendingGroup")
    Category = apps.get_model("spending", "SpendingCategory")
    Rule = apps.get_model("spending", "MerchantRule")
    Transaction = apps.get_model("spending", "Transaction")

    for code, name, order, color, note in GROUPS:
        Group.objects.update_or_create(
            pk=code,
            defaults={"name": name, "order": order, "color": color, "note": note},
        )

    Category.objects.update_or_create(
        pk="care",
        defaults={"name": "치료·돌봄", "order": 85, "is_financial_cost": False},
    )

    for group_id, category_ids in MEMBERSHIP.items():
        Category.objects.filter(pk__in=category_ids).update(group_id=group_id)

    # 어디에도 지정되지 않은 카테고리는 기타로 보낸다. 대분류가 비어 있으면
    # 차트에서 조용히 사라져 합계가 총액과 맞지 않게 된다.
    Category.objects.filter(group__isnull=True).update(group_id="other")

    for keyword in CARE_KEYWORDS:
        normalized = keyword.replace(" ", "").upper()
        Rule.objects.update_or_create(
            keyword=normalized, defaults={"category_id": "care", "order": 5}
        )
        # 이미 들어와 있는 거래도 옮긴다. 규칙만 넣으면 다음 달부터나 맞는다.
        Transaction.objects.filter(merchant_norm__contains=normalized).update(
            category_id="care", category_source="rule"
        )


def unseed(apps, schema_editor):
    apps.get_model("spending", "SpendingCategory").objects.update(group_id=None)
    apps.get_model("spending", "SpendingGroup").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("spending", "0003_spendinggroup_spendingcategory_group")]
    operations = [migrations.RunPython(seed, unseed)]
