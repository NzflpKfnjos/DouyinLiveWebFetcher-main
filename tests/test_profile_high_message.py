import unittest

from benchmarks.profile_high_message import build_high_message_response, run_benchmark


class HighMessageProfileHarnessTests(unittest.TestCase):
    def test_build_high_message_response_is_deterministic_size(self):
        response = build_high_message_response(12)

        self.assertEqual(len(response.messages_list), 12)
        self.assertEqual(response.messages_list[0].method, "WebcastChatMessage")
        self.assertEqual(response.messages_list[1].method, "WebcastGiftMessage")
        self.assertEqual(response.messages_list[2].method, "WebcastGiftSyncMessage")

    def test_console_benchmark_reports_events_and_hotspots(self):
        result = run_benchmark("console", runs=1, messages=16, top=3)

        self.assertEqual(result["mode"], "console")
        self.assertEqual(result["messages"], 16)
        self.assertEqual(result["runs"], 1)
        self.assertGreater(result["median_cpu_seconds"], 0)
        self.assertEqual(len(result["run_results"]), 1)
        self.assertGreaterEqual(result["run_results"][0]["events"], 16)
        self.assertEqual(len(result["run_results"][0]["top_hotspots"]), 3)

    def test_web_benchmark_exercises_publish_and_sse_serialization(self):
        result = run_benchmark("web", runs=1, messages=16, top=3)
        first_run = result["run_results"][0]

        self.assertEqual(result["mode"], "web")
        self.assertGreaterEqual(first_run["events"], 16)
        self.assertGreater(first_run["sse_chunks"], 0)
        self.assertGreater(first_run["sse_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
