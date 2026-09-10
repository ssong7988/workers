import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from portfolio.models import HableAccountDailyMetric
from report.stock_views import _summary
from .factories import login_staff, make_account


class PeriodSummaryTests(SimpleTestCase):
    def test_selected_period_excludes_earlier_profit_flows_and_drawdown(self):
        rows = [SimpleNamespace(
            market_value=Decimal(value), cumulative_external_flow=Decimal(flow),
            investment_pl=Decimal(profit), index_value=Decimal(index),
        ) for value, flow, profit, index in (
            ("1000000", "300000", "500000", "2"),
            ("1200000", "400000", "600000", "2.2"),
            ("1140000", "400000", "540000", "2.09"),
        )]
        summary = _summary(rows[-1], rows, Decimal("0.045"))
        self.assertEqual(summary["net_flow_text"], "+10만원")
        self.assertEqual(summary["investment_pl_text"], "+4만원")
        self.assertEqual(summary["period_return_text"], "+4.50%")
        self.assertEqual(summary["max_drawdown_text"], "-5.00%")


@override_settings(STOCK_API_TOKEN="history-test")
class HistoryImportTests(TestCase):
    def setUp(self):
        self.account = make_account(masked_number="338-***-781-01")
        HableAccountDailyMetric.objects.create(
            account=self.account, as_of=date(2025, 9, 8), market_value=100000,
            investment_pl=0, daily_return=0, account_cumulative_return=0,
        )

    def post_row(self, daily_return="0.01"):
        return self.client.post(reverse("stock-api:performance-history"),
            data=json.dumps({"accounts": [{"account_number": self.account.masked_number,
                "rows": [{"as_of": "2026-09-08", "market_value": "110000",
                    "deposit": "0", "withdrawal": "0", "investment_pl": "1000",
                    "daily_return": daily_return, "cumulative_return": "0.1"}]}]}),
            content_type="application/json", headers={"authorization": "Bearer history-test"})

    def test_shorter_reimport_preserves_older_days_and_is_idempotent(self):
        self.assertEqual(self.post_row().status_code, 201)
        self.assertEqual(self.post_row().status_code, 201)
        self.assertEqual(HableAccountDailyMetric.objects.count(), 2)

    def test_nonfinite_value_rejects_transaction(self):
        self.assertEqual(self.post_row("NaN").status_code, 400)
        self.assertEqual(HableAccountDailyMetric.objects.count(), 1)

    def test_new_query_baseline_does_not_erase_previously_recorded_return(self):
        self.post_row("0.03")
        self.post_row("0")
        self.assertEqual(HableAccountDailyMetric.objects.get(
            account=self.account, as_of=date(2026,9,8)).daily_return, Decimal("0.03"))


class PortfolioSelectionTests(TestCase):
    def setUp(self):
        login_staff(self.client)
        for key, rate in (("first", "0.1"), ("second", "-0.1")):
            account = make_account(key, alias=key)
            for day in (1, 2):
                HableAccountDailyMetric.objects.create(
                    account=account, as_of=date(2026, 9, day), market_value=100000,
                    deposit=10000 if key == "first" and day == 2 else 0,
                    withdrawal=0, investment_pl=1000 if day == 2 else 0,
                    daily_return=rate if day == 2 else 0, account_cumulative_return=0,
                )
        make_account("empty", alias="빈 계좌", institution="KB증권")

    def test_selecting_account_isolates_return_flow_and_keeps_range(self):
        response = self.client.get(reverse("stock-performance"), {"portfolio": "first", "range": "1m"})
        self.assertEqual(response.context["summary"]["period_return_text"], "+10.00%")
        self.assertEqual(response.context["summary"]["net_flow_text"], "+1만원")
        self.assertContains(response, 'range=1y&amp;portfolio=first')
        self.assertNotContains(response, "확정된 손익")

    def test_empty_account_does_not_show_other_portfolios_data(self):
        response = self.client.get(reverse("stock-performance"), {"portfolio": "empty"})
        self.assertFalse(response.context["has_data"])
        self.assertContains(response, "빈 계좌")
