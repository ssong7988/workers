"""카테고리와 출발점이 될 가맹점 규칙을 심는다.

빈 화면에서 시작하면 첫 명세서가 통째로 미분류로 들어와 무엇부터 손대야 할지
알기 어렵다. 여기 심는 것은 전국 어디서나 같은 이름으로 찍히는 체인뿐이고,
동네 가맹점은 admin에서 더한다.

규칙 순서가 분류를 가른다. `order`가 작을수록 먼저 검사하므로 좁은 규칙이 위에
있어야 한다 - `이마트24`(편의점)가 `이마트`(마트)에 먹히지 않는 이유다.
"""

from django.db import migrations


CATEGORIES = [
    ("food", "식비", 10, False),
    ("cafe", "카페·간식", 20, False),
    ("grocery", "편의점·마트", 30, False),
    ("transport", "교통", 40, False),
    ("fuel", "주유", 50, False),
    ("telecom", "통신", 60, False),
    ("subscription", "구독", 70, False),
    ("medical", "의료", 80, False),
    ("shopping", "쇼핑", 90, False),
    ("culture", "문화·여가", 100, False),
    ("housing", "주거·공과금", 110, False),
    ("education", "교육", 120, False),
    ("gift", "경조사", 130, False),
    ("finance_cost", "금융비용", 140, True),
    ("etc", "기타", 150, False),
    ("unclassified", "미분류", 999, False),
]

# (order, 카테고리, 키워드들). order가 작을수록 먼저 검사한다.
RULES = [
    (10, "grocery", ["이마트24"]),
    (20, "transport", ["교통-하이패스", "교통-지하철", "교통-버스", "티머니", "TMONEY",
                       "카카오T", "코레일", "SRT", "고속버스", "쏘카", "그린카"]),
    (30, "cafe", ["스타벅스", "STARBUCKS", "투썸", "이디야", "메가엠지씨", "메가커피",
                  "커피빈", "폴바셋", "빽다방", "컴포즈", "파리바게뜨", "뚜레쥬르",
                  "배스킨", "던킨"]),
    (40, "grocery", ["GS25", "CU", "세븐일레븐", "이마트", "홈플러스", "롯데마트",
                     "코스트코", "하나로마트", "노브랜드"]),
    (50, "food", ["배달의민족", "배민", "쿠팡이츠", "요기요", "맥도날드", "버거킹",
                  "롯데리아", "서브웨이", "김밥", "국밥", "순대", "분식", "칼국수"]),
    (60, "fuel", ["주유소", "SK에너지", "GS칼텍스", "현대오일뱅크", "S-OIL", "에쓰오일",
                  "오일뱅크", "충전소"]),
    (70, "telecom", ["SKT", "SK텔레콤", "LG유플러스", "유플러스", "알뜰폰"]),
    (80, "subscription", ["NETFLIX", "넷플릭스", "YOUTUBE", "유튜브", "SPOTIFY", "멜론",
                          "왓챠", "티빙", "웨이브", "쿠팡플레이", "ICLOUD", "GOOGLE",
                          "APPLE.COM", "MICROSOFT", "OPENAI", "ANTHROPIC", "CHATGPT",
                          "NOTION", "ADOBE"]),
    (90, "medical", ["의원", "병원", "약국", "치과", "한의원", "클리닉", "메디컬"]),
    (100, "shopping", ["쿠팡", "COUPANG", "네이버페이", "11번가", "G마켓", "지마켓",
                       "옥션", "SSG", "무신사", "올리브영", "다이소", "갤러리아",
                       "현대백화점", "신세계백화점", "롯데백화점", "ALIEXPRESS", "AMAZON"]),
    (110, "culture", ["CGV", "메가박스", "롯데시네마", "교보문고", "예스24", "알라딘",
                      "인터파크", "STEAM", "플레이스테이션", "헬스", "피트니스", "골프"]),
    (120, "housing", ["한국전력", "도시가스", "수도사업소", "관리사무소", "아파트관리",
                      "상하수도"]),
    (130, "education", ["학원", "교육원", "인프런", "UDEMY", "대학교", "도서관"]),
]


def seed(apps, schema_editor):
    Category = apps.get_model("spending", "SpendingCategory")
    Rule = apps.get_model("spending", "MerchantRule")

    for code, name, order, financial in CATEGORIES:
        Category.objects.update_or_create(
            pk=code,
            defaults={"name": name, "order": order, "is_financial_cost": financial},
        )

    for order, category, keywords in RULES:
        for keyword in keywords:
            # 모델의 save()가 아니라 마이그레이션 모델이라 정규화가 걸리지 않는다.
            # 규칙이 정규화된 가맹점명과 맞으려면 같은 모양으로 넣어야 한다.
            normalized = keyword.replace(" ", "").upper()
            Rule.objects.update_or_create(
                keyword=normalized,
                defaults={"category_id": category, "order": order},
            )


def unseed(apps, schema_editor):
    apps.get_model("spending", "MerchantRule").objects.all().delete()
    apps.get_model("spending", "SpendingCategory").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("spending", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
