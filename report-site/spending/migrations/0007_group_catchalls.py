"""대분류마다 기타 자리를 만든다.

성격은 분명한데 맞는 카테고리가 없는 지출이 있다 - 세탁이나 미용은 필수생활인
것이 분명하지만 장보기도 병원도 아니다. 그런 것을 통짜 `기타`로 보내면 대분류
비중이 틀어진다. 실제로는 필수생활인 돈이 기타로 잡히기 때문이다.

대분류마다 기타를 두면 그런 지출도 제 성격으로 집계되면서, 나중에 같은 것이
쌓였을 때 거기서 새 카테고리를 떼어내기도 쉽다.

`기타` 대분류에는 만들지 않는다. 그 아래 이미 `기타`가 있고, 둘을 두면 어느
쪽에 넣어야 할지가 매번 질문이 된다.
"""

from django.db import migrations


# (대분류, 카테고리 코드, 이름)
CATCHALLS = [
    ("fixed", "fixed_etc", "고정비-기타"),
    ("essential", "essential_etc", "필수생활-기타"),
    ("dining", "dining_etc", "외식-기타"),
    ("transport", "transport_etc", "교통-기타"),
    ("leisure", "leisure_etc", "여가·쇼핑-기타"),
]


def seed(apps, schema_editor):
    Category = apps.get_model("spending", "SpendingCategory")
    for group_id, code, name in CATCHALLS:
        Category.objects.update_or_create(
            pk=code,
            defaults={
                "name": name,
                # 자기 대분류 안에서는 늘 마지막에 온다. 고를 때 눈이 먼저
                # 구체적인 카테고리를 훑고 나서 기타에 닿아야 한다.
                "order": 900,
                "group_id": group_id,
                "is_financial_cost": False,
            },
        )


def unseed(apps, schema_editor):
    Category = apps.get_model("spending", "SpendingCategory")
    codes = [code for _group, code, _name in CATCHALLS]
    # 쓰인 적 있는 카테고리는 지우지 않는다. 지우면 그 거래가 갈 곳을 잃는다.
    Category.objects.filter(pk__in=codes, transactions__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("spending", "0006_seed_more_rules")]
    operations = [migrations.RunPython(seed, unseed)]
