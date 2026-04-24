#!/usr/bin/env python3
"""Replay/profile harness for high-message Douyin parser CPU work.

The harness builds a deterministic synthetic ``Response`` once, then replays it
through the same ``DouyinLiveWebFetcher._dispatch_response`` path used by both
console and web modes.  ``--mode web`` adds the current web publish/fan-out and
SSE JSON serialization work without starting a network server, so runs are
repeatable and do not depend on a live room.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from liveMan import DouyinLiveWebFetcher  # noqa: E402
from protobuf.douyin import (  # noqa: E402
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
from web_server import DEBUG_EVENT_TYPES, SELECTABLE_EVENT_TYPES, LiveMessageWebApp  # noqa: E402


@dataclass
class EventCounter:
    """Low-overhead event sink used for shared/console-path profiling."""

    count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)

    def __call__(self, event: dict[str, Any]) -> None:
        self.count += 1
        event_type = str(event.get("type") or "")
        self.by_type[event_type] = self.by_type.get(event_type, 0) + 1


@dataclass
class WebReplaySink:
    """Exercise web publish fan-out plus SSE serialization without a socket."""

    live_id: str = "benchmark-live"
    count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    sse_chunks: int = 0
    sse_bytes: int = 0

    def __post_init__(self) -> None:
        self.app = LiveMessageWebApp(self.live_id, history_size=200)
        # One subscriber makes publish_event perform the same queue fan-out used
        # by /events clients while keeping the benchmark in-process.
        self.subscriber = self.app.add_subscriber()

    def __call__(self, event: dict[str, Any]) -> None:
        self.count += 1
        event_type = str(event.get("type") or "")
        self.by_type[event_type] = self.by_type.get(event_type, 0) + 1
        self.app.publish_event(event)
        if event_type in SELECTABLE_EVENT_TYPES or event_type in DEBUG_EVENT_TYPES:
            data = json.dumps(event, ensure_ascii=False)
            chunk = f"event: {event_type}\ndata: {data}\n\n".encode("utf-8")
            self.sse_chunks += 1
            self.sse_bytes += len(chunk)


def _gift_text(user_name: str = "", gift_name: str = "小心心", count: int = 1) -> Text:
    pieces: list[TextPiece] = []
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


def build_high_message_response(message_count: int) -> Response:
    """Build a deterministic mixed message batch with unique gift signatures."""

    messages: list[Message] = []
    for index in range(message_count):
        variant = index % 4
        user = User(id=100000 + index, nick_name=f"用户{index}")
        if variant == 0:
            payload = ChatMessage(user=user, content=f"高消息量聊天 {index}").SerializeToString()
            method = "WebcastChatMessage"
        elif variant == 1:
            payload = GiftMessage(
                gift_id=9000 + index,
                combo_count=(index % 5) + 1,
                trace_id=f"trace-{index}",
                user=user,
                gift=GiftStruct(
                    id=9000 + index,
                    name=f"小心心{index}",
                    diamond_count=1,
                    image=Image(url_list_list=[f"https://example.test/gift-{index}.png"]),
                ),
            ).SerializeToString()
            method = "WebcastGiftMessage"
        elif variant == 2:
            payload = GiftMessage(
                combo_count=(index % 3) + 1,
                trace_id=f"fallback-{index}",
                tray_display_text=_gift_text(user_name=f"托盘用户{index}", gift_name=f"玫瑰{index}", count=(index % 3) + 1),
            ).SerializeToString()
            method = "WebcastGiftSyncMessage"
        else:
            payload = ChatMessage(
                user=user,
                gift_image=Image(url_list_list=[f"https://example.test/chat-gift-{index}.png"]),
                rtf_content=_gift_text(gift_name=f"小星星{index}", count=(index % 7) + 1),
            ).SerializeToString()
            method = "WebcastChatMessage"
        messages.append(Message(method=method, payload=payload))
    return Response(messages_list=messages, heartbeat_duration=10000)


def _new_fetcher(mode: str) -> tuple[DouyinLiveWebFetcher, EventCounter | WebReplaySink]:
    sink: EventCounter | WebReplaySink
    sink = WebReplaySink() if mode == "web" else EventCounter()
    fetcher = DouyinLiveWebFetcher("benchmark-live", event_handler=sink, verbose=False)
    # Avoid live room network discovery during packet/parser event construction.
    fetcher._DouyinLiveWebFetcher__room_id = "benchmark-room"  # type: ignore[attr-defined]
    return fetcher, sink


def _profile_once(func: Callable[[], None], top: int) -> tuple[float, float, list[dict[str, Any]]]:
    profiler = cProfile.Profile()
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    profiler.enable()
    func()
    profiler.disable()
    cpu_elapsed = time.process_time() - cpu_start
    wall_elapsed = time.perf_counter() - wall_start

    stats = pstats.Stats(profiler, stream=io.StringIO()).strip_dirs().sort_stats("cumtime")
    hotspots = []
    for (filename, line, name), stat in list(stats.stats.items())[:top]:
        primitive_calls, total_calls, total_time, cumulative_time, _callers = stat
        hotspots.append(
            {
                "function": f"{filename}:{line}:{name}",
                "primitive_calls": primitive_calls,
                "total_calls": total_calls,
                "tottime_seconds": round(total_time, 6),
                "cumtime_seconds": round(cumulative_time, 6),
            }
        )
    return wall_elapsed, cpu_elapsed, hotspots


def run_benchmark(mode: str, runs: int, messages: int, top: int) -> dict[str, Any]:
    response = build_high_message_response(messages)
    run_results = []
    for run_index in range(1, runs + 1):
        fetcher, sink = _new_fetcher(mode)

        def replay() -> None:
            fetcher._dispatch_response(response)

        wall_elapsed, cpu_elapsed, hotspots = _profile_once(replay, top)
        result: dict[str, Any] = {
            "run": run_index,
            "wall_seconds": round(wall_elapsed, 6),
            "cpu_seconds": round(cpu_elapsed, 6),
            "events": sink.count,
            "event_types": dict(sorted(sink.by_type.items())),
            "top_hotspots": hotspots,
        }
        if isinstance(sink, WebReplaySink):
            result.update({"sse_chunks": sink.sse_chunks, "sse_bytes": sink.sse_bytes})
        run_results.append(result)

    wall_values = [item["wall_seconds"] for item in run_results]
    cpu_values = [item["cpu_seconds"] for item in run_results]
    return {
        "scenario": "high-message",
        "mode": mode,
        "messages": messages,
        "runs": runs,
        "median_wall_seconds": round(statistics.median(wall_values), 6),
        "median_cpu_seconds": round(statistics.median(cpu_values), 6),
        "run_results": run_results,
    }


def compare_results(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_cpu = float(before["median_cpu_seconds"])
    after_cpu = float(after["median_cpu_seconds"])
    before_wall = float(before["median_wall_seconds"])
    after_wall = float(after["median_wall_seconds"])

    def pct_delta(old: float, new: float) -> float | None:
        if old == 0:
            return None
        return round(((new - old) / old) * 100, 2)

    return {
        "mode": after.get("mode", before.get("mode")),
        "messages": after.get("messages", before.get("messages")),
        "before_median_cpu_seconds": before_cpu,
        "after_median_cpu_seconds": after_cpu,
        "cpu_delta_percent": pct_delta(before_cpu, after_cpu),
        "before_median_wall_seconds": before_wall,
        "after_median_wall_seconds": after_wall,
        "wall_delta_percent": pct_delta(before_wall, after_wall),
    }


def _print_summary(results: list[dict[str, Any]], comparisons: list[dict[str, Any]]) -> None:
    for result in results:
        print(
            f"{result['scenario']} mode={result['mode']} messages={result['messages']} runs={result['runs']} "
            f"median_cpu={result['median_cpu_seconds']:.6f}s median_wall={result['median_wall_seconds']:.6f}s"
        )
        first_run = result["run_results"][0]
        print(f"  events={first_run['events']} event_types={first_run['event_types']}")
        if "sse_chunks" in first_run:
            print(f"  sse_chunks={first_run['sse_chunks']} sse_bytes={first_run['sse_bytes']}")
        print("  top cumulative hotspots (run 1):")
        for hotspot in first_run["top_hotspots"]:
            print(
                f"    {hotspot['cumtime_seconds']:.6f}s cum / {hotspot['tottime_seconds']:.6f}s self "
                f"{hotspot['function']} calls={hotspot['total_calls']}"
            )
    for comparison in comparisons:
        print(
            "comparison "
            f"mode={comparison['mode']} cpu {comparison['before_median_cpu_seconds']:.6f}s -> "
            f"{comparison['after_median_cpu_seconds']:.6f}s ({comparison['cpu_delta_percent']}%), "
            f"wall {comparison['before_median_wall_seconds']:.6f}s -> "
            f"{comparison['after_median_wall_seconds']:.6f}s ({comparison['wall_delta_percent']}%)"
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile deterministic high-message replay for console/shared and web paths.")
    parser.add_argument("--scenario", default="high-message", choices=["high-message"])
    parser.add_argument("--mode", default="console", choices=["console", "web", "all"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--messages", type=int, default=5000)
    parser.add_argument("--top", type=int, default=3, help="number of cumulative-time hotspots to report per run")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a text summary")
    parser.add_argument("--save", type=Path, help="write machine-readable results to this path")
    parser.add_argument("--compare-before", type=Path, help="JSON output from a previous run for before/after comparison")
    parser.add_argument("--compare-after", type=Path, help="JSON output from a later run; when omitted, compares --compare-before to current results")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.runs < 1 or args.messages < 1 or args.top < 1:
        raise SystemExit("--runs, --messages, and --top must all be >= 1")

    modes = ["console", "web"] if args.mode == "all" else [args.mode]
    results = [run_benchmark(mode, args.runs, args.messages, args.top) for mode in modes]

    comparisons: list[dict[str, Any]] = []
    if args.compare_before:
        before_payload = json.loads(args.compare_before.read_text(encoding="utf-8"))
        before_results = before_payload.get("results", [before_payload])
        after_results = results
        if args.compare_after:
            after_payload = json.loads(args.compare_after.read_text(encoding="utf-8"))
            after_results = after_payload.get("results", [after_payload])
        before_by_mode = {item["mode"]: item for item in before_results}
        for after in after_results:
            before = before_by_mode.get(after["mode"])
            if before:
                comparisons.append(compare_results(before, after))

    payload = {"results": results, "comparisons": comparisons}
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_summary(results, comparisons)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
