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
        self.assertEqual(InvestmentAccount.objects.count(), 5)
        rows = BenchmarkAllocation.objects.all()
        self.assertEqual(rows.count(), 5)
        # 원본 합계 99.8%를 그대로 보존한다.
        self.assertEqual(sum(row.source_percent for row in rows), Decimal("99.8"))

    def test_running_twice_is_safe(self) -> None:
        self._run()
        self._run()
        self.assertEqual(InvestmentAccount.objects.count(), 5)
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
