import unittest

from email.message import EmailMessage

from spending_analyzer.diagnose import (
    PdfProbe,
    describe_message,
    probe_secure_mail,
    statement_attachments,
    verdict,
)
from tests.test_mailbox import build_statement_mail
from spending_analyzer.mailbox import parse_message


def build_secure_mail(
    *, plain: bool = False, networked: bool = False, mention_only: bool = False
) -> bytes:
    """A stand-in for the VestMail attachment 삼성카드 actually sends.

    Carries only the structural markers the probe looks for — no real statement.
    """
    if plain:
        body = "<html><body><p>안내드립니다</p>"
        if mention_only:
            body += "<p>VestMail 보안메일 안내</p>"
        body += "</body></html>"
    else:
        body = (
            "<html><body>"
            '<form name="decForm" id="decForm" onSubmit="doAction(); return false;">'
            '<input type="password" id="password"><input id="confirm" type="submit">'
            "</form>"
            "<script>var b_p = 'dmFyIEE9';</script>"
            "<script>/* YettieSoft VestMail */"
            + ("var x = new XMLHttpRequest();" if networked else "")
            + "</script></body></html>"
        )

    message = EmailMessage()
    message["From"] = "삼성카드 <billing@samsungcard.com>"
    message["Subject"] = "[삼성카드] 이용대금 명세서 입니다."
    message["Date"] = "Wed, 09 Sep 2026 23:52:33 +0900"
    message.set_content("첨부파일 열기 → 생년월일 6자리 입력")
    message.add_attachment(
        body.encode("utf-8"),
        maintype="text",
        subtype="html",
        filename="samsungcard_detail_20260913.html",
    )
    return message.as_bytes()


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

    def test_attachment_free_mail_says_the_approach_does_not_hold(self):
        message = parse_message("1", build_statement_mail(with_pdf=False))
        text = verdict([message])
        self.assertIn("명세서로 볼 만한 첨부가 없습니다", text)
        self.assertIn("엑셀", text)

    def test_secure_mail_attachment_is_recognized_as_workable(self):
        message = parse_message("1", build_secure_mail())
        text = verdict([message])
        self.assertIn("VestMail 보안메일", text)
        self.assertIn("SAMSUNG_STATEMENT_PASSWORD", text)

    def test_a_secure_mail_needing_the_network_is_called_out(self):
        message = parse_message("1", build_secure_mail(networked=True))
        text = verdict([message])
        self.assertIn("서버 통신이 필요", text)


class SecureMailProbeTest(unittest.TestCase):
    def attachment(self, **kwargs):
        message = parse_message("1", build_secure_mail(**kwargs))
        return message.attachments[0]

    def test_detects_a_self_decrypting_attachment(self):
        probe = probe_secure_mail(self.attachment())
        self.assertTrue(probe.is_secure_mail)
        self.assertFalse(probe.needs_network)
        self.assertIn("오프라인 파싱 가능", probe.summary())

    def test_a_plain_html_attachment_is_not_secure_mail(self):
        message = parse_message("1", build_secure_mail(plain=True))
        probe = probe_secure_mail(message.attachments[0])
        self.assertFalse(probe.is_secure_mail)
        self.assertIn("일반 HTML", probe.summary())

    def test_one_stray_mention_is_not_enough_to_call_it_secure_mail(self):
        # A notice mail can name the product without being the document.
        message = parse_message("1", build_secure_mail(plain=True, mention_only=True))
        self.assertFalse(probe_secure_mail(message.attachments[0]).is_secure_mail)

    def test_statement_attachments_picks_only_the_document(self):
        message = parse_message("1", build_secure_mail())
        self.assertEqual(len(statement_attachments(message)), 1)


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
