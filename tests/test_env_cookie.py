import os
import tempfile
import unittest
from pathlib import Path

from liveMan import DouyinLiveWebFetcher
from main import load_dotenv


class EnvCookieTests(unittest.TestCase):
    def setUp(self):
        self.original_cookie = os.environ.pop("DOUYIN_COOKIE", None)

    def tearDown(self):
        if self.original_cookie is None:
            os.environ.pop("DOUYIN_COOKIE", None)
        else:
            os.environ["DOUYIN_COOKIE"] = self.original_cookie

    def test_load_dotenv_converts_multiline_json_cookie_to_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                '''DOUYIN_COOKIE={
  "passport_csrf_token": "token-value",
  "enter_pc_once": "1",
  "IsDouyinActive": "true"
}
''',
                encoding="utf-8",
            )

            load_dotenv(env_file)

        cookie = os.environ["DOUYIN_COOKIE"]
        self.assertIn("passport_csrf_token=token-value", cookie)
        self.assertIn("enter_pc_once=1", cookie)
        self.assertIn("IsDouyinActive=true", cookie)
        self.assertNotEqual(cookie, "{")

    def test_fetcher_accepts_json_cookie_string_directly(self):
        fetcher = DouyinLiveWebFetcher(
            "962565925628",
            cookie='{"passport_csrf_token":"token-value","enter_pc_once":"1"}',
            verbose=False,
        )

        self.assertEqual(fetcher._get_cookie_value("passport_csrf_token"), "token-value")
        self.assertEqual(fetcher._get_cookie_value("enter_pc_once"), "1")

    def test_existing_environment_cookie_is_not_overwritten(self):
        os.environ["DOUYIN_COOKIE"] = "existing=value"
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text('DOUYIN_COOKIE={"new":"value"}\n', encoding="utf-8")

            load_dotenv(env_file)

        self.assertEqual(os.environ["DOUYIN_COOKIE"], "existing=value")


if __name__ == "__main__":
    unittest.main()
