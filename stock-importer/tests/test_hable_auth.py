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


class BlockingDialogTests(unittest.TestCase):
    """제목을 직접 그려서 이름이 없는 모달도 알아본다."""

    def test_titleless_dialog_is_described_by_its_place(self):
        # KB의 필수 안내 팝업이 이 모양이다 - 제목도 컨트롤 글자도 없다.
        with patch.object(window, "window_text", return_value=""), patch.object(
            window, "dialog_labels", return_value=[]
        ), patch.object(window, "rect", return_value=(809, 388, 303, 265)):
            self.assertEqual(
                window.describe_dialog(9), "제목 없는 대화상자 (303x265 @ 809,388)"
            )

    def test_a_dialog_with_a_title_keeps_its_title(self):
        with patch.object(window, "window_text", return_value=" 계좌 선택 "):
            self.assertEqual(window.describe_dialog(9), "계좌 선택")

    def test_enabled_main_window_means_nothing_is_blocking(self):
        with patch.object(window.user32, "IsWindowEnabled", return_value=True):
            self.assertEqual(window.blocking_dialogs(1), [])
            window.ensure_not_blocked(1)

    def test_blocked_main_window_stops_even_without_a_name(self):
        with patch.object(window.user32, "IsWindowEnabled", return_value=False), patch.object(
            window, "process_id", return_value=77
        ), patch.object(window, "notice_dialogs", return_value=[]):
            with self.assertRaises(window.BlockedByDialog):
                window.ensure_not_blocked(1)


class DismissBlockingDialogTests(unittest.TestCase):
    """사람 없이 도는 수집이 KB 필수 고지 팝업에 걸려 죽지 않게 한다."""

    def test_it_closes_the_modal_and_reports_what_it_closed(self):
        enabled = iter([False, True, True])
        with patch.object(
            window.user32, "IsWindowEnabled", side_effect=lambda h: next(enabled)
        ), patch.object(window, "process_id", return_value=77), patch.object(
            window, "notice_dialogs", return_value=[9]
        ), patch.object(
            window, "describe_dialog", return_value="제목 없는 대화상자 (303x265 @ 809,388)"
        ), patch.object(window, "descendants", return_value=[]), patch.object(
            window.user32, "PostMessageW"
        ) as post, patch("time.sleep"):
            closed = window.dismiss_blocking_dialogs(1)
        self.assertEqual(closed, ["제목 없는 대화상자 (303x265 @ 809,388)"])
        post.assert_called_once_with(9, window.WM_CLOSE, 0, 0)

    def test_it_only_ever_sends_wm_close(self):
        # 버튼 좌표를 누르면 사용자를 대신해 무언가에 동의하는 셈이 된다.
        enabled = iter([False, True, True])
        with patch.object(
            window.user32, "IsWindowEnabled", side_effect=lambda h: next(enabled)
        ), patch.object(window, "process_id", return_value=77), patch.object(
            window, "notice_dialogs", return_value=[9]
        ), patch.object(window, "describe_dialog", return_value="안내"), patch.object(
            window, "descendants", return_value=[]
        ), patch.object(window.user32, "PostMessageW") as post, patch.object(
            window.user32, "SendMessageW"
        ) as send, patch("time.sleep"):
            window.dismiss_blocking_dialogs(1)
        self.assertEqual({call.args[1] for call in post.call_args_list}, {window.WM_CLOSE})
        send.assert_not_called()

    def test_a_password_prompt_is_never_closed(self):
        # 닫으면 사람이 고쳐야 할 상태가 사라진 채 다른 실패로 나타난다.
        with patch.object(window.user32, "IsWindowEnabled", return_value=False), patch.object(
            window, "process_id", return_value=77
        ), patch.object(window, "notice_dialogs", return_value=[9]), patch.object(
            window, "descendants", return_value=[4]
        ), patch.object(window, "class_name", return_value="Static"), patch.object(
            window, "window_text", return_value="비밀번호를 입력하세요."
        ), patch.object(window.user32, "PostMessageW") as post, patch("time.sleep"):
            with self.assertRaises(window.AccountPasswordRequired):
                window.dismiss_blocking_dialogs(1)
        post.assert_not_called()

    def test_a_logout_notice_is_never_closed(self):
        with patch.object(window.user32, "IsWindowEnabled", return_value=False), patch.object(
            window, "process_id", return_value=77
        ), patch.object(window, "notice_dialogs", return_value=[9]), patch.object(
            window, "descendants", return_value=[4]
        ), patch.object(window, "class_name", return_value="Static"), patch.object(
            window, "window_text", return_value="다시 로그인하세요."
        ), patch.object(window.user32, "PostMessageW") as post, patch("time.sleep"):
            with self.assertRaises(window.LoggedOut):
                window.dismiss_blocking_dialogs(1)
        post.assert_not_called()

    def test_a_dialog_that_refuses_to_close_still_stops_the_run(self):
        with patch.object(window.user32, "IsWindowEnabled", return_value=False), patch.object(
            window, "process_id", return_value=77
        ), patch.object(window, "notice_dialogs", return_value=[9]), patch.object(
            window, "describe_dialog", return_value="안 닫히는 창"
        ), patch.object(window, "descendants", return_value=[]), patch.object(
            window.user32, "PostMessageW"
        ), patch("time.sleep"):
            with self.assertRaisesRegex(window.BlockedByDialog, "안 닫히는 창"):
                window.dismiss_blocking_dialogs(1)

    def test_nothing_blocking_means_nothing_closed(self):
        with patch.object(window.user32, "IsWindowEnabled", return_value=True), patch.object(
            window.user32, "PostMessageW"
        ) as post:
            self.assertEqual(window.dismiss_blocking_dialogs(1), [])
        post.assert_not_called()


