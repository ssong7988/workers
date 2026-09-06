"""언제 H-able을 깨울지, 그리고 무엇을 실패로 볼지.

창을 만지는 부분은 시험하지 않는다. 시험하는 것은 두 가지 규칙뿐이다 -
"지금 눌러도 되는가"와 "이 상태를 실패로 볼 것인가". 둘 다 순수 함수라
H-able 없이 돌아간다.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from stock_importer.hable import keepalive


class DecideTests(unittest.TestCase):
    def test_idle_person_means_go_ahead(self) -> None:
        decision = keepalive.decide(idle_seconds=600, seconds_since_touch=60)

        self.assertTrue(decision.touch)
        self.assertIn("입력이", decision.reason)

    def test_busy_person_is_left_alone(self) -> None:
        decision = keepalive.decide(idle_seconds=5, seconds_since_touch=60)

        self.assertFalse(decision.touch)
        self.assertIn("쓰는 중", decision.reason)

    def test_a_long_gap_wins_over_a_busy_person(self) -> None:
        """사람이 PC를 쓰는 것과 H-able 세션이 살아 있는 것은 별개다."""
        decision = keepalive.decide(idle_seconds=5, seconds_since_touch=3600)

        self.assertTrue(decision.touch)
        self.assertIn("분이 지났습니다", decision.reason)

    def test_first_ever_run_touches_even_if_busy(self) -> None:
        decision = keepalive.decide(idle_seconds=5, seconds_since_touch=None)

        self.assertTrue(decision.touch)

    def test_the_thresholds_are_the_boundary(self) -> None:
        self.assertTrue(
            keepalive.decide(
                idle_seconds=180, seconds_since_touch=0, min_idle=180
            ).touch
        )
        self.assertFalse(
            keepalive.decide(
                idle_seconds=179.9, seconds_since_touch=0, min_idle=180
            ).touch
        )


class ExitCodeTests(unittest.TestCase):
    def test_keepalive_never_fails(self) -> None:
        """H-able을 꺼 둔 날 매시 경고가 오면 곤란하다."""
        for state in (
            keepalive.STATE_OK,
            keepalive.STATE_SKIPPED,
            keepalive.STATE_BLOCKED,
            keepalive.STATE_NOT_RUNNING,
            keepalive.STATE_LOGGED_OUT,
            keepalive.STATE_PASSWORD_REQUIRED,
            keepalive.STATE_FAILED,
        ):
            with self.subTest(state=state):
                self.assertEqual(keepalive.exit_code(state, require_ready=False), 0)

    def test_the_pre_collection_check_fails_when_a_person_is_needed(self) -> None:
        for state in (
            keepalive.STATE_NOT_RUNNING,
            keepalive.STATE_SCREEN_MISSING,
            keepalive.STATE_LOGGED_OUT,
            keepalive.STATE_PASSWORD_REQUIRED,
            keepalive.STATE_FAILED,
        ):
            with self.subTest(state=state):
                self.assertEqual(keepalive.exit_code(state, require_ready=True), 1)

    def test_a_running_collection_is_not_a_failure(self) -> None:
        """수집이 돌고 있다는 것은 세션이 살아 있다는 뜻이다."""
        self.assertEqual(
            keepalive.exit_code(keepalive.STATE_BLOCKED, require_ready=True), 0
        )
        self.assertEqual(keepalive.exit_code(keepalive.STATE_OK, require_ready=True), 0)


class TouchRecordTests(unittest.TestCase):
    def test_no_record_reads_as_unknown(self) -> None:
        with TemporaryDirectory() as directory:
            self.assertIsNone(keepalive.seconds_since_touch(Path(directory)))

    def test_a_record_round_trips(self) -> None:
        moment = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            data_dir = Path(directory)
            keepalive.record_touch(data_dir, now=moment)

            elapsed = keepalive.seconds_since_touch(
                data_dir, now=moment + timedelta(minutes=15)
            )

        self.assertEqual(elapsed, 900)

    def test_a_broken_record_reads_as_unknown(self) -> None:
        with TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / keepalive.TOUCH_FILE).write_text("{oops", encoding="utf-8")

            self.assertIsNone(keepalive.seconds_since_touch(data_dir))


if __name__ == "__main__":
    unittest.main()
