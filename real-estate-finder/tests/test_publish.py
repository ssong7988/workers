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


def _verb(command: list[str]) -> str:
    """The git subcommand, past the -c options that silence credential prompts."""
    return command[len(publish.NO_CREDENTIAL_PROMPT) + 1]


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


class DeployTests(unittest.TestCase):
    def _runner(self, results: dict[str, subprocess.CompletedProcess]):
        calls: list[list[str]] = []

        def fake_run(command, cwd, env, timeout):
            calls.append(command)
            return results.get(_verb(command), _completed(0))

        return fake_run, calls

    def test_pushes_the_committed_report_data(self) -> None:
        # `diff --cached` exits non-zero when there is something staged.
        fake_run, calls = self._runner({"diff": _completed(1)})
        with mock.patch.object(publish, "_run", fake_run):
            publish.deploy_site(Path("site"))

        verbs = [_verb(command) for command in calls]
        self.assertEqual(verbs, ["add", "diff", "commit", "push"])
        self.assertIn("HEAD:main", calls[-1])

    def test_unchanged_data_skips_the_commit(self) -> None:
        fake_run, calls = self._runner({"diff": _completed(0)})
        with mock.patch.object(publish, "_run", fake_run):
            publish.deploy_site(Path("site"))

        self.assertEqual([_verb(command) for command in calls], ["add", "diff", "push"])

    def test_push_failure_asks_for_a_manual_publish(self) -> None:
        fake_run, _calls = self._runner(
            {"diff": _completed(0), "push": _completed(128, stderr="Authentication failed")}
        )
        with mock.patch.object(publish, "_run", fake_run):
            with self.assertRaises(publish.ManualPublishRequired) as caught:
                publish.deploy_site(Path("site"))

        message = str(caught.exception)
        self.assertIn("Authentication failed", message)
        self.assertIn("--verify-only", message, "수동 배포 안내가 따라와야 한다")


class PublishReportTests(unittest.TestCase):
    def test_reports_false_when_the_deploy_did_not_land(self) -> None:
        with mock.patch.object(publish, "build_site"), mock.patch.object(
            publish, "deploy_site"
        ), mock.patch.object(publish, "is_live", return_value=False):
            self.assertFalse(publish.publish_report(OBSERVED_AT, "https://report"))

    def test_reports_true_once_the_live_page_matches(self) -> None:
        with mock.patch.object(publish, "build_site"), mock.patch.object(
            publish, "deploy_site"
        ), mock.patch.object(publish, "is_live", return_value=True):
            self.assertTrue(publish.publish_report(OBSERVED_AT, "https://report"))


if __name__ == "__main__":
    unittest.main()
