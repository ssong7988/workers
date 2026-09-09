import unittest
from email.message import EmailMessage

from spending_analyzer.mailbox import (
    decode_mime_header,
    html_to_text,
    parse_mail_date,
    parse_message,
    _imap_date,
)


def build_statement_mail(*, with_pdf: bool = True) -> bytes:
    message = EmailMessage()
    message["From"] = "삼성카드 <bill@samsungcard.com>"
    message["Subject"] = "[삼성카드] 9월 이용대금명세서"
    message["Date"] = "Tue, 09 Sep 2026 09:00:00 +0900"
    message["Message-ID"] = "<statement-202609@samsungcard.com>"
    message.set_content("텍스트 본문입니다.")
    message.add_alternative(
        "<html><body><style>p{color:red}</style>"
        "<p>청구금액</p><table><tr><td>1,234,567원</td></tr></table>"
        "</body></html>",
        subtype="html",
    )
    if with_pdf:
        message.add_attachment(
            b"%PDF-1.4 fake",
            maintype="application",
            subtype="pdf",
            filename="202609_명세서.pdf",
        )
    return message.as_bytes()


class HeaderDecodingTest(unittest.TestCase):
    def test_decodes_an_encoded_korean_subject(self):
        encoded = "=?UTF-8?B?7IK87ISx7Lm065Oc?="  # 삼성카드
        self.assertEqual(decode_mime_header(encoded), "삼성카드")

    def test_plain_ascii_passes_through(self):
        self.assertEqual(decode_mime_header("Statement"), "Statement")

    def test_missing_header_becomes_empty(self):
        self.assertEqual(decode_mime_header(None), "")


class HtmlToTextTest(unittest.TestCase):
    def test_drops_style_blocks_rather_than_printing_css(self):
        text = html_to_text("<style>p{color:red}</style><p>청구금액</p>")
        self.assertNotIn("color", text)
        self.assertIn("청구금액", text)

    def test_table_cells_stay_separated(self):
        text = html_to_text("<tr><td>가맹점</td><td>12,000</td></tr>")
        self.assertIn("가맹점\t12,000", text)

    def test_unescapes_entities(self):
        self.assertEqual(html_to_text("<p>A&nbsp;&amp;&nbsp;B</p>").replace("\xa0", " "), "A & B")

    def test_empty_input_is_empty(self):
        self.assertEqual(html_to_text(""), "")


class ImapDateTest(unittest.TestCase):
    def test_formats_the_way_imap_search_expects(self):
        self.assertEqual(_imap_date("2025-01-05"), "05-Jan-2025")
        self.assertEqual(_imap_date("2026-12-31"), "31-Dec-2026")

    def test_rejects_a_non_iso_date(self):
        with self.assertRaises(ValueError):
            _imap_date("2025/01/05")


class ParseMessageTest(unittest.TestCase):
    def test_reads_headers_body_and_attachment(self):
        message = parse_message("42", build_statement_mail())
        self.assertEqual(message.uid, "42")
        self.assertIn("samsungcard.com", message.sender)
        self.assertEqual(message.subject, "[삼성카드] 9월 이용대금명세서")
        self.assertEqual(message.message_id, "<statement-202609@samsungcard.com>")
        self.assertIn("청구금액", message.html_body)
        self.assertEqual(len(message.pdf_attachments), 1)
        self.assertEqual(message.pdf_attachments[0].filename, "202609_명세서.pdf")

    def test_part_tree_lists_every_leaf(self):
        message = parse_message("42", build_statement_mail())
        joined = "\n".join(message.part_tree)
        self.assertIn("text/plain", joined)
        self.assertIn("text/html", joined)
        self.assertIn("application/pdf", joined)

    def test_link_only_mail_reports_no_attachments(self):
        message = parse_message("7", build_statement_mail(with_pdf=False))
        self.assertEqual(message.pdf_attachments, [])
        self.assertIn("청구금액", html_to_text(message.html_body))

    def test_body_text_prefers_the_plain_part(self):
        message = parse_message("42", build_statement_mail())
        self.assertIn("텍스트 본문", message.body_text())


if __name__ == "__main__":
    unittest.main()


class ParseMailDateTest(unittest.TestCase):
    def test_reads_an_rfc2822_date_with_its_offset(self):
        parsed = parse_mail_date("Tue, 09 Sep 2026 09:00:00 +0900")
        self.assertIsNotNone(parsed)
        self.assertEqual((parsed.year, parsed.month, parsed.day), (2026, 9, 9))
        self.assertEqual(parsed.utcoffset().total_seconds(), 9 * 3600)

    def test_an_unparseable_date_is_none_rather_than_an_error(self):
        self.assertIsNone(parse_mail_date("어제쯤"))
        self.assertIsNone(parse_mail_date(""))
