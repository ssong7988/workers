"""인증 실패 뒤 낡은 잔고를 복사하거나 다른 화면을 클릭하지 않는다."""
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_importer.hable import window
from stock_importer.hable.collector import HableCollector


class QueryStateTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(window, "process_id", return_value=77),
            patch.object(window, "notice_dialogs", return_value=[3]),
            patch.object(window, "descendants", return_value=[4, 5]),
            patch.object(window, "class_name", side_effect=lambda h: "Static" if h == 4 else "Edit"),
            patch.object(window.user32, "IsWindowEnabled", return_value=True),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_password_notice_does_not_read_edit_value(self):
        with patch.object(window, "window_text", return_value="비밀번호를 입력하세요.") as text:
            with self.assertRaisesRegex(window.AccountPasswordRequired, "보안설정"):
                window.ensure_query_ready(1, 2)
        text.assert_called_once_with(4)

    def test_logout_is_not_password_request(self):
        with patch.object(window, "window_text", return_value="다시 로그인하세요."):
            with self.assertRaises(window.HableError) as result:
                window.ensure_query_ready(1, 2)
        self.assertNotIsInstance(result.exception, window.AccountPasswordRequired)

    def test_unreadable_modal_is_not_coordinate_error(self):
        with patch.object(window, "window_text", return_value=""), patch.object(
            window.user32, "IsWindowEnabled", return_value=False
        ):
            with self.assertRaisesRegex(window.HableError, "대화상자"):
                window.ensure_query_ready(1, 2)

    def test_enabled_screen_without_auth_notice_passes(self):
        with patch.object(window, "notice_dialogs", return_value=[]):
            window.ensure_query_ready(1, 2)


class CollectorAuthTests(unittest.TestCase):
    def test_password_after_query_prevents_copy_and_export(self):
        collector = HableCollector(Path("unused"))
        with patch.object(window, "ensure_query_ready", side_effect=[
            None, window.AccountPasswordRequired("password required")
        ]), patch("stock_importer.hable.collector.click_toolbar") as click, patch(
            "stock_importer.hable.collector.copy_grid"
        ) as copy, patch("stock_importer.hable.collector.export_grid") as export:
            with self.assertRaises(window.AccountPasswordRequired):
                collector._read_table(1, 2, None)
        click.assert_called_once()
        copy.assert_not_called()
        export.assert_not_called()

    def test_existing_modal_prevents_query(self):
        with patch.object(window, "ensure_query_ready", side_effect=window.AccountPasswordRequired()), patch(
            "stock_importer.hable.collector.click_toolbar"
        ) as click:
            with self.assertRaises(window.AccountPasswordRequired):
                HableCollector(Path("unused"))._query(1, 2, None)
        click.assert_not_called()

    def test_probe_also_stops_before_capture_on_auth_failure(self):
        collector = HableCollector(Path("unused"))
        with patch.object(window, "rect", return_value=(0, 0, 800, 600)), patch.object(
            window, "process_id", return_value=77
        ), patch.object(window, "notice_dialogs", return_value=[]), patch.object(
            window, "panes", return_value=[]
        ), patch.object(collector, "_grid_pane", return_value=None), patch.object(
            collector, "_query", side_effect=window.AccountPasswordRequired()
        ), patch("stock_importer.hable.collector.capture") as capture:
            with self.assertRaises(window.AccountPasswordRequired):
                collector._probe(1, 2)
        capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
