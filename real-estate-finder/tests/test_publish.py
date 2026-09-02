from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from real_estate_finder import publish


OBSERVED_AT = "2026-09-02T16:53:33+09:00"
PAGE = (
    '<div class="mt-3" data-observed-at="' + OBSERVED_AT + '">'
    "<span>2026. 09. 02. 오후 04:53 조회</span></div>"
)


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class LiveCheckTests(unittest.TestCase):
    def test_reads_the_raw_timestamp_from_the_page(self) -> None:
        with mock.patch.object(publish, "_fetch", return_value=PAGE):
            self.assertEqual(publish.live_observed_at("https://report"), OBSERVED_AT)

    def test_page_without_the_marker_is_unknown(self) -> None:
        with mock.patch.object(publish, "_fetch", return_value="<div>없음</div>"):
            self.assertIsNone(publish.live_observed_at("https://report"))

    def test_unreachable_site_is_unknown(self) -> None:
        with mock.patch.object(publish, "_fetch", side_effect=OSError("연결 실패")):
            self.assertIsNone(publish.live_observed_at("https://report"))

    def test_live_matches_the_same_moment_in_another_offset(self) -> None:
        with mock.patch.object(publish, "live_observed_at", return_value="2026-09-02T07:53:33+00:00"):
            self.assertTrue(publish.is_live(OBSERVED_AT, "https://report"))

    def test_stale_page_is_not_live(self) -> None:
        with mock.patch.object(
            publish, "live_observed_at", return_value="2026-09-02T13:59:55+09:00"
        ):
            self.assertFalse(publish.is_live(OBSERVED_AT, "https://report"))


class DescribeLiveTests(unittest.TestCase):
    """`live_observed_at` collapses two failures into None; a human needs them apart."""

    def test_reports_the_served_timestamp(self) -> None:
        with mock.patch.object(publish, "_fetch", return_value=PAGE):
            self.assertEqual(publish.describe_live("https://report"), OBSERVED_AT)

    def test_distinguishes_an_unreachable_site(self) -> None:
        with mock.patch.object(publish, "_fetch", side_effect=OSError("연결 실패")):
            message = publish.describe_live("https://report")
        self.assertIn("접속하지 못했습니다", message)

    def test_distinguishes_a_build_too_old_to_carry_the_marker(self) -> None:
        with mock.patch.object(publish, "_fetch", return_value="<div>옛 빌드</div>"):
            message = publish.describe_live("https://report")
        self.assertIn("오래된 버전", message)


class BuildTests(unittest.TestCase):
    def test_runs_the_site_build_in_the_site_directory(self) -> None:
        calls: list[tuple] = []

        def fake_run(command, cwd, env, timeout):
            calls.append((command, cwd))
            return _completed(0)

        with mock.patch.object(publish.shutil, "which", return_value="npm"), mock.patch.object(
            publish, "_run", fake_run
        ):
            publish.build_site(Path("site"))

        self.assertEqual(calls, [(["npm", "run", "build"], Path("site"))])

    def test_build_failure_carries_the_output(self) -> None:
        with mock.patch.object(publish.shutil, "which", return_value="npm"), mock.patch.object(
            publish, "_run", return_value=_completed(1, stderr="Build failed: 타입 오류")
        ):
            with self.assertRaises(RuntimeError) as caught:
                publish.build_site(Path("site"))
        self.assertIn("타입 오류", str(caught.exception))


class ManualStepsTests(unittest.TestCase):
    def test_points_at_the_hosting_ui_not_a_git_push(self) -> None:
        """Pushing to the git remote does not deploy this site; the UI does."""
        self.assertIn("앱 호스팅 UI", publish.MANUAL_STEPS)
        self.assertIn("--verify-only", publish.MANUAL_STEPS)
        self.assertNotIn("push", publish.MANUAL_STEPS)


if __name__ == "__main__":
    unittest.main()
