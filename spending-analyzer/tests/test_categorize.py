import tempfile
import unittest
from pathlib import Path

from spending_analyzer.categorize import (
    FINANCIAL_COST_CATEGORY,
    categorize,
    load_cache,
    load_rules,
    normalize_merchant,
    promote_to_rules,
    save_cache,
)
from spending_analyzer.models import UNCATEGORIZED, Transaction

RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "rules.yaml"

RULES_YAML = """
categories: [카페·간식, 편의점·마트, 금융비용, 기타]
rules:
  - category: 편의점·마트
    keywords: [이마트24, 이마트]
  - category: 카페·간식
    keywords: [스타벅스]
"""


def make_transaction(merchant: str, payment_type: str = "일시불") -> Transaction:
    return Transaction(
        billing_month="2026-09",
        used_at="2026-08-14",
        merchant=merchant,
        merchant_norm=normalize_merchant(merchant),
        billed_won=5_000,
        total_won=5_000,
        payment_type=payment_type,
    )


def load_temp_rules(text: str):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.yaml"
        path.write_text(text, encoding="utf-8")
        return load_rules(path)


class NormalizeMerchantTest(unittest.TestCase):
    def test_strips_whitespace_and_corporate_forms(self):
        self.assertEqual(normalize_merchant("(주) 이마트 과천점"), "이마트과천점")
        self.assertEqual(normalize_merchant("㈜스타벅스코리아"), "스타벅스코리아")

    def test_uppercases_so_ascii_keywords_match_either_case(self):
        self.assertEqual(normalize_merchant("netflix.com"), "NETFLIX.COM")

    def test_empty_input_stays_empty(self):
        self.assertEqual(normalize_merchant(""), "")


class RuleMatchTest(unittest.TestCase):
    def setUp(self):
        self.rules = load_temp_rules(RULES_YAML)

    def test_a_branch_matches_its_chain(self):
        matched = self.rules.match(normalize_merchant("스타벅스 과천점"))
        self.assertEqual(matched.category, "카페·간식")

    def test_the_first_listed_rule_wins(self):
        # 이마트24 is a convenience store and 이마트 a supermarket; listing the
        # narrower keyword first is what keeps them apart.
        matched = self.rules.match(normalize_merchant("이마트24 과천점"))
        self.assertEqual(matched.keyword, "이마트24")

    def test_unknown_merchant_has_no_match(self):
        self.assertIsNone(self.rules.match(normalize_merchant("동네분식")))

    def test_canonical_name_groups_branches_of_one_chain(self):
        self.assertEqual(self.rules.canonical(normalize_merchant("스타벅스 판교점")), "스타벅스")
        self.assertEqual(self.rules.canonical(normalize_merchant("스타벅스 과천점")), "스타벅스")

    def test_canonical_name_of_an_unknown_merchant_is_itself(self):
        self.assertEqual(self.rules.canonical("동네분식"), "동네분식")


class LoadRulesTest(unittest.TestCase):
    def test_the_shipped_rules_file_loads(self):
        rules = load_rules(RULES_PATH)
        self.assertIn("식비", rules.categories)
        self.assertTrue(rules.rules)

    def test_rejects_a_category_not_in_the_list(self):
        with self.assertRaisesRegex(ValueError, "categories 목록에 없습니다"):
            load_temp_rules("categories: [식비]\nrules:\n  - category: 없는것\n    keywords: [a]\n")

    def test_rejects_a_rule_with_no_keywords(self):
        with self.assertRaisesRegex(ValueError, "keywords"):
            load_temp_rules("categories: [식비]\nrules:\n  - category: 식비\n    keywords: []\n")

    def test_rejects_uncategorized_as_a_real_category(self):
        with self.assertRaisesRegex(ValueError, "예약된 이름"):
            load_temp_rules(f"categories: [{UNCATEGORIZED}]\nrules: []\n")

    def test_keywords_are_normalized_so_spaced_entries_still_match(self):
        rules = load_temp_rules(
            "categories: [구독]\nrules:\n  - category: 구독\n    keywords: ['net flix']\n"
        )
        self.assertIsNotNone(rules.match(normalize_merchant("NETFLIX.COM")))


