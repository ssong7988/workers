from datetime import date, timedelta
from unittest import TestCase

from stock_importer.hable.history_screen import validate_period


class HistoryPeriodTests(TestCase):
    def rows(self, start, end):
        return [{"as_of": (start + timedelta(days=n)).isoformat()}
                for n in range((end-start).days+1)]

    def test_one_year_to_yesterday_is_accepted(self):
        validate_period(self.rows(date(2025,9,9), date(2026,9,8)),
                        date(2025,9,9), date(2026,9,9))

    def test_stale_end_and_missing_day_are_rejected(self):
        rows = self.rows(date(2025,9,9), date(2026,9,8))
        for invalid in (rows[:-10], rows[:20] + rows[21:]):
            with self.subTest(count=len(invalid)), self.assertRaises(RuntimeError):
                validate_period(invalid,date(2025,9,9),date(2026,9,9))
