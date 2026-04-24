import unittest

from liveMan import DouyinLiveWebFetcher
from protobuf.douyin import FansclubMessage, User


class FansclubGiftEventTests(unittest.TestCase):
    def test_join_fansclub_message_emits_browser_visible_gift_event(self):
        events = []
        fetcher = DouyinLiveWebFetcher("962565925628", event_handler=events.append, verbose=False)
        payload = FansclubMessage(
            type=2,
            content="恭喜 知心小胡 成为第457923名腰拐成员",
            user=User(id=123, nick_name="知心小胡"),
        ).SerializeToString()

        fetcher._parseFansclubMsg(payload)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "gift")
        self.assertEqual(events[0]["method"], "WebcastFansclubMessage")
        self.assertEqual(events[0]["user_name"], "知心小胡")
        self.assertEqual(events[0]["gift_name"], "点亮粉丝团")
        self.assertEqual(events[0]["gift_count"], 1)

    def test_fansclub_user_name_can_fallback_to_content(self):
        events = []
        fetcher = DouyinLiveWebFetcher("962565925628", event_handler=events.append, verbose=False)
        payload = FansclubMessage(
            type=2,
            content="恭喜 ᘗ阿man 成为第457923名腰拐成员",
        ).SerializeToString()

        fetcher._parseFansclubMsg(payload)

        self.assertEqual(events[0]["user_name"], "ᘗ阿man")
        self.assertEqual(events[0]["gift_name"], "点亮粉丝团")


if __name__ == "__main__":
    unittest.main()
