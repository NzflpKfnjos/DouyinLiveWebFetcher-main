import unittest

from liveMan import DouyinLiveWebFetcher
from protobuf.douyin import (
    ChatMessage,
    GiftMessage,
    GiftStruct,
    Image,
    Message,
    PatternRef,
    Response,
    Text,
    TextPiece,
    TextPieceGift,
    TextPieceUser,
    User,
)


def _gift_text(user_name="", gift_name="小心心", count=1):
    pieces = []
    if user_name:
        pieces.append(TextPiece(user_value=TextPieceUser(user=User(nick_name=user_name))))
        pieces.append(TextPiece(string_value=" 送出了 "))
    else:
        pieces.append(TextPiece(string_value="送出了 "))
    pieces.append(
        TextPiece(
            gift_value=TextPieceGift(
                gift_id=9527,
                name_ref=PatternRef(default_pattern=gift_name),
            )
        )
    )
    pieces.append(TextPiece(string_value=f" x{count}"))
    return Text(pieces_list=pieces)


class GiftMessageEventTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.fetcher = DouyinLiveWebFetcher("962565925628", event_handler=self.events.append, verbose=False)

    def test_parse_gift_message_emits_gift_event_with_core_fields(self):
        payload = GiftMessage(
            gift_id=9527,
            combo_count=3,
            user=User(id=123, nick_name="送礼观众"),
            gift=GiftStruct(
                id=9527,
                name="小心心",
                diamond_count=1,
                image=Image(url_list_list=["https://example.test/heart.png"]),
            ),
        ).SerializeToString()

        self.fetcher._parseGiftMsg(payload)

        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["type"], "gift")
        self.assertEqual(self.events[0]["method"], "WebcastGiftMessage")
        self.assertEqual(self.events[0]["user_name"], "送礼观众")
        self.assertEqual(self.events[0]["gift_name"], "小心心")
        self.assertEqual(self.events[0]["gift_count"], 3)

    def test_parse_gift_message_falls_back_to_tray_text_when_struct_fields_missing(self):
        payload = GiftMessage(
            combo_count=3,
            tray_display_text=_gift_text(user_name="小明", gift_name="玫瑰", count=3),
        ).SerializeToString()

        self.fetcher._parseGiftMsg(payload)

        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["user_name"], "小明")
        self.assertEqual(self.events[0]["gift_name"], "玫瑰")
        self.assertEqual(self.events[0]["gift_count"], 3)

    def test_dispatch_response_routes_gift_like_method_to_parse_gift(self):
        payload = GiftMessage(
            combo_count=2,
            user=User(id=789, nick_name="补位礼物"),
            gift=GiftStruct(id=2048, name="跑车"),
        ).SerializeToString()
        response = Response(
            messages_list=[
                Message(method="WebcastGiftSyncMessage", payload=payload),
            ]
        )

        self.fetcher._dispatch_response(response)

        gifts = [event for event in self.events if event["type"] == "gift"]
        self.assertEqual(len(gifts), 1)
        self.assertEqual(gifts[0]["method"], "WebcastGiftSyncMessage")
        self.assertEqual(gifts[0]["gift_name"], "跑车")
        self.assertEqual(gifts[0]["gift_count"], 2)

    def test_parse_chat_message_with_gift_signal_emits_gift_event(self):
        payload = ChatMessage(
            user=User(id=456, nick_name="横幅观众"),
            gift_image=Image(url_list_list=["https://example.test/chat-gift.png"]),
            rtf_content=_gift_text(gift_name="小星星", count=5),
        ).SerializeToString()

        self.fetcher._parseChatMsg(payload)

        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["type"], "gift")
        self.assertEqual(self.events[0]["method"], "WebcastChatMessage")
        self.assertEqual(self.events[0]["user_name"], "横幅观众")
        self.assertEqual(self.events[0]["gift_name"], "小星星")
        self.assertEqual(self.events[0]["gift_count"], 5)

    def test_regular_chat_message_with_gift_words_but_no_gift_signal_stays_chat(self):
        payload = ChatMessage(
            user=User(id=654, nick_name="普通观众"),
            content="今天是不是很多人送礼物了？",
        ).SerializeToString()

        self.fetcher._parseChatMsg(payload)

        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["type"], "chat")
        self.assertEqual(self.events[0]["user_name"], "普通观众")


if __name__ == "__main__":
    unittest.main()
