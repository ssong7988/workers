"""몰 이름으로 만든 키워드를 좁힌다.

`갤러리아`는 백화점을 잡으려고 넣었는데 그 안에 입점한 식당까지 끌어왔다 -
`빕스갤러리아광교점`이 쇼핑으로 잡혔다. 몰 안에는 다른 업종이 들어 있으므로,
몰 이름은 그 몰 자신을 가리키는 형태로 좁혀야 한다.

한 건만 고치면 다음에 같은 자리에서 다시 걸린다. 키워드를 좁히는 쪽이
문제를 없앤다.
"""

from django.db import migrations


# 넓은 키워드 → 좁힌 키워드
NARROW = [("갤러리아", "갤러리아백화점", "shopping")]

# 몰 안에 들어 있어 몰 이름에 먼저 걸릴 수 있는 전국 브랜드. 좁은 쪽이 먼저다.
TENANTS = [(5, "food", ["빕스"])]


def apply(apps, schema_editor):
    Rule = apps.get_model("spending", "MerchantRule")

    for broad, narrow, category in NARROW:
        Rule.objects.filter(keyword=broad).delete()
        Rule.objects.update_or_create(
            keyword=narrow, defaults={"category_id": category, "order": 60}
        )

    for order, category, keywords in TENANTS:
        for keyword in keywords:
            Rule.objects.update_or_create(
                keyword=keyword.replace(" ", "").upper(),
                defaults={"category_id": category, "order": order},
            )


def undo(apps, schema_editor):
    Rule = apps.get_model("spending", "MerchantRule")
    for _order, _category, keywords in TENANTS:
        Rule.objects.filter(keyword__in=keywords).delete()
    for broad, narrow, category in NARROW:
        Rule.objects.filter(keyword=narrow).delete()
        Rule.objects.update_or_create(
            keyword=broad, defaults={"category_id": category, "order": 60}
        )


class Migration(migrations.Migration):
    dependencies = [("spending", "0007_group_catchalls")]
    operations = [migrations.RunPython(apply, undo)]
