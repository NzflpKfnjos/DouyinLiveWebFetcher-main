import base64
import json
import unittest
from pathlib import Path

from liveMan import DouyinLiveWebFetcher


class GiftBannerParsingTests(unittest.TestCase):
    def setUp(self):
        self.fetcher = DouyinLiveWebFetcher("962565925628", verbose=False)

    def test_ignores_anchor_task_banner_as_gift_event(self):
        samples = json.loads(Path("banner_samples.json").read_text(encoding="utf-8"))["samples"]
        banner_payload = next(
            base64.b64decode(item["payload_b64"])
            for item in samples
            if item["method"] == "WebcastInRoomBannerMessage"
        )

        events = []
        self.fetcher.event_handler = events.append
        self.fetcher._parseInRoomBannerMsg(banner_payload)

        self.assertFalse([event for event in events if event["type"] == "gift"])
        self.assertTrue([event for event in events if event["type"] == "unknown_message"])

    def test_extracts_text_banner_with_sender_and_gift_name(self):
        data = {
            "basic_props": {
                "desc": "小明 送出了 小心心 x3",
                "icon_src": ["https://example.test/gift.png"],
            }
        }

        events = self.fetcher._extract_banner_gift_events(data)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["user_name"], "小明")
        self.assertEqual(events[0]["gift_name"], "小心心")
        self.assertEqual(events[0]["gift_count"], 3)

    def test_extracts_explicit_json_gift_without_using_title_as_sender(self):
        data = {
            "title": "礼物榜单",
            "payload": {
                "user_name": "送礼观众",
                "gift_name": "玫瑰",
                "gift_count": 2,
            },
        }

        events = self.fetcher._extract_banner_gift_events(data)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["user_name"], "送礼观众")
        self.assertEqual(events[0]["gift_name"], "玫瑰")
        self.assertEqual(events[0]["gift_count"], 2)

    def test_extracts_nested_banner_gift_core_fields(self):
        data = {
            "cards": [
                {
                    "title": "礼物榜单",
                    "payload": {
                        "detail": {
                            "basic_props": {
                                "desc": "小李 送出了 热气球 x2",
                                "icon_src": ["https://example.test/balloon.png"],
                            },
                            "gift_name": "热气球",
                            "gift_count": 2,
                            "user_name": "小李",
                        }
                    },
                }
            ]
        }

        events = self.fetcher._extract_banner_gift_events(data)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["user_name"], "小李")
        self.assertEqual(events[0]["gift_name"], "热气球")
        self.assertEqual(events[0]["gift_count"], 2)
        self.assertEqual(events[0]["gift_image"], ["https://example.test/balloon.png"])

    def test_skips_explicit_gift_json_when_sender_is_missing(self):
        data = {"basic_props": {"title": "礼物榜单"}, "gift_name": "玫瑰"}

        self.assertEqual(self.fetcher._extract_banner_gift_events(data), [])


if __name__ == "__main__":
    unittest.main()
