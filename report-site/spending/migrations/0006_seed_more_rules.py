"""보험 카테고리와 전국 브랜드 규칙을 심는다.

여기 넣는 것은 어느 집에서나 같은 이름으로 찍히는 전국 브랜드뿐이다. 동네
가맹점은 화면의 선택 박스로 넣는다 - 그쪽은 사람마다 다르고, 이 파일에 넣으면
남의 동네 이름이 기본값으로 따라다닌다.

보험료는 매달 정해진 금액이 나가는데 갈 카테고리가 없어 미분류에 있었다.
고정비 아래에 자리를 만든다.
"""

from django.db import migrations


RULES = [
    # 이케아는 매장과 레스토랑이 다른 이름으로 찍힌다. 좁은 쪽이 먼저다.
    (5, "food", ["이케아기흥점"]),
    (60, "food", [
        "캐치테이블", "아웃백스테이크하우스", "고든램지", "봉추찜닭",
        "60계치킨", "바르다김선생", "아비꼬", "오마카세",
    ]),
    (60, "cafe", ["테라로사", "설빙", "보나비", "이성당"]),
    (60, "shopping", [
        "삼성전자(주)", "신세계사이먼", "나이키코리아", "에프알엘코리아",
        "이케아코리아", "노스페이스", "토이저러스", "현대아울렛", "스타필드",
        "와인앤모어",
    ]),
    (60, "culture", ["에버랜드"]),
    (60, "education", ["파고다"]),
    (60, "subscription", ["디지틀조선일보"]),
    (60, "transport", ["카카오모빌리티", "카카오택시", "카카오_택시"]),
    (60, "insurance", ["손해보험", "생명보험", "화재해상"]),
    # 브랜드 규칙이 먼저 검사되도록 뒤에 둔다. 이름에 커피가 들어가면 카페다.
    (80, "cafe", ["커피"]),
]


def seed(apps, schema_editor):
    Category = apps.get_model("spending", "SpendingCategory")
    Rule = apps.get_model("spending", "MerchantRule")

    Category.objects.update_or_create(
        pk="insurance",
        defaults={
            "name": "보험",
            "order": 65,
            "group_id": "fixed",
            "is_financial_cost": False,
        },
    )

    for order, category, keywords in RULES:
        for keyword in keywords:
            Rule.objects.update_or_create(
                keyword=keyword.replace(" ", "").upper(),
                defaults={"category_id": category, "order": order},
            )


def unseed(apps, schema_editor):
    Rule = apps.get_model("spending", "MerchantRule")
    for _order, _category, keywords in RULES:
        Rule.objects.filter(
            keyword__in=[k.replace(" ", "").upper() for k in keywords]
        ).delete()
    Category = apps.get_model("spending", "SpendingCategory")
    Category.objects.filter(pk="insurance", transactions__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("spending", "0005_transaction_excluded")]
    operations = [migrations.RunPython(seed, unseed)]
