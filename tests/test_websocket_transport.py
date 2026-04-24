import ssl
import unittest
from unittest.mock import patch

from liveMan import DouyinLiveWebFetcher


class WebSocketTransportTests(unittest.TestCase):
    def test_start_uses_websocket_transport_by_default(self):
        fetcher = DouyinLiveWebFetcher("358083504413", verbose=False)
        calls = []

        def fake_connect():
            calls.append("websocket")
            fetcher.stop()

        with patch.object(fetcher, "_connectWebSocket", side_effect=fake_connect), \
             patch.object(fetcher, "_connectFetchLoop", side_effect=AssertionError("fetch loop should not be default")):
            fetcher.start()

        self.assertEqual(calls, ["websocket"])

    def test_fetch_transport_remains_available(self):
        fetcher = DouyinLiveWebFetcher("358083504413", verbose=False, transport="fetch")
        calls = []

        def fake_fetch():
            calls.append("fetch")
            fetcher.stop()

        with patch.object(fetcher, "_connectFetchLoop", side_effect=fake_fetch), \
             patch.object(fetcher, "_connectWebSocket", side_effect=AssertionError("websocket should not run in fetch mode")):
            fetcher.start()

        self.assertEqual(calls, ["fetch"])

    def test_websocket_run_disables_local_certificate_verification(self):
        fetcher = DouyinLiveWebFetcher("358083504413", verbose=False)
        fetcher._DouyinLiveWebFetcher__room_id = "7632263541055081252"
        fetcher._DouyinLiveWebFetcher__ttwid = "ttwid-test"
        seen = {}

        class FakeWebSocketApp:
            def __init__(self, *args, **kwargs):
                seen["init"] = (args, kwargs)

            def run_forever(self, **kwargs):
                seen["run_forever"] = kwargs
                fetcher.stop()
                return True

        with patch("liveMan.generateSignature", return_value="signature-test"), \
             patch("liveMan.websocket.WebSocketApp", FakeWebSocketApp):
            fetcher._connectWebSocket()

        self.assertEqual(seen["run_forever"]["sslopt"], {"cert_reqs": ssl.CERT_NONE})


if __name__ == "__main__":
    unittest.main()
