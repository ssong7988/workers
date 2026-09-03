from unittest import mock

from django.test import SimpleTestCase

from properties import publish


class PublishTests(SimpleTestCase):
    databases = set()

    def test_loopback_and_non_https_urls_are_never_public(self) -> None:
        for url in ("", "http://example.com/r/x/", "https://127.0.0.1/r/x/"):
            with self.subTest(url=url):
                self.assertFalse(publish.is_public_report_url(url))

    @mock.patch.object(publish, "_fetch")
    def test_reads_marker_and_compares_equivalent_offsets(self, fetch) -> None:
        fetch.return_value = '<div data-observed-at="2026-09-03T00:00:00+00:00">'
        self.assertEqual(
            publish.live_observed_at("https://example.com/r/x/"),
            "2026-09-03T00:00:00+00:00",
        )
        self.assertTrue(
            publish.is_live(
                "2026-09-03T09:00:00+09:00", "https://example.com/r/x/"
            )
        )

    @mock.patch.object(publish, "_fetch", side_effect=OSError("offline"))
    def test_unreachable_report_is_not_live(self, _fetch) -> None:
        self.assertFalse(
            publish.is_live(
                "2026-09-03T09:00:00+09:00", "https://example.com/r/x/"
            )
        )
        self.assertIn("접속하지 못했습니다", publish.describe_live("https://example.com"))
