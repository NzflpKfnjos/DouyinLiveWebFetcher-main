#!/usr/bin/python
# coding:utf-8

import json
import queue
import threading
from collections import deque
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from liveMan import DouyinLiveWebFetcher


class LiveMessageWebApp:
    def __init__(self, live_id, host="127.0.0.1", port=8000, history_size=200):
        self.live_id = str(live_id)
        self.host = host
        self.port = int(port)
        self.messages = deque(maxlen=history_size)
        self.subscribers = set()
        self.lock = threading.Lock()
        self.fetcher = None
        self.fetcher_thread = None
        self.static_dir = Path(__file__).resolve().parent / "webui"
        self.state = {
            "live_id": self.live_id,
            "room_id": None,
            "connection_status": "idle",
            "room_status_text": "等待连接",
            "message_count": 0,
            "last_message_at": None,
            "packet_count": 0,
            "last_packet_at": None,
            "last_methods": [],
            "last_error": None,
        }

    def publish_event(self, event):
        payload = dict(event)
        event_type = payload.get("type")

        with self.lock:
            if payload.get("room_id"):
                self.state["room_id"] = str(payload["room_id"])
            if event_type in {"chat", "gift"}:
                self.messages.append(payload)
                self.state["message_count"] += 1
                self.state["last_message_at"] = payload.get("iso_time")
            elif event_type == "connection":
                self.state["connection_status"] = payload.get("status", "unknown")
                if payload.get("status") == "open" and self.state["room_status_text"] == "等待连接":
                    self.state["room_status_text"] = "已连接，等待聊天消息"
                if payload.get("message"):
                    self.state["last_error"] = payload.get("message")
            elif event_type == "room_status":
                self.state["room_status_text"] = payload.get("room_status_text", "未知")
            elif event_type == "packet":
                self.state["packet_count"] += 1
                self.state["last_packet_at"] = payload.get("iso_time")
                self.state["last_methods"] = payload.get("methods", [])[:8]
            elif event_type == "parse_error":
                self.state["last_error"] = f"{payload.get('method')}: {payload.get('message')}"

            subscribers = list(self.subscribers)

        stale = []
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except Exception:
                stale.append(subscriber)

        if stale:
            with self.lock:
                for subscriber in stale:
                    self.subscribers.discard(subscriber)

    def get_messages_snapshot(self):
        with self.lock:
            return list(self.messages)

    def get_state_snapshot(self):
        with self.lock:
            return dict(self.state)

    def add_subscriber(self):
        client_queue = queue.Queue()
        with self.lock:
            self.subscribers.add(client_queue)
        return client_queue

    def remove_subscriber(self, client_queue):
        with self.lock:
            self.subscribers.discard(client_queue)

    def start_fetcher(self):
        if self.fetcher_thread and self.fetcher_thread.is_alive():
            return

        self.publish_event({"type": "connection", "status": "connecting"})
        self.fetcher = DouyinLiveWebFetcher(
            self.live_id,
            event_handler=self.publish_event,
            verbose=False,
        )
        self.fetcher_thread = threading.Thread(target=self._run_fetcher, daemon=True)
        self.fetcher_thread.start()

    def _run_fetcher(self):
        try:
            self.fetcher.start()
        except Exception as err:
            self.publish_event({
                "type": "connection",
                "status": "error",
                "message": str(err),
            })

    def run(self):
        self.start_fetcher()
        handler = partial(LiveMessageRequestHandler, app=self)
        server = ThreadingHTTPServer((self.host, self.port), handler)
        print(f"Web UI: http://{self.host}:{self.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            if self.fetcher is not None:
                self.fetcher.stop()


class LiveMessageRequestHandler(BaseHTTPRequestHandler):
    server_version = "DouyinLiveWebUI/1.0"

    def __init__(self, *args, app=None, **kwargs):
        self.app = app
        super().__init__(*args, **kwargs)

    def do_GET(self):
        route = urlparse(self.path).path

        if route == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if route == "/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
            return
        if route == "/app.js":
            self._serve_static("app.js", "application/javascript; charset=utf-8")
            return
        if route == "/api/messages":
            self._send_json({"items": self.app.get_messages_snapshot()})
            return
        if route == "/api/status":
            self._send_json(self.app.get_state_snapshot())
            return
        if route == "/events":
            self._serve_events()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def log_message(self, format, *args):
        return

    def _serve_static(self, file_name, content_type):
        file_path = self.app.static_dir / file_name
        if not file_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload):
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_events(self):
        client_queue = self.app.add_subscriber()
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()

            while True:
                try:
                    payload = client_queue.get(timeout=15)
                    event_name = payload.get("type", "message")
                    data = json.dumps(payload, ensure_ascii=False)
                    chunk = f"event: {event_name}\ndata: {data}\n\n".encode("utf-8")
                except queue.Empty:
                    chunk = b": keepalive\n\n"

                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError:
            pass
        finally:
            self.app.remove_subscriber(client_queue)
