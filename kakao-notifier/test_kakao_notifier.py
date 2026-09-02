from __future__ import annotations

import unittest
from unittest import mock

import kakao_notifier


class ImageMessageTests(unittest.TestCase):
    def test_report_link_adds_second_button_without_replacing_image_link(self) -> None:
        image_url = "https://k.kakaocdn.net/card.png"
        report_url = "https://example.com/report"

        with mock.patch.object(kakao_notifier, "_send_template") as send:
            kakao_notifier.send_image_to_me(
                image_url,
                "제목",
                "설명",
                report_url,
                1080,
                4992,
            )

        template = send.call_args.args[0]
        image_link = {"web_url": image_url, "mobile_web_url": image_url}
        report_link = {"web_url": report_url, "mobile_web_url": report_url}
        self.assertEqual(template["content"]["link"], image_link)
        self.assertEqual(
            template["buttons"],
            [
                {"title": "원본 이미지 보기", "link": image_link},
                {"title": "전체 매물 보기", "link": report_link},
            ],
        )

    def test_no_report_link_keeps_single_image_button(self) -> None:
        image_url = "https://k.kakaocdn.net/card.png"

        with mock.patch.object(kakao_notifier, "_send_template") as send:
            kakao_notifier.send_image_to_me(image_url, "제목", "설명")

        buttons = send.call_args.args[0]["buttons"]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["title"], "원본 이미지 보기")


if __name__ == "__main__":
    unittest.main()
