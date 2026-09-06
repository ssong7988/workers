"""Reading the sign-in credentials, and deciding when to use them.

The browser side is not tested here - a real sign-in needs Naver. What is
tested is everything that decides *whether* to sign in and *with what*, which
is where a mistake would either leak a secret or leave the 06:00 health check
silently signed out.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from real_estate_finder.collector import CollectionError, NaverBrowserCollector
from real_estate_finder.credentials import naver_credentials, parse_env_file


class ParseEnvFileTests(unittest.TestCase):
    def test_reads_pairs_and_ignores_comments(self) -> None:
        values = parse_env_file("# note\n\nNAVER_ID=someone\nNAVER_PASSWORD=secret\n")

        self.assertEqual(values, {"NAVER_ID": "someone", "NAVER_PASSWORD": "secret"})

    def test_quotes_protect_a_password_that_needs_them(self) -> None:
        values = parse_env_file('NAVER_PASSWORD=" a#b=c "\n')

        self.assertEqual(values["NAVER_PASSWORD"], " a#b=c ")

    def test_only_the_first_equals_splits(self) -> None:
        values = parse_env_file("NAVER_PASSWORD=a=b=c\n")

        self.assertEqual(values["NAVER_PASSWORD"], "a=b=c")


class NaverCredentialsTests(unittest.TestCase):
    def _env_file(self, directory: str, text: str) -> Path:
        path = Path(directory) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_the_env_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._env_file(directory, "NAVER_ID=someone\nNAVER_PASSWORD=secret\n")

            credentials = naver_credentials(environ={}, env_files=[path])

        self.assertIsNotNone(credentials)
        self.assertEqual(credentials.username, "someone")
        self.assertEqual(credentials.password, "secret")

    def test_environment_wins_over_the_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._env_file(directory, "NAVER_ID=file\nNAVER_PASSWORD=file-secret\n")

            credentials = naver_credentials(
                environ={"NAVER_ID": "env", "NAVER_PASSWORD": "env-secret"},
                env_files=[path],
            )

        self.assertEqual(credentials.username, "env")
        self.assertEqual(credentials.password, "env-secret")

    def test_half_configured_is_the_same_as_unconfigured(self) -> None:
        self.assertIsNone(naver_credentials(environ={"NAVER_ID": "someone"}, env_files=[]))
        self.assertIsNone(naver_credentials(environ={"NAVER_PASSWORD": "secret"}, env_files=[]))

    def test_a_missing_file_is_not_an_error(self) -> None:
        self.assertIsNone(
            naver_credentials(environ={}, env_files=[Path("does-not-exist.env")])
        )

    def test_repr_does_not_carry_the_password(self) -> None:
        credentials = naver_credentials(
            environ={"NAVER_ID": "someone", "NAVER_PASSWORD": "secret"}, env_files=[]
        )

        self.assertNotIn("secret", repr(credentials))


class HealthCheckSignInTests(unittest.TestCase):
    """`check-login` runs unattended, so it has to act, not only report."""

    def setUp(self) -> None:
        self.collector = NaverBrowserCollector(Path("unused"))

    @patch.object(NaverBrowserCollector, "_sign_in")
    @patch.object(NaverBrowserCollector, "_is_logged_in", return_value=True)
    def test_a_live_session_is_left_alone(self, _logged_in, sign_in) -> None:
        self.collector._verify_or_sign_in(object())

        sign_in.assert_not_called()

    @patch.object(NaverBrowserCollector, "_sign_in", return_value=True)
    @patch.object(NaverBrowserCollector, "_is_logged_in", side_effect=[False, True])
    def test_a_signed_out_browser_is_signed_in(self, _logged_in, sign_in) -> None:
        self.collector._verify_or_sign_in(object())

        sign_in.assert_called_once()

    @patch.object(NaverBrowserCollector, "_sign_in", return_value=False)
    @patch.object(NaverBrowserCollector, "_is_logged_in", return_value=False)
    def test_without_credentials_the_error_says_what_to_configure(
        self, _logged_in, _sign_in
    ) -> None:
        with self.assertRaisesRegex(CollectionError, "NAVER_PASSWORD"):
            self.collector._verify_or_sign_in(object())

    @patch("real_estate_finder.collector.naver_credentials", return_value=None)
    def test_sign_in_without_credentials_never_touches_the_page(self, _credentials) -> None:
        page = object()  # Any attribute use would raise.

        self.assertFalse(self.collector._sign_in(page))

    @patch.object(NaverBrowserCollector, "_is_logged_in", return_value=False)
    @patch.object(
        NaverBrowserCollector, "_sign_in", side_effect=CollectionError("자동입력 방지")
    )
    def test_the_interactive_path_falls_back_instead_of_raising(
        self, _sign_in, _logged_in
    ) -> None:
        self.assertFalse(self.collector._try_sign_in(object()))


if __name__ == "__main__":
    unittest.main()
