# Real-room gift verification evidence

Room under test: `https://live.douyin.com/358083504413` (`live_id=358083504413`).
Cookie source: local `.env` `DOUYIN_COOKIE` loaded by the verification harness; cookie values are intentionally not recorded.

## Interface evidence captured on 2026-04-24

The verified upstream pull path is the protobuf web fetch endpoint used by `DouyinLiveWebFetcher._fetch_message_response`:

- URL: `https://live.douyin.com/webcast/im/fetch/`
- Required room resolution: live page resolved `room_id=7632263541055081252`
- Request identity: `app_name=douyin_web`, `aid=6383`, `live_id=1`, `endpoint=live_pc`, `identity=audience`, `room_id=<resolved room_id>`
- Payload: response parses as protobuf `Response`; each item dispatches by `Message.method`

A real-room polling run processed 66 response packets without request or parse errors. The dominant methods observed were:

| Method | Count |
| --- | ---: |
| `WebcastChatMessage` | 333 |
| `WebcastInRoomBannerMessage` | 300 |
| `WebcastMemberMessage` | 150 |
| `WebcastRanklistHourEntranceMessage` | 75 |
| `WebcastRoomDataSyncMessage` | 65 |
| `WebcastRoomStatsMessage` | 64 |
| `WebcastFansclubMessage` | 50 |
| `WebcastRoomUserSeqMessage` | 39 |
| `WebcastLikeMessage` | 25 |
| `WebcastSocialMessage` | 22 |

The same run emitted browser-selectable events through the production dispatch path:

| Event type | Count |
| --- | ---: |
| `chat` | 333 |
| `gift` | 50 |
| `like` | 25 |
| `packet` debug events | 66 |

All gift events observed during that window were `WebcastFansclubMessage`; no live non-fansclub `WebcastGift*Message` appeared in that sample window. Regression coverage therefore locks the non-fansclub path with protobuf `GiftMessage` payloads and the real method fallback (`WebcastGiftSyncMessage`) so that any real `WebcastGift*...Message` method delivered by `/webcast/im/fetch/` is parsed, stored by `LiveMessageWebApp`, serialized to SSE/API clients, and rendered by the unchanged gift UI.

## Additional logged-in room evidence (`https://live.douyin.com/LYG9199`)

Using the user-provided logged-in cookie for `https://live.douyin.com/LYG9199`,
the resolved room id was `7632170663536642868`.

A 10-minute observation window produced **real non-fansclub gift traffic** on
both the websocket and protobuf fetch paths:

| Transport | Gift total | Non-fansclub total | Methods |
| --- | ---: | ---: | --- |
| websocket | 18 | 2 | `WebcastFansclubMessage` ×16, `WebcastGiftIconFlashMessage` ×2 |
| fetch | 18 | 2 | `WebcastFansclubMessage` ×16, `WebcastGiftIconFlashMessage` ×2 |

This confirms that `WebcastGiftIconFlashMessage` is a real non-fansclub gift
method that the browser-visible gift path must preserve. The runtime now routes
that method directly to `_parseGiftMsg` instead of relying only on the generic
gift-name heuristic.

## Regression evidence added

`tests/test_web_gift_visibility.py` verifies that:

1. A non-fansclub protobuf `GiftMessage` parsed by `DouyinLiveWebFetcher._parseGiftMsg` reaches `LiveMessageWebApp` history with `type=gift`, `method=WebcastGiftMessage`, `gift_name`, `gift_count`, and browser display `content`.
2. Gift events remain JSON/SSE serializable and are delivered to web subscribers without changing the web UI contract.
3. A real-room non-fansclub method shape (`WebcastGiftIconFlashMessage`) also
   reaches the web history as a normal `gift` event with its original method
   preserved.