class ScreenLookupTests(unittest.TestCase):
    """화면이 없을 때, 그 이유가 모달이면 모달을 먼저 말한다."""

    def test_missing_screen_behind_a_modal_reports_the_modal(self):
        with patch.object(window, "descendants", return_value=[]), patch.object(
            window.user32, "IsWindowEnabled", return_value=False
        ), patch.object(window, "process_id", return_value=77), patch.object(
            window, "notice_dialogs", return_value=[]
        ):
            with self.assertRaises(window.BlockedByDialog):
                window.find_screen(1, "1285")

    def test_missing_screen_without_a_modal_still_says_to_open_it(self):
        with patch.object(window, "descendants", return_value=[]), patch.object(
            window.user32, "IsWindowEnabled", return_value=True
        ):
            with self.assertRaisesRegex(window.ScreenNotOpen, "1285"):
                window.find_screen(1, "1285")

    def test_an_open_screen_is_returned_without_checking_dialogs(self):
        with patch.object(window, "descendants", return_value=[42]), patch.object(
            window, "window_text", return_value="1285 총자산현황"
        ), patch.object(window, "class_name", return_value="Afx:00C30000:b"), patch.object(
            window, "ensure_not_blocked"
        ) as blocked:
            self.assertEqual(window.find_screen(1, "1285"), 42)
        blocked.assert_not_called()

    def test_the_number_box_we_typed_into_is_not_mistaken_for_a_screen(self):
        # 번호를 넣고 나면 입력창의 제목도 "1285"가 된다. 클래스로 갈라야 한다.
        with patch.object(window, "descendants", return_value=[5]), patch.object(
            window, "window_text", return_value="1285"
        ), patch.object(window, "class_name", return_value="Edit"), patch.object(
            window.user32, "IsWindowEnabled", return_value=True
        ):
            with self.assertRaises(window.ScreenNotOpen):
                window.find_screen(1, "1285")


