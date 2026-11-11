from dataclasses import replace
import http.client
from io import BytesIO
import unittest
import uuid

from PIL import Image

from casinotime_bridge import CaptureBridge, MAX_BODY


def jpeg(width=400, height=200, color="white", kind="JPEG"):
    output = BytesIO()
    Image.new("RGB", (width, height), color).save(output, format=kind)
    return output.getvalue()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = CaptureBridge()
        self.bridge.start()
        self.stream = str(uuid.uuid4())

    def tearDown(self):
        self.bridge.close()

    def request(self, path, body=b"", headers=None, method="POST"):
        connection = http.client.HTTPConnection("127.0.0.1", self.bridge.server.server_port, timeout=3)
        fields = {"Origin": self.bridge.origin, "X-Capture-Token": self.bridge.token,
                  "X-Stream-Id": self.stream, "Content-Type": "image/jpeg"}
        fields.update(headers or {})
        connection.request(method, path, body=body, headers=fields)
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result

    def test_http_frame_lifecycle(self):
        self.assertEqual(self.bridge.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.request("/start")[0], 204)
        picture = jpeg()
        self.assertEqual(self.request("/frame", picture)[0], 204)
        frame = self.bridge.snapshot()
        self.assertEqual((frame.width, frame.height, frame.jpeg), (400, 200, picture))
        self.assertEqual(self.request("/stop")[0], 204)
        with self.assertRaisesRegex(ValueError, "Waiting"):
            self.bridge.snapshot()

    def test_source_changes_cannot_accept_old_frames_or_old_stops(self):
        self.request("/start")
        first = self.stream
        self.stream = str(uuid.uuid4())
        self.request("/start")
        self.assertEqual(self.request("/frame", jpeg(), {"X-Stream-Id": first})[0], 400)
        self.request("/frame", jpeg())
        self.request("/stop", headers={"X-Stream-Id": first})
        self.assertEqual(self.bridge.snapshot().stream_id, self.stream)

    def test_unauthorized_origins_tokens_and_hosts_are_rejected(self):
        cases = [{"Origin": "https://example.com"}, {"Origin": "null"}, {"X-Capture-Token": "wrong"},
                 {"Host": "external.example"}, {"X-Capture-Token": "é"}]
        for fields in cases:
            with self.subTest(fields=fields):
                self.assertEqual(self.request("/start", headers=fields)[0], 403)
        self.assertIsNone(self.bridge.frame)
        self.assertEqual(self.request("/frame", method="OPTIONS")[0], 403)

    def test_invalid_images_dimensions_and_sizes_are_rejected(self):
        self.request("/start")
        for data in (b"not an image", jpeg(kind="PNG"), jpeg(4097, 32)):
            with self.subTest(size=len(data)):
                self.assertEqual(self.request("/frame", data)[0], 400)
        self.assertEqual(self.request("/frame", headers={"Content-Length": str(MAX_BODY + 1)})[0], 413)
        self.assertIsNone(self.bridge.frame)

    def test_stale_frames_are_not_returned(self):
        self.request("/start")
        self.request("/frame", jpeg())
        self.bridge.frame = replace(self.bridge.frame, received=self.bridge.frame.received - 10)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.bridge.snapshot()

    def test_assets_are_fixed_no_token_or_file_browsing(self):
        status, page, headers = self.request("/", method="GET")
        self.assertEqual(status, 200)
        self.assertNotIn(self.bridge.token.encode(), page)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.request("/../requirements.txt", method="GET")[0], 404)
        self.assertEqual(self.request("/unknown")[0], 400)

    def test_restart_rotates_connection_token_and_discards_frames(self):
        token = self.bridge.token
        self.request("/start")
        self.request("/frame", jpeg())
        self.bridge.close()
        self.assertIsNone(self.bridge.frame)
        self.bridge.start()
        self.assertNotEqual(token, self.bridge.token)
        self.assertEqual(self.request("/start", headers={"X-Capture-Token": token})[0], 403)
