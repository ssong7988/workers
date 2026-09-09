from __future__ import annotations

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from portfolio.models import (
    UNCLASSIFIED_ASSET_CLASS_ID,
    AssetClass,
    BenchmarkAllocation,
    Instrument,
    InvestmentAccount,
)


class SeedCommandTests(TestCase):
    def _run(self) -> str:
        out = StringIO()
        call_command("import_portfolio_seed", stdout=out)
        return out.getvalue()

    def test_seeds_classes_accounts_and_benchmark(self) -> None:
        self._run()
        self.assertTrue(AssetClass.objects.filter(pk="korea-stock").exists())
        self.assertTrue(
            AssetClass.objects.filter(pk=UNCLASSIFIED_ASSET_CLASS_ID).exists()
        )
        self.assertEqual(InvestmentAccount.objects.count(), 6)
        rows = BenchmarkAllocation.objects.all()
        self.assertEqual(rows.count(), 5)
        # 원본 합계 99.8%를 그대로 보존한다.
        self.assertEqual(sum(row.source_percent for row in rows), Decimal("99.8"))

    def test_running_twice_is_safe(self) -> None:
        self._run()
        self._run()
        self.assertEqual(InvestmentAccount.objects.count(), 6)
        self.assertEqual(BenchmarkAllocation.objects.count(), 5)

    def test_it_classifies_known_names_but_leaves_the_rest_alone(self) -> None:
        self._run()
        unknown = AssetClass.objects.get(pk=UNCLASSIFIED_ASSET_CLASS_ID)
        Instrument.objects.create(code="005930", name="삼성전자", asset_class=unknown)
        Instrument.objects.create(code="XXXX", name="처음 보는 종목", asset_class=unknown)
        self._run()
        self.assertEqual(Instrument.objects.get(pk="005930").asset_class_id, "korea-stock")
        self.assertEqual(
            Instrument.objects.get(pk="XXXX").asset_class_id, UNCLASSIFIED_ASSET_CLASS_ID
        )

    def test_a_hand_set_classification_is_not_reverted(self) -> None:
        self._run()
        bonds = AssetClass.objects.get(pk="bond")
        Instrument.objects.create(code="005930", name="삼성전자", asset_class=bonds)
        self._run()
        self.assertEqual(Instrument.objects.get(pk="005930").asset_class_id, "bond")

    def test_makes_a_place_for_coins(self) -> None:
        """수량만 넣으면 되도록 코인 지갑과 코인 종목을 미리 만들어 둔다."""
        self._run()
        wallet = InvestmentAccount.objects.get(pk="coin-wallet")
        # 시세를 못 받은 날이 주식 성과까지 지우면 안 된다.
        self.assertFalse(wallet.required)
        bitcoin = Instrument.objects.get(pk="KRW-BTC")
        self.assertEqual(bitcoin.price_source, "upbit:KRW-BTC")
        self.assertEqual(bitcoin.asset_class_id, "crypto")

    def test_does_not_undo_a_hand_made_change(self) -> None:
        self._run()
        Instrument.objects.filter(pk="KRW-BTC").update(
            asset_class_id=UNCLASSIFIED_ASSET_CLASS_ID, name="내가 고친 이름"
        )
        self._run()
        bitcoin = Instrument.objects.get(pk="KRW-BTC")
        self.assertEqual(bitcoin.name, "내가 고친 이름")

    def test_fills_a_blank_price_source(self) -> None:
        """수집기가 먼저 만든 종목에도 시세 출처를 붙여준다."""
        self._run()
        Instrument.objects.filter(pk="KRW-ETH").update(price_source="")
        self._run()
        self.assertEqual(
            Instrument.objects.get(pk="KRW-ETH").price_source, "upbit:KRW-ETH"
        )