class OpenScreenTests(unittest.TestCase):
    """닫힌 화면은 사람을 부르지 않고 우리가 연다."""

    def test_an_open_screen_is_not_reopened(self):
        with patch.object(window, "descendants", return_value=[42]), patch.object(
            window, "window_text", return_value="1285 총자산현황"
        ), patch.object(window, "class_name", return_value="Afx:00C30000:b"), patch.object(
            window, "open_screen"
        ) as opener:
            self.assertEqual(window.ensure_screen_open(1, "1285"), 42)
        opener.assert_not_called()

    def test_a_closed_screen_is_typed_into_the_number_box(self):
        with patch.object(window, "descendants", return_value=[]), patch.object(
            window.user32, "IsWindowEnabled", return_value=True
        ), patch.object(window, "open_screen", return_value=42) as opener:
            self.assertEqual(window.ensure_screen_open(1, "1285"), 42)
        opener.assert_called_once_with(1, "1285")

    def test_a_modal_is_reported_before_trying_to_open_anything(self):
        # 막혀 있으면 번호를 넣어도 화면이 열리지 않는다.
        with patch.object(window, "descendants", return_value=[]), patch.object(
            window.user32, "IsWindowEnabled", return_value=False
        ), patch.object(window, "process_id", return_value=77), patch.object(
            window, "notice_dialogs", return_value=[]
        ), patch.object(window, "open_screen") as opener:
            with self.assertRaises(window.BlockedByDialog):
                window.ensure_screen_open(1, "1285")
        opener.assert_not_called()

    def test_opening_types_the_number_and_presses_enter(self):
        with patch.object(window, "screen_number_box", return_value=5), patch.object(
            window, "descendants", return_value=[7]
        ), patch.object(
            window,
            "window_text",
            side_effect=lambda h: "1285" if h == 5 else "1285 총자산현황",
        ), patch.object(
            window, "class_name", return_value="Afx:00C30000:b"
        ), patch.object(window, "rect", return_value=(22, 45, 78, 25)), patch.object(
            window, "ensure_point_hits_hable"
        ), patch.object(window.user32, "SetWindowTextW") as cleared, patch(
            "stock_importer.hable.extract.pin_to_top"
        ), patch("stock_importer.hable.extract.unpin") as unpin, patch(
            "stock_importer.hable.extract.BorrowedCursor.click"
        ) as click, patch("stock_importer.hable.extract.BorrowedCursor.__exit__",
            return_value=False
        ), patch("stock_importer.hable.extract.type_digits") as digits, patch(
            "stock_importer.hable.extract.press_key"
        ) as key, patch("time.sleep"):
            self.assertEqual(window.open_screen(1, "1285"), 7)
        cleared.assert_called_once_with(5, "")
        click.assert_called_once_with(61, 57)
        digits.assert_called_once_with("1285")
        key.assert_called_once_with(window.VK_RETURN, settle=1.0)
        unpin.assert_called_once_with(1)

    def test_a_number_that_did_not_land_cleanly_is_not_submitted(self):
        # 남은 글자에 이어 붙으면 엉뚱한 화면이 열린다 - 실측으로 `1285114`가 됐다.
        with patch.object(window, "screen_number_box", return_value=5), patch.object(
            window, "rect", return_value=(22, 45, 78, 25)
        ), patch.object(window, "ensure_point_hits_hable"), patch.object(
            window.user32, "SetWindowTextW"
        ), patch.object(window, "window_text", return_value="1285114"), patch(
            "stock_importer.hable.extract.pin_to_top"
        ), patch("stock_importer.hable.extract.unpin"), patch(
            "stock_importer.hable.extract.BorrowedCursor.click"
        ), patch("stock_importer.hable.extract.BorrowedCursor.__exit__", return_value=False
        ), patch("stock_importer.hable.extract.type_digits"), patch(
            "stock_importer.hable.extract.press_key"
        ) as key, patch("time.sleep"):
            with self.assertRaisesRegex(window.ScreenNotOpen, "1285114"):
                window.open_screen(1, "1285")
        key.assert_not_called()

    def test_a_missing_number_box_says_so_instead_of_typing_elsewhere(self):
        with patch.object(window, "screen_number_box", return_value=None), patch(
            "stock_importer.hable.extract.type_digits"
        ) as digits:
            with self.assertRaisesRegex(window.ScreenNotOpen, "화면번호 입력창"):
                window.open_screen(1, "1285")
        digits.assert_not_called()

    def test_it_refuses_to_click_when_another_window_covers_the_box(self):
        # 그 자리를 누르면 남의 창이 받는다 - 화면번호가 편집기에 찍힌다.
        with patch.object(window, "window_at", return_value=999), patch.object(
            window, "process_id", side_effect=lambda h: 1 if h == 999 else 77
        ), patch("time.sleep"), patch("time.monotonic", side_effect=[0.0, 9.0]):
            with self.assertRaisesRegex(window.HableError, "덮고 있어"):
                window.ensure_point_hits_hable(1, (61, 57))

    def test_it_proceeds_once_the_box_is_actually_on_top(self):
        with patch.object(window, "window_at", return_value=999), patch.object(
            window, "process_id", return_value=77
        ):
            window.ensure_point_hits_hable(1, (61, 57))


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