class CategorizeTest(unittest.TestCase):
    def setUp(self):
        self.rules = load_temp_rules(RULES_YAML)

    def test_rules_assign_a_category_and_record_the_source(self):
        transactions = [make_transaction("스타벅스 과천점")]
        result = categorize(transactions, self.rules)
        self.assertEqual(transactions[0].category, "카페·간식")
        self.assertEqual(transactions[0].category_source, "rule")
        self.assertEqual(result.by_rule, 1)

    def test_annual_fee_bypasses_the_keyword_rules_entirely(self):
        # An annual fee is a charge, not spending at a merchant, so the payment
        # type must settle it even when the name would match a keyword.
        transactions = [make_transaction("스타벅스제휴카드연회비", payment_type="연회비")]
        result = categorize(transactions, self.rules)
        self.assertEqual(transactions[0].category, FINANCIAL_COST_CATEGORY)
        self.assertEqual(transactions[0].category_source, "payment_type")
        self.assertEqual(result.by_payment_type, 1)

    def test_interest_is_a_financial_cost_too(self):
        transactions = [make_transaction("할부수수료", payment_type="이자")]
        categorize(transactions, self.rules)
        self.assertEqual(transactions[0].category, FINANCIAL_COST_CATEGORY)

    def test_cache_covers_what_the_rules_miss(self):
        transactions = [make_transaction("동네분식")]
        result = categorize(transactions, self.rules, cache={"동네분식": "기타"})
        self.assertEqual(transactions[0].category, "기타")
        self.assertEqual(transactions[0].category_source, "ai")
        self.assertEqual(result.by_cache, 1)

    def test_a_cached_category_outside_the_list_is_ignored(self):
        transactions = [make_transaction("동네분식")]
        result = categorize(transactions, self.rules, cache={"동네분식": "없는카테고리"})
        self.assertEqual(transactions[0].category, UNCATEGORIZED)
        self.assertEqual(result.unmatched, ["동네분식"])

    def test_unmatched_merchants_are_reported_once_each(self):
        transactions = [make_transaction("동네분식"), make_transaction("동네분식")]
        result = categorize(transactions, self.rules)
        self.assertEqual(result.unmatched, ["동네분식"])
        self.assertEqual(result.total_matched, 0)

    def test_recategorizing_clears_a_stale_category(self):
        transactions = [make_transaction("동네분식")]
        transactions[0].category = "카페·간식"
        transactions[0].category_source = "rule"
        categorize(transactions, self.rules)
        self.assertEqual(transactions[0].category, UNCATEGORIZED)
        self.assertEqual(transactions[0].category_source, "")


class CachePersistenceTest(unittest.TestCase):
    def test_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "category-cache.json"
            save_cache(path, {"동네분식": "식비"})
            self.assertEqual(load_cache(path), {"동네분식": "식비"})

    def test_missing_cache_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_cache(Path(directory) / "none.json"), {})

    def test_corrupt_cache_is_empty_rather_than_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_cache(path), {})


class PromoteToRulesTest(unittest.TestCase):
    def promote(self, assignments):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "rules.yaml"
        path.write_text(RULES_YAML, encoding="utf-8")
        added = promote_to_rules(path, assignments)
        return added, load_rules(path)

    def test_a_promoted_merchant_matches_without_the_api_next_time(self):
        added, rules = self.promote({"동네분식": "기타"})
        self.assertEqual(added, 1)
        self.assertEqual(rules.match("동네분식").category, "기타")

    def test_promotion_keeps_the_existing_rules_working(self):
        _, rules = self.promote({"동네분식": "기타"})
        self.assertEqual(rules.match(normalize_merchant("스타벅스 과천점")).category, "카페·간식")

    def test_an_unknown_category_is_skipped(self):
        added, _ = self.promote({"동네분식": "없는카테고리"})
        self.assertEqual(added, 0)

    def test_promoting_nothing_touches_nothing(self):
        self.assertEqual(self.promote({})[0], 0)


if __name__ == "__main__":
    unittest.main()
