"""수집기가 계좌 ID가 아니라 계좌번호를 보낼 때.

mable 화면에는 `kb-isa` 같은 우리 ID가 없다. 화면에 있는 것은 계좌번호뿐이고,
어느 번호가 ISA인지 아는 것은 사람이다. 그래서 그 연결은 admin의 마스킹
계좌번호에 두고, 여기서는 조회만 한다 - 모르는 번호를 짐작해 붙이지 않는다.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.test import TestCase, override_settings

from portfolio.importing import PortfolioImportError, record_import_run
from portfolio.models import PositionSnapshot

from .factories import balance_payload, hash_of, make_account, position


MASKED = "338-***-400 01"
STATUS_URL = f"/{settings.STOCK_ROUTE_PREFIX}api/status/"


def by_number(number: str, as_of: str = "2026-09-05") -> dict:
    payload = balance_payload("", as_of, [position("005930", "1000000")])
    payload.pop("account")
    payload["account_number"] = number
    payload["file_hash"] = hash_of(f"{number}:{as_of}")
    return payload


class ResolveByNumberTests(TestCase):
    def test_finds_the_account_carrying_that_masked_number(self) -> None:
        make_account("kb-isa", account_type="isa", masked_number=MASKED)
        result = record_import_run(by_number(MASKED))
        self.assertEqual(result.run.account_id, "kb-isa")
        self.assertEqual(PositionSnapshot.objects.count(), 1)

    def test_an_unknown_number_says_what_to_do_in_admin(self) -> None:
        make_account("kb-isa", account_type="isa", masked_number=MASKED)
        with self.assertRaises(PortfolioImportError) as caught:
            record_import_run(by_number("373-***-206 01"))
        message = str(caught.exception)
        self.assertIn("373-***-206 01", message)
        self.assertIn("마스킹 계좌번호", message)

    def test_two_accounts_sharing_a_number_is_refused(self) -> None:
        make_account("kb-isa", account_type="isa", masked_number=MASKED)
        make_account("kb-pension-1", account_type="pension", masked_number=MASKED)
        with self.assertRaises(PortfolioImportError):
            record_import_run(by_number(MASKED))

    def test_an_inactive_account_is_refused(self) -> None:
        make_account("kb-isa", account_type="isa", masked_number=MASKED, active=False)
        with self.assertRaises(PortfolioImportError):
            record_import_run(by_number(MASKED))

    def test_neither_key_is_refused(self) -> None:
        payload = by_number(MASKED)
        payload.pop("account_number")
        with self.assertRaises(PortfolioImportError):
            record_import_run(payload)

    def test_the_account_id_still_works(self) -> None:
        make_account("kb-brokerage", masked_number=MASKED)
        payload = balance_payload(
            "kb-brokerage", "2026-09-05", [position("005930", "1000000")]
        )
        self.assertEqual(record_import_run(payload).run.account_id, "kb-brokerage")


@override_settings(STOCK_API_TOKEN="stock-test-token")
class StatusExposesTheNumberTests(TestCase):
    def test_status_shows_which_accounts_still_need_a_number(self) -> None:
        make_account("kb-isa", account_type="isa", masked_number=MASKED)
        make_account("kb-pension-1", account_type="pension")
        body = self.client.get(
            STATUS_URL, headers={"authorization": "Bearer stock-test-token"}
        ).json()
        numbers = {row["account"]: row["masked_number"] for row in body["accounts"]}
        self.assertEqual(numbers["kb-isa"], MASKED)
        self.assertEqual(numbers["kb-pension-1"], "")


@override_settings(STOCK_API_TOKEN="stock-test-token")
class ImportApiByNumberTests(TestCase):
    def test_the_api_accepts_a_number_and_answers_201(self) -> None:
        make_account("kb-isa", account_type="isa", masked_number=MASKED)
        response = self.client.post(
            f"/{settings.STOCK_ROUTE_PREFIX}api/import-runs/",
            data=json.dumps(by_number(MASKED)),
            content_type="application/json",
            headers={"authorization": "Bearer stock-test-token"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["import_run"]["account"], "kb-isa")

    def test_an_unknown_number_is_a_400_not_a_silent_success(self) -> None:
        make_account("kb-isa", account_type="isa", masked_number=MASKED)
        response = self.client.post(
            f"/{settings.STOCK_ROUTE_PREFIX}api/import-runs/",
            data=json.dumps(by_number("373-***-206 01")),
            content_type="application/json",
            headers={"authorization": "Bearer stock-test-token"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_request")
