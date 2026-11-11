"""Loopback-only browser capture transport. No casino API or betting requests."""

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import re
import secrets
import threading
import time

from PIL import Image, UnidentifiedImageError


MAX_BODY = 6 * 1024 * 1024
ASSETS = Path(__file__).parent / "capture"


@dataclass(frozen=True)
class Frame:
    sequence: int
    stream_id: str
    width: int
    height: int
    jpeg: bytes
    received: float


class CaptureBridge:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.frame = None
        self.stream_id = None
        self.sequence = 0
        self.server = None
        self.thread = None

    def start(self):
        if self.server is None:
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
            self.server.daemon_threads = True
            self.server.bridge = self
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
        return self.url

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    @property
    def url(self):
        return self.origin + "/#" + self.token

    def begin_stream(self, stream_id):
        if not re.fullmatch(r"[a-f0-9-]{36}", stream_id):
            raise ValueError("Invalid stream identifier.")
        with self.lock:
            self.stream_id = stream_id
            self.frame = None

    def stop_stream(self, stream_id):
        with self.lock:
            if self.stream_id == stream_id:
                self.stream_id = None
                self.frame = None

    def receive(self, stream_id, body):
        with Image.open(BytesIO(body)) as picture:
            width, height = picture.size
            if picture.format != "JPEG" or not (32 <= width <= 4096 and 32 <= height <= 2304):
                raise ValueError("Expected a JPEG frame up to 4096 x 2304 pixels.")
            picture.load()
        with self.lock:
            if self.stream_id is None or self.stream_id != stream_id:
                raise ValueError("Capture source changed or stopped.")
            self.sequence += 1
            self.frame = Frame(self.sequence, stream_id, width, height, body, time.monotonic())

    def snapshot(self, max_age=3.0):
        with self.lock:
            frame = self.frame
        if frame is None:
            raise ValueError("Waiting for browser sharing. Choose the Casino Time tab in the capture page.")
        if time.monotonic() - frame.received > max_age:
            raise ValueError("Capture is stale. Return to the capture page and check sharing.")
        return frame

    def close(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
            self.server = None
            self.thread = None
        with self.lock:
            self.frame = None
            self.stream_id = None
        self.token = secrets.token_urlsafe(32)


class CaptureHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *args):
        pass  # Never log capture tokens, images or request paths.

    def reply(self, status, data=b"", content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'unsafe-inline'; media-src blob:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def valid_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403)
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/capture.js": ("capture.js", "text/javascript; charset=utf-8")}
        if self.path not in files:
            return self.reply(404)
        name, kind = files[self.path]
        self.reply(200, (ASSETS / name).read_bytes(), kind)

    def authorized(self):
        token = self.headers.get("X-Capture-Token", "")
        bridge = self.server.bridge
        origin = f"http://127.0.0.1:{self.server.server_port}"
        return (token.isascii() and self.valid_host() and self.headers.get("Origin") == origin
                and secrets.compare_digest(token, bridge.token))

    def do_OPTIONS(self):
        self.reply(403)  # No cross-origin access.

    def do_POST(self):
        if not self.authorized():
            return self.reply(403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_BODY or self.headers.get("Transfer-Encoding"):
                return self.reply(413)
            body = self.rfile.read(length)
            if len(body) != length:
                return self.reply(400)
            self.dispatch(body)
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
            self.reply(400, b"Invalid or interrupted capture request.")

    def dispatch(self, body):
        stream_id = self.headers.get("X-Stream-Id", "")
        bridge = self.server.bridge
        if self.path == "/start" and not body:
            bridge.begin_stream(stream_id)
        elif self.path == "/stop" and not body:
            bridge.stop_stream(stream_id)
        elif self.path == "/frame" and self.headers.get("Content-Type") == "image/jpeg":
            bridge.receive(stream_id, body)
        else:
            return self.reply(400)
        self.reply(204)
