"""카드 소비의 규칙이 실제로 지켜지는지 확인한다.

가장 중요한 것 둘: 소계와 어긋난 명세서는 저장되지 않는다는 것, 그리고 같은
청구월이 다시 오면 합쳐지지 않고 통째로 바뀐다는 것이다.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from spending.categorize import categorize, recategorize_all
from spending.delivery import build_digest
from spending.analysis import (
    category_rows,
    group_rows,
    installment_outlook,
    month_view,
    monthly_totals,
)
from spending.ingest import IngestError, ingest_statement
from spending.models import (
    UNCLASSIFIED_CATEGORY_ID,
    MerchantRule,
    SpendingCategory,
    Statement,
    Transaction,
    normalize_merchant,
)


def row(merchant: str, billed: int, **extra) -> dict:
    payload = {
        "used_at": "2026-08-14",
        "merchant": merchant,
        "billed_won": billed,
        "total_won": billed,
        "payment_type": "일시불",
        "card_last4": "4766",
    }
    payload.update(extra)
    return payload


def statement_payload(month: str = "2026-09", rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else [row("스타벅스 과천점", 5_600)]
    return {
        "billing_month": month,
        "payment_date": f"{month}-13",
        "total_billed_won": sum(item["billed_won"] for item in rows),
        "source_ref": "<test@samsungcard.com>",
        "transactions": rows,
    }


class IngestTest(TestCase):
    def test_saves_a_statement_and_its_rows(self):
        result = ingest_statement(statement_payload())
        self.assertTrue(result.created)
        self.assertEqual(Statement.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_rejects_a_statement_whose_rows_do_not_add_up(self):
        payload = statement_payload()
        payload["total_billed_won"] += 10_000
        with self.assertRaisesRegex(IngestError, "청구총액"):
            ingest_statement(payload)
        # 거절된 명세서는 흔적을 남기지 않는다.
        self.assertEqual(Statement.objects.count(), 0)

    def test_a_resent_statement_replaces_the_month_rather_than_appending(self):
        ingest_statement(statement_payload(rows=[row("스타벅스", 5_600)]))
        ingest_statement(
            statement_payload(rows=[row("이마트", 30_000), row("GS25", 4_000)])
        )
        self.assertEqual(Statement.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(Statement.objects.get().total_billed_won, 34_000)

    def test_a_cancellation_keeps_the_total_consistent(self):
        payload = statement_payload(
            rows=[row("이마트", 30_000), row("이마트 취소", -30_000)]
        )
        result = ingest_statement(payload)
        self.assertEqual(result.total_billed_won, 0)

    def test_rejects_a_malformed_billing_month(self):
        with self.assertRaisesRegex(IngestError, "청구월"):
            ingest_statement(statement_payload(month="2026-13"))

    def test_rejects_a_statement_with_no_rows(self):
        payload = statement_payload()
        payload["transactions"] = []
        payload["total_billed_won"] = 0
        with self.assertRaises(IngestError):
            ingest_statement(payload)


class CategorizeTest(TestCase):
    def test_a_branch_matches_its_chain(self):
        ingest_statement(statement_payload(rows=[row("스타벅스 과천점", 5_600)]))
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.category_id, "cafe")
        self.assertEqual(transaction.category_source, "rule")

    def test_the_narrower_rule_wins(self):
        # 이마트24는 편의점이고 이마트는 마트다. 순서가 이 둘을 가른다.
        ingest_statement(statement_payload(rows=[row("이마트24 과천점", 4_000)]))
        self.assertEqual(Transaction.objects.get().category_id, "grocery")

    def test_annual_fee_bypasses_the_keyword_rules(self):
        ingest_statement(
            statement_payload(rows=[row("스타벅스제휴카드연회비", 15_000, payment_type="연회비")])
        )
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.category_id, "finance_cost")
        self.assertEqual(transaction.category_source, "payment_type")

    def test_an_unknown_merchant_lands_in_unclassified(self):
        ingest_statement(statement_payload(rows=[row("이름없는가게ZZ", 9_000)]))
        self.assertEqual(Transaction.objects.get().category_id, UNCLASSIFIED_CATEGORY_ID)

    def test_a_new_rule_reclassifies_without_recollecting(self):
        ingest_statement(statement_payload(rows=[row("이름없는가게ZZ", 9_000)]))
        MerchantRule.objects.create(
            keyword="이름없는가게ZZ", category=SpendingCategory.objects.get(pk="food"), order=5
        )
        recategorize_all()
        self.assertEqual(Transaction.objects.get().category_id, "food")

    def test_a_hand_picked_category_survives_a_resent_statement(self):
        """정정 명세서가 와도 사람이 고른 분류는 남는다.

        그 달을 통째로 바꾸느라 행이 새로 만들어지는데, 그때 사람의 판단까지
        날려 버리면 손으로 고칠 이유가 없어진다.
        """
        ingest_statement(statement_payload(rows=[row("이름없는가게ZZ", 9_000)]))
        transaction = Transaction.objects.get()
        transaction.category = SpendingCategory.objects.get(pk="culture")
        transaction.category_source = "manual"
        transaction.save()

        ingest_statement(statement_payload(rows=[row("이름없는가게ZZ", 9_000)]))
        restored = Transaction.objects.get()
        self.assertEqual(restored.category_id, "culture")
        self.assertEqual(restored.category_source, "manual")

    def test_a_hand_picked_category_survives_reclassification(self):
        ingest_statement(statement_payload(rows=[row("스타벅스 과천점", 5_600)]))
        transaction = Transaction.objects.get()
        transaction.category = SpendingCategory.objects.get(pk="etc")
        transaction.category_source = "manual"
        transaction.save()
        recategorize_all()
        self.assertEqual(Transaction.objects.get().category_id, "etc")


class NormalizeTest(TestCase):
    def test_strips_whitespace_and_corporate_forms(self):
        self.assertEqual(normalize_merchant("(주) 이마트 과천점"), "이마트과천점")

    def test_uppercases_so_ascii_keywords_match_either_case(self):
        self.assertEqual(normalize_merchant("netflix.com"), "NETFLIX.COM")


class AnalysisTest(TestCase):
    def test_month_over_month_is_empty_across_a_gap(self):
        ingest_statement(statement_payload(month="2026-06"))
        ingest_statement(statement_payload(month="2026-09"))
        view = month_view()
        # 6월과 9월 사이가 비어 있으므로 직전 달로 삼지 않는다.
        self.assertIsNone(view.previous)

    def test_the_immediately_preceding_month_counts(self):
        ingest_statement(statement_payload(month="2026-08"))
        ingest_statement(statement_payload(month="2026-09"))
        self.assertEqual(month_view().previous.billing_month, "2026-08")

    def test_a_category_that_disappeared_is_still_listed_at_zero(self):
        ingest_statement(statement_payload(month="2026-08", rows=[row("이마트", 30_000)]))
        ingest_statement(statement_payload(month="2026-09", rows=[row("스타벅스", 5_600)]))
        view = month_view()
        grocery = next(r for r in category_rows(view.statement, view.previous) if r["id"] == "grocery")
        self.assertEqual(grocery["total"], 0)
        self.assertEqual(grocery["delta"], -30_000)

    def test_installments_project_only_the_charges_still_to_come(self):
        ingest_statement(
            statement_payload(
                rows=[
                    row(
                        "노트북",
                        50_000,
                        total_won=300_000,
                        payment_type="할부",
                        installment_seq=2,
                        installment_months=6,
                    )
                ]
            )
        )
        outlook = installment_outlook(Statement.objects.get())
        self.assertEqual(outlook["active"][0]["remaining"], 4)
        self.assertEqual(outlook["future_total"], 200_000)
        self.assertEqual(outlook["by_month"][0]["month"], "2026-10")


class GroupTest(TestCase):
    def test_every_category_belongs_to_a_group(self):
        """대분류가 비면 그 금액이 차트에서 조용히 사라져 합계가 안 맞는다."""
        orphans = SpendingCategory.objects.filter(group__isnull=True)
        self.assertEqual(list(orphans), [])

    def test_group_shares_add_up_to_the_month(self):
        ingest_statement(
            statement_payload(
                rows=[
                    row("스타벅스", 100_000),      # 외식
                    row("이마트", 200_000),        # 필수생활
                    row("SKT 요금", 50_000),       # 고정비
                ]
            )
        )
        view = month_view()
        rows = group_rows(view.statement)
        self.assertEqual(sum(r["total"] for r in rows), 350_000)
        self.assertAlmostEqual(sum(r["share"] for r in rows), 1.0, places=3)

    def test_the_therapy_category_counts_as_a_fixed_cost(self):
        """매달 같은 금액이 정해진 횟수만큼 나가므로 통신·구독과 같은 자리다."""
        ingest_statement(statement_payload(rows=[row("내인생봄날의원", 85_000)]))
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.category_id, "care")
        self.assertEqual(transaction.category.group_id, "fixed")

    def test_an_ordinary_clinic_is_not_a_fixed_cost(self):
        """의료를 통째로 고정비에 넣었다면 감기 진료가 고정비로 잡혔을 것이다."""
        ingest_statement(statement_payload(rows=[row("한빛의원", 15_000)]))
        transaction = Transaction.objects.get()
        self.assertEqual(transaction.category_id, "medical")
        self.assertEqual(transaction.category.group_id, "essential")

    def test_every_group_but_기타_has_a_catchall(self):
        """성격은 분명한데 맞는 카테고리가 없는 지출이 갈 곳."""
        for group_id in ("fixed", "essential", "dining", "transport", "leisure"):
            with self.subTest(group=group_id):
                self.assertTrue(
                    SpendingCategory.objects.filter(
                        group_id=group_id, name__endswith="기타"
                    ).exists()
                )

    def test_a_catchall_still_counts_towards_its_own_group(self):
        """통짜 기타로 보내면 대분류 비중이 틀어진다. 그걸 막는 것이 목적이다."""
        ingest_statement(statement_payload(rows=[row("광교세탁소", 50_000)]))
        transaction = Transaction.objects.get()
        transaction.category = SpendingCategory.objects.get(pk="essential_etc")
        transaction.category_source = "manual"
        transaction.save()

        view = month_view()
        essential = next(r for r in group_rows(view.statement) if r["id"] == "essential")
        self.assertEqual(essential["total"], 50_000)
        other = next(r for r in group_rows(view.statement) if r["id"] == "other")
        self.assertEqual(other["total"], 0)

    def test_the_catchall_sorts_last_inside_its_group(self):
        """구체적인 카테고리를 먼저 훑고 나서 기타에 닿아야 한다."""
        within = list(
            SpendingCategory.objects.filter(group_id="essential")
            .order_by("order", "name")
            .values_list("pk", flat=True)
        )
        self.assertEqual(within[-1], "essential_etc")

    def test_group_order_is_stable_so_colours_do_not_move(self):
        ingest_statement(statement_payload(rows=[row("스타벅스", 100_000)]))
        view = month_view()
        first = [r["id"] for r in group_rows(view.statement)]
        ingest_statement(statement_payload(rows=[row("이마트", 900_000)]))
        second = [r["id"] for r in group_rows(month_view().statement)]
        self.assertEqual(first, second)


class ExclusionTest(TestCase):
    """대신 결제해 주고 돌려받는 돈처럼, 청구는 됐지만 내 소비가 아닌 줄."""

    def setUp(self):
        ingest_statement(
            statement_payload(
                rows=[row("스타벅스", 10_000), row("남의카드결제대행", 500_000)]
            )
        )
        self.dropped = Transaction.objects.get(merchant="남의카드결제대행")

    def exclude(self):
        self.dropped.excluded = True
        self.dropped.save()

    def test_excluding_removes_it_from_the_analysed_total(self):
        self.exclude()
        statement = Statement.objects.get()
        self.assertEqual(statement.analysed_total_won, 10_000)
        self.assertEqual(statement.excluded_total_won, 500_000)

    def test_the_statement_check_still_sees_every_row(self):
        """제외는 집계에서만 빼는 것이지 명세서와의 대조를 흔들면 안 된다."""
        self.exclude()
        statement = Statement.objects.get()
        self.assertEqual(statement.parsed_total_won, 510_000)
        self.assertEqual(statement.discrepancy_won, 0)

    def test_excluded_rows_leave_the_category_and_group_totals(self):
        self.exclude()
        view = month_view()
        self.assertEqual(sum(r["total"] for r in group_rows(view.statement)), 10_000)
        self.assertEqual(sum(r["total"] for r in category_rows(view.statement, None)), 10_000)

    def test_monthly_totals_drop_the_excluded_row(self):
        self.exclude()
        self.assertEqual(monthly_totals()[-1].total, 10_000)

    def test_a_resent_statement_keeps_the_exclusion(self):
        """정정 명세서 한 통에 사람이 골라 둔 것이 되살아나면 다시 골라야 한다."""
        self.exclude()
        ingest_statement(
            statement_payload(
                rows=[row("스타벅스", 10_000), row("남의카드결제대행", 500_000)]
            )
        )
        restored = Transaction.objects.get(merchant="남의카드결제대행")
        self.assertTrue(restored.excluded)
        self.assertEqual(Statement.objects.get().analysed_total_won, 10_000)

    def test_the_digest_reports_the_analysed_total(self):
        self.exclude()
        self.assertIn("1.0만", build_digest().message)


class PickCategoryTest(TestCase):
    """전체 거래 화면에서 미분류를 고르면 규칙이 된다."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "picker", password="x", is_staff=True
        )
        self.client.force_login(self.user)
        ingest_statement(
            statement_payload(month="2026-08", rows=[row("이름없는가게ZZ", 30_000)])
        )
        ingest_statement(
            statement_payload(month="2026-09", rows=[row("이름없는가게ZZ", 20_000)])
        )
        self.september = Transaction.objects.get(statement__billing_month="2026-09")

    def post(self, **extra):
        payload = {"month": "2026-09", "keep": [str(self.september.pk)]}
        payload.update(extra)
        return self.client.post(settings.SPENDING_TRANSACTIONS_URL_PATH + "/", payload)

    def test_picking_a_category_classifies_the_row(self):
        self.post(**{f"category-{self.september.pk}": "food"})
        self.september.refresh_from_db()
        self.assertEqual(self.september.category_id, "food")

    def test_the_pick_becomes_a_rule_for_later_statements(self):
        self.post(**{f"category-{self.september.pk}": "food"})
        rule = MerchantRule.objects.get(keyword="이름없는가게ZZ")
        self.assertEqual(rule.category_id, "food")

    def test_the_same_merchant_in_another_month_is_classified_too(self):
        """한 줄만 고쳐지면 다음 달에 또 손이 간다."""
        self.post(**{f"category-{self.september.pk}": "food"})
        august = Transaction.objects.get(statement__billing_month="2026-08")
        self.assertEqual(august.category_id, "food")

    def test_a_new_statement_uses_the_learned_rule(self):
        self.post(**{f"category-{self.september.pk}": "food"})
        ingest_statement(
            statement_payload(month="2026-10", rows=[row("이름없는가게ZZ 2호점", 5_000)])
        )
        october = Transaction.objects.get(statement__billing_month="2026-10")
        self.assertEqual(october.category_id, "food")

    def test_leaving_it_unpicked_changes_nothing(self):
        self.post(**{f"category-{self.september.pk}": ""})
        self.september.refresh_from_db()
        self.assertEqual(self.september.category_id, UNCLASSIFIED_CATEGORY_ID)
        self.assertFalse(MerchantRule.objects.filter(keyword="이름없는가게ZZ").exists())

    def test_unclassified_cannot_be_picked_as_a_category(self):
        self.post(**{f"category-{self.september.pk}": UNCLASSIFIED_CATEGORY_ID})
        self.assertFalse(MerchantRule.objects.filter(keyword="이름없는가게ZZ").exists())

    def test_picking_and_excluding_work_in_the_same_save(self):
        self.client.post(
            settings.SPENDING_TRANSACTIONS_URL_PATH + "/",
            {"month": "2026-09", "keep": [], f"category-{self.september.pk}": "food"},
        )
        self.september.refresh_from_db()
        self.assertEqual(self.september.category_id, "food")
        self.assertTrue(self.september.excluded)


class DigestTest(TestCase):
    def test_message_fits_the_kakao_limit(self):
        ingest_statement(
            statement_payload(
                rows=[row(f"가맹점{index}", 10_000 * index) for index in range(1, 30)]
            )
        )
        digest = build_digest()
        self.assertLessEqual(len(digest.message), 200)
        self.assertIn("2026년 9월", digest.message)

    def test_unclassified_is_named_once_not_twice(self):
        ingest_statement(
            statement_payload(rows=[row("이름없는가게ZZ", 500_000), row("스타벅스", 5_000)])
        )
        digest = build_digest()
        self.assertEqual(digest.message.count("미분류"), 1)

    def test_message_reports_groups_not_categories(self):
        """대분류라야 200자 안에서 한 달의 성격을 말할 수 있다."""
        ingest_statement(
            statement_payload(
                rows=[
                    row("스타벅스", 100_000),   # 외식
                    row("이마트", 200_000),     # 필수생활
                    row("SKT 요금", 50_000),    # 고정비
                ]
            )
        )
        message = build_digest().message
        for name in ("외식", "필수생활", "고정비"):
            self.assertIn(name, message)
        # 카테고리 이름이 아니라 대분류 이름이 나가야 한다.
        self.assertNotIn("카페·간식", message)
