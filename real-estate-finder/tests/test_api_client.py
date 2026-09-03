from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest import mock

from real_estate_finder.api_client import ApiError, ReportSiteClient
from real_estate_finder.cli import _deduplicate
from real_estate_finder.models import Listing


def client() -> ReportSiteClient:
    return ReportSiteClient("http://127.0.0.1:8000/", token="secret")


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        self.close()


def json_response(payload: dict) -> FakeResponse:
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def listing(listing_id: str, condition_id: str = "weverfield") -> Listing:
    return Listing(
        condition_id=condition_id,
        listing_id=listing_id,
        complex_name="과천위버필드",
        type_name="84A",
        exclusive_area_m2=84.94,
        price_won=2_400_000_000,
        floor_text="10/30층",
        direction="남향",
        description="",
        url="https://fin.land.naver.com/articles/1",
        observed_at="2026-09-03T08:00:00+09:00",
    )


class TokenTests(unittest.TestCase):
    def test_missing_token_names_the_file_to_fix(self) -> None:
        with self.assertRaises(ApiError) as caught:
            ReportSiteClient("http://127.0.0.1:8000", token="")
        self.assertIn("FINDER_API_TOKEN", str(caught.exception))


class RequestTests(unittest.TestCase):
    def test_health_sends_the_bearer_token(self) -> None:
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = json_response({"status": "ok", "database": "ok"})
            self.assertEqual(client().health()["status"], "ok")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(request.full_url, "http://127.0.0.1:8000/api/health/")
        self.assertEqual(request.get_method(), "GET")

    def test_post_scan_sends_json(self) -> None:
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value = json_response({"scan": {"success": True}})
            client().post_scan({"observations": []})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"observations": []})

    def test_unreachable_server_points_at_run_site(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with self.assertRaises(ApiError) as caught:
                client().health()
        self.assertIn("run-site.bat", str(caught.exception))

    def test_rejected_request_repeats_the_servers_reason(self) -> None:
        body = json.dumps({"error": "observations는 배열이어야 합니다.", "code": "invalid_request"})
        error = urllib.error.HTTPError(
            "http://127.0.0.1:8000/api/scans/", 400, "Bad Request", {}, io.BytesIO(body.encode())
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ApiError) as caught:
                client().post_scan({})
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.code, "invalid_request")
        self.assertIn("observations는 배열이어야 합니다.", str(caught.exception))

    def test_unauthorized_names_the_token_setting(self) -> None:
        error = urllib.error.HTTPError(
            "http://127.0.0.1:8000/api/health/", 401, "Unauthorized", {}, io.BytesIO(b"{}")
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ApiError) as caught:
                client().health()
        self.assertIn("FINDER_API_TOKEN", str(caught.exception))


class DeduplicateTests(unittest.TestCase):
    """The server rolls a whole scan back on a duplicate, so drop it here."""

    def test_same_article_twice_under_one_condition_is_sent_once(self) -> None:
        observations, dropped = _deduplicate(
            [listing("111"), listing("222"), listing("111")]
        )
        self.assertEqual([item["listing_id"] for item in observations], ["111", "222"])
        self.assertEqual(dropped, 1)

    def test_same_article_under_two_conditions_is_kept(self) -> None:
        observations, dropped = _deduplicate(
            [listing("111", "weverfield"), listing("111", "raemian")]
        )
        self.assertEqual(len(observations), 2)
        self.assertEqual(dropped, 0)


if __name__ == "__main__":
    unittest.main()
