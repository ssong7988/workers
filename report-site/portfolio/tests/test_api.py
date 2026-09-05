from __future__ import annotations

import json

from django.conf import settings
from django.test import TestCase, override_settings

from portfolio.models import DailyPortfolioMetric, PositionSnapshot

from .factories import balance_payload, hash_of, make_account, position


TOKEN = "stock-test-token"
IMPORT_URL = f"/{settings.STOCK_ROUTE_PREFIX}api/import-runs/"
STATUS_URL = f"/{settings.STOCK_ROUTE_PREFIX}api/status/"


@override_settings(STOCK_API_TOKEN=TOKEN)
class ImportApiTests(TestCase):
    def setUp(self) -> None:
        make_account()

    def _post(self, payload: dict, token: str = TOKEN):
        return self.client.post(
            IMPORT_URL,
            data=json.dumps(payload),
            content_type="application/json",
            headers={"authorization": f"Bearer {token}"},
        )

    def test_rejects_a_wrong_token(self) -> None:
        response = self._post({}, token="nope")
        self.assertEqual(response.status_code, 401)

    def test_stores_positions_and_reports_completeness(self) -> None:
        response = self._post(
            balance_payload(
                "kb-brokerage", "2026-09-01", [position("005930", "1000000")]
            )
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["positions"], 1)
        self.assertEqual(body["new_instruments"], ["005930"])
        self.assertEqual(body["complete_as_of"], "2026-09-01")
        self.assertEqual(PositionSnapshot.objects.count(), 1)
        # 완전 스냅샷이 생겼으므로 성과도 같은 요청 안에서 계산돼 있어야 한다.
        self.assertEqual(DailyPortfolioMetric.objects.count(), 1)

    def test_repeating_the_same_file_answers_200_and_changes_nothing(self) -> None:
        payload = balance_payload(
            "kb-brokerage", "2026-09-01", [position("005930", "1000000")]
        )
        self._post(payload)
        again = self._post(payload)
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json()["duplicate"])
        self.assertEqual(PositionSnapshot.objects.count(), 1)

    def test_invalid_payload_is_a_400(self) -> None:
        response = self._post(
            {"account": "kb-brokerage", "as_of": "2026-09-01", "document_type": "balance"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_request")

    def test_bad_file_hash_is_rejected(self) -> None:
        payload = balance_payload(
            "kb-brokerage", "2026-09-01", [position("005930", "1")], file_hash="abc"
        )
        self.assertEqual(self._post(payload).status_code, 400)

    def test_get_is_not_allowed(self) -> None:
        response = self.client.get(
            IMPORT_URL, headers={"authorization": f"Bearer {TOKEN}"}
        )
        self.assertEqual(response.status_code, 405)


@override_settings(STOCK_API_TOKEN=TOKEN)
class StatusApiTests(TestCase):
    def test_reports_missing_accounts_and_unclassified_instruments(self) -> None:
        make_account("kb-brokerage")
        make_account("kb-isa", account_type="isa")
        self.client.post(
            IMPORT_URL,
            data=json.dumps(
                balance_payload(
                    "kb-brokerage",
                    "2026-09-01",
                    [position("005930", "1000000")],
                    file_hash=hash_of("one"),
                )
            ),
            content_type="application/json",
            headers={"authorization": f"Bearer {TOKEN}"},
        )
        body = self.client.get(
            STATUS_URL, headers={"authorization": f"Bearer {TOKEN}"}
        ).json()
        self.assertIsNone(body["complete_as_of"])
        self.assertEqual(body["unclassified_instruments"], 1)
        statuses = {row["account"]: row["status"] for row in body["accounts"]}
        self.assertEqual(statuses["kb-isa"], "missing")


class TokenNotConfiguredTests(TestCase):
    @override_settings(STOCK_API_TOKEN="")
    def test_unset_token_is_a_503_not_an_open_endpoint(self) -> None:
        response = self.client.get(STATUS_URL, headers={"authorization": "Bearer x"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "token_not_configured")
