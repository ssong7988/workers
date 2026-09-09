import unittest

from spending_analyzer.diagnose import PdfProbe, describe_message, verdict
from tests.test_mailbox import build_statement_mail
from spending_analyzer.mailbox import parse_message


class PdfProbeTest(unittest.TestCase):
    def test_a_text_layer_needs_more_than_a_few_stray_characters(self):
        self.assertTrue(PdfProbe("a.pdf", 1000, opened=True, first_page_chars=4000).has_text_layer)
        self.assertFalse(PdfProbe("a.pdf", 1000, opened=True, first_page_chars=3).has_text_layer)

    def test_an_unopened_pdf_never_counts_as_readable(self):
        probe = PdfProbe("a.pdf", 1000, encrypted=True, first_page_chars=9999)
        self.assertFalse(probe.has_text_layer)

    def test_summary_of_a_failure_carries_the_reason(self):
        probe = PdfProbe("a.pdf", 2048, note="PDFPasswordIncorrect")
        self.assertIn("열지 못함", probe.summary())
        self.assertIn("PDFPasswordIncorrect", probe.summary())

    def test_summary_flags_a_scanned_pdf(self):
        probe = PdfProbe("a.pdf", 2048, opened=True, pages=3, first_page_chars=2)
        self.assertIn("OCR", probe.summary())

    def test_summary_of_a_healthy_pdf_says_so(self):
        probe = PdfProbe("a.pdf", 2048, opened=True, pages=3, first_page_chars=4000)
        summary = probe.summary()
        self.assertIn("암호 없음", summary)
        self.assertIn("3페이지", summary)
        self.assertNotIn("OCR", summary)


class VerdictTest(unittest.TestCase):
    def test_no_mail_points_at_the_settings_to_check(self):
        text = verdict([])
        self.assertIn("메일이 없습니다", text)
        self.assertIn("mail.senders", text)

    def test_link_only_mail_says_the_approach_does_not_hold(self):
        message = parse_message("1", build_statement_mail(with_pdf=False))
        text = verdict([message])
        self.assertIn("PDF 첨부가 있는 메일이 없습니다", text)
        self.assertIn("엑셀", text)


class DescribeMessageTest(unittest.TestCase):
    def test_block_shows_the_headers_and_part_tree(self):
        message = parse_message("42", build_statement_mail(with_pdf=False))
        block = describe_message(message, 1)
        self.assertIn("uid=42", block)
        self.assertIn("이용대금명세서", block)
        self.assertIn("text/html", block)

    def test_missing_attachment_is_called_out(self):
        message = parse_message("42", build_statement_mail(with_pdf=False))
        self.assertIn("첨부: 없음", describe_message(message, 1))

    def test_a_subject_mismatch_is_marked(self):
        message = parse_message("42", build_statement_mail(with_pdf=False))
        block = describe_message(message, 1, subject_matched=False)
        self.assertIn("제목 키워드 불일치", block)


if __name__ == "__main__":
    unittest.main()
