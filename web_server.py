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

SELECTABLE_EVENT_TYPES = {"chat", "gift", "like"}
DEBUG_EVENT_TYPES = {"packet", "parse_error", "unknown_message"}


class LiveMessageWebApp:
    def __init__(self, live_id, host="127.0.0.1", port=8000, history_size=200, cookie=""):
        self.live_id = str(live_id)
        self.host = host
        self.port = int(port)
        self.cookie = cookie or ""
        self.messages = deque(maxlen=history_size)
        self.subscribers = set()
        self.lock = threading.Lock()
        self.fetcher = None
        self.fetcher_thread = None
        self.static_dir = Path(__file__).resolve().parent / "webui"

    def publish_event(self, event):
        payload = dict(event)
        event_type = payload.get("type")

        with self.lock:
            if event_type in SELECTABLE_EVENT_TYPES:
                self.messages.append(payload)
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

        self.fetcher = DouyinLiveWebFetcher(
            self.live_id,
            cookie=self.cookie,
            event_handler=self.publish_event,
            verbose=False,
        )
        self.fetcher_thread = threading.Thread(target=self.fetcher.start, daemon=True)
        self.fetcher_thread.start()

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
        if route == "/events":
            self._serve_events()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def log_message(self, format, *args):
        return

    def handle(self):
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _serve_static(self, file_name, content_type):
        file_path = self.app.static_dir / file_name
        if not file_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        content = file_path.read_bytes()
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _send_json(self, payload):
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

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
                    event_type = payload.get("type")
                    if event_type not in SELECTABLE_EVENT_TYPES and event_type not in DEBUG_EVENT_TYPES:
                        continue
                    data = json.dumps(payload, ensure_ascii=False)
                    chunk = f"event: {event_type}\ndata: {data}\n\n".encode("utf-8")
                except queue.Empty:
                    chunk = b": keepalive\n\n"

                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError:
            pass
        finally:
            self.app.remove_subscriber(client_queue)
