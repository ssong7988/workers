import unittest
from pathlib import Path

from spending_analyzer.analyze import analyze
from spending_analyzer.categorize import categorize, load_rules, normalize_merchant
from spending_analyzer.charts import (
    Bar,
    Column,
    Segment,
    column_chart,
    diverging_bars,
    format_man,
    format_percent,
    format_won,
    horizontal_bars,
    stacked_bar,
)
from spending_analyzer.demo import build_demo_statements
from spending_analyzer.models import AnalysisConfig, Statement, Transaction
from spending_analyzer.report import render_html

RULES = load_rules(Path(__file__).resolve().parents[1] / "config" / "rules.yaml")


class FormatTest(unittest.TestCase):
    def test_won_uses_thousands_separators(self):
        self.assertEqual(format_won(1_234_567), "1,234,567원")

    def test_won_keeps_a_refund_negative(self):
        self.assertEqual(format_won(-5_600), "-5,600원")

    def test_man_switches_units_as_amounts_grow(self):
        self.assertEqual(format_man(56_000), "5.6만")
        self.assertEqual(format_man(1_270_900), "127만")
        self.assertEqual(format_man(15_000_000), "1,500만")
        self.assertEqual(format_man(150_000_000), "1.50억")

    def test_man_of_zero_is_plain(self):
        self.assertEqual(format_man(0), "0")

    def test_percent_of_none_is_a_dash_not_a_fake_number(self):
        self.assertEqual(format_percent(None), "—")
        self.assertEqual(format_percent(0.059), "+5.9%")


class ChartTest(unittest.TestCase):
    def test_empty_input_renders_a_note_instead_of_a_blank_chart(self):
        self.assertIn("표시할", column_chart([]))
        self.assertIn("표시할", horizontal_bars([]))
        self.assertIn("비교할", diverging_bars([]))

    def test_column_chart_emits_one_mark_per_month(self):
        svg = column_chart([Column("26.08", 100), Column("26.09", 200)])
        self.assertEqual(svg.count("<title>"), 2)
        self.assertIn("<svg", svg)

    def test_the_average_rule_is_labelled(self):
        svg = column_chart([Column("26.09", 100_000)], average=90_000)
        self.assertIn("평균", svg)
        self.assertIn('class="rule"', svg)

    def test_diverging_bars_use_opposite_poles(self):
        svg = diverging_bars([Bar("식비", 10_000), Bar("교통", -5_000)])
        self.assertIn("--diverge-up", svg)
        self.assertIn("--diverge-down", svg)

    def test_stacked_bar_ships_a_legend_with_values(self):
        html = stacked_bar([Segment("일시불", 70, 1), Segment("할부", 30, 2)])
        self.assertIn("legend", html)
        self.assertIn("일시불", html)
        # Three light-mode slots are under 3:1, so a visible value is required.
        self.assertIn("70원", html)

    def test_a_zero_segment_is_dropped_rather_than_drawn_at_zero_width(self):
        html = stacked_bar([Segment("일시불", 100, 1), Segment("해외", 0, 2)])
        self.assertNotIn("해외", html)

    def test_marks_carry_a_hover_title(self):
        svg = horizontal_bars([Bar("스타벅스", 10_000)])
        self.assertIn("<title>스타벅스 10,000원</title>", svg)


def build_analysis() -> dict:
    statements = build_demo_statements(months=4)
    transactions = [item for statement in statements for item in statement.transactions]
    categorize(transactions, RULES)
    return analyze(statements, RULES, AnalysisConfig())


class RenderTest(unittest.TestCase):
    def test_no_statements_renders_a_page_that_says_what_to_run(self):
        html = render_html({"empty": True})
        self.assertIn("scan-mail", html)
        self.assertIn("<!doctype html>", html)

    def test_full_page_carries_every_section(self):
        html = render_html(build_analysis())
        for heading in (
            "월별 청구액 추이",
            "카테고리별 지출",
            "카테고리별 전월 대비",
            "결제 유형 구성",
            "할부 잔여 부담",
            "고정비 / 변동비",
            "가맹점 TOP",
            "전체 거래",
            "미분류 가맹점",
        ):
            self.assertIn(heading, html, f"'{heading}' 섹션이 없습니다")

    def test_page_is_self_contained(self):
        html = render_html(build_analysis())
        # No CDN, no external font, no build step — it must open from disk.
        self.assertNotIn("http://", html.replace("http://127.0.0.1", ""))
        self.assertNotIn("https://", html)
        self.assertNotIn("<link", html)

    def test_dark_mode_is_defined_for_both_the_toggle_and_the_os_setting(self):
        html = render_html(build_analysis())
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn(':root[data-theme="dark"]', html)

    def test_a_merchant_name_cannot_inject_markup(self):
        statement = Statement(
            billing_month="2026-09",
            payment_date="2026-09-25",
            total_billed_won=1_000,
            transactions=[
                Transaction(
                    billing_month="2026-09",
                    used_at="2026-09-01",
                    merchant="<script>alert(1)</script>",
                    merchant_norm=normalize_merchant("<script>alert(1)</script>"),
                    billed_won=1_000,
                    total_won=1_000,
                    payment_type="일시불",
                )
            ],
        )
        html = render_html(analyze([statement], RULES, AnalysisConfig()))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
