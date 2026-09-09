from datetime import date
from decimal import Decimal

from django.test import TestCase

from portfolio.class_history import class_history
from portfolio.models import CashFlow, InstrumentDailyPrice
from report.class_charts import class_charts
from .factories import make_account, make_asset_class, make_instrument, record_balance


class AssetHistoryTests(TestCase):
    def setUp(self):
        self.account = make_account()
        self.asset = make_asset_class("stocks", "주식")
        self.stock = make_instrument("stock", self.asset)
        self.days = [date(2026,9,n) for n in (1,2,3)]
        for day, value in zip(self.days, ("1000000", "1200000", "1080000")):
            record_balance(self.account, self.stock, day, value)
        CashFlow.objects.create(account=self.account, instrument=self.stock,
            occurred_on=self.days[1], flow_type="buy", amount=100000, amount_krw=100000,
            external_key="buy-stock")

    def test_purchase_is_not_gain_and_mdd_uses_return_index(self):
        series = class_history(self.days[0],self.days[-1])
        self.assertEqual(len(series),1)
        last = series[0]["points"][-1]
        self.assertEqual(last["return"], Decimal("-0.01"))
        self.assertEqual(last["drawdown"], Decimal("-0.1"))
        self.assertEqual(last["mdd"], Decimal("-0.1"))

    def test_late_account_has_no_invented_history_and_account_filter_isolates(self):
        coin = make_account("coin", institution="wallet")
        token = make_instrument("coin",make_asset_class("coin", "코인"))
        record_balance(coin, token, self.days[-1], "500000")
        chart = class_charts(class_history(self.days[0],self.days[-1]))
        coin_series = next(row for row in chart["series"] if row["id"]=="coin")
        self.assertFalse(coin_series["available"])
        self.assertEqual(coin_series["return_text"], "-")
        self.assertEqual([row["id"] for row in class_history(self.days[0],self.days[-1],self.account.pk)], ["stocks"])
        self.assertEqual(len(chart["charts"]),3)
        self.assertTrue(all(len(graph["lines"])==1 for graph in chart["charts"]))

    def test_cutoff_does_not_include_earlier_peak(self):
        chart = class_charts(class_history(self.days[-1],self.days[-1]))
        self.assertEqual(chart["charts"], [])

    def test_current_basket_uses_fixed_quantities_and_daily_prices(self):
        wallet = make_account("wallet", institution="wallet")
        crypto = make_asset_class("crypto", "코인")
        btc = make_instrument("btc", crypto)
        eth = make_instrument("eth", crypto)
        record_balance(wallet, btc, self.days[-1], "100")
        eth_position = record_balance(wallet, eth, self.days[-1], "100")
        eth_position.quantity = Decimal("2")
        eth_position.save(update_fields=("quantity",))
        prices = (("100", "50"), ("120", "40"), ("90", "45"))
        for day, (btc_close, eth_close) in zip(self.days, prices):
            InstrumentDailyPrice.objects.create(as_of=day, instrument=btc, close=btc_close, source="upbit:BTC")
            InstrumentDailyPrice.objects.create(as_of=day, instrument=eth, close=eth_close, source="upbit:ETH")

        row = next(item for item in class_history(self.days[0], self.days[-1]) if item["id"] == "crypto")
        self.assertEqual(row["basis"], "current_holdings_price_index")
        self.assertEqual(len(row["points"]), 3)
        self.assertEqual(row["points"][-1]["return"], Decimal("-0.1"))
        self.assertEqual(row["points"][-1]["mdd"], Decimal("-0.1"))
        self.assertFalse(any(item["id"] == "crypto" for item in class_history(self.days[0], self.days[-1], self.account.pk)))

        earlier = next(
            item
            for item in class_history(self.days[0], self.days[1])
            if item["id"] == "crypto"
        )
        self.assertEqual(len(earlier["points"]), 2)
