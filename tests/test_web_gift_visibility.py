import json
import unittest

from liveMan import DouyinLiveWebFetcher
from protobuf.douyin import GiftMessage, GiftStruct, Image, User
from web_server import LiveMessageWebApp


class WebGiftVisibilityTests(unittest.TestCase):
    def test_real_gift_message_reaches_web_history_with_display_fields(self):
        app = LiveMessageWebApp("358083504413", history_size=10)
        fetcher = DouyinLiveWebFetcher(
            "358083504413",
            event_handler=app.publish_event,
            verbose=False,
        )
        payload = GiftMessage(
            gift_id=9527,
            combo_count=3,
            user=User(id=123, nick_name="送礼观众"),
            gift=GiftStruct(
                id=9527,
                name="小心心",
                image=Image(url_list_list=["https://example.test/heart.png"]),
            ),
        ).SerializeToString()

        fetcher._parseGiftMsg(payload)

        snapshot = app.get_messages_snapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["type"], "gift")
        self.assertEqual(snapshot[0]["method"], "WebcastGiftMessage")
        self.assertEqual(snapshot[0]["user_name"], "送礼观众")
        self.assertEqual(snapshot[0]["gift_name"], "小心心")
        self.assertEqual(snapshot[0]["gift_count"], 3)
        self.assertEqual(snapshot[0]["content"], "送出了 小心心x3")

    def test_gift_events_are_serializable_for_sse_clients(self):
        app = LiveMessageWebApp("358083504413", history_size=10)
        subscriber = app.add_subscriber()
        try:
            event = {
                "type": "gift",
                "method": "WebcastGiftSyncMessage",
                "user_name": "补位礼物",
                "gift_name": "跑车",
                "gift_count": 2,
                "content": "送出了 跑车x2",
            }

            app.publish_event(event)
            queued = subscriber.get_nowait()
            serialized = json.dumps(queued, ensure_ascii=False)

            self.assertIn('"type": "gift"', serialized)
            self.assertIn('"method": "WebcastGiftSyncMessage"', serialized)
            self.assertIn('"gift_name": "跑车"', serialized)
            self.assertEqual(app.get_messages_snapshot(), [event])
        finally:
            app.remove_subscriber(subscriber)


if __name__ == "__main__":
    unittest.main()
