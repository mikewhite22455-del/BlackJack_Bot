from dataclasses import replace
from io import BytesIO
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

import cv2
import numpy as np
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402
from blackjack_vision import RankReading  # noqa: E402
from casinotime_live import LiveTablePanel, crop_frame  # noqa: E402


def hand_image():
    image = np.full((100, 390, 3), 255, dtype=np.uint8)
    for index, rank in enumerate(("6", "A", "10")):
        cv2.putText(image, rank, (20 + index * 130, 75), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3, cv2.LINE_AA)
    buffer = BytesIO()
    Image.fromarray(image).save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


class LivePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings = patch.object(QtCore.QStandardPaths, "writableLocation", return_value=self.temporary.name)
        self.settings.start()
        self.panel = LiveTablePanel()
        self.reader = self.panel.reader
        self.stream = str(uuid.uuid4())
        self.panel.bridge.begin_stream(self.stream)
        self.feed()
        self.panel.refresh_frame()
        self.reader.regions = [{"screen": "Shared tab", "x": i * 130, "y": 0, "width": 130, "height": 100,
                                "screen_width": 390, "screen_height": 100} for i in range(3)]
        self.reader.refresh_slots()

    def tearDown(self):
        self.panel.shutdown()
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()
        self.settings.stop()
        self.temporary.cleanup()

    def feed(self, data=None):
        self.panel.bridge.receive(self.stream, data or hand_image())

    def verify(self):
        self.reader.layout_verified.setChecked(True)
        self.reader.confirm_rules.setChecked(True)

    def test_capture_is_idle_until_user_connects(self):
        self.assertIsNone(self.panel.bridge.server)
        with patch.object(QtGui.QDesktopServices, "openUrl", return_value=True) as opened:
            self.panel.connect_browser()
            self.assertTrue(opened.call_args[0][0].toString().startswith("http://127.0.0.1:"))
        self.assertTrue(self.panel.timer.isActive())

    def test_preview_and_crops_match_received_pixels(self):
        self.assertIn("Receiving shared table", self.panel.status.text())
        self.assertFalse(self.panel.preview.pixmap().isNull())
        self.verify()
        self.reader.validate_setup()
        crops = crop_frame(self.panel.bridge.snapshot(), self.reader.regions)
        self.assertEqual([c.shape for c in crops], [(100, 130, 3)] * 3)
        self.reader.regions[0]["width"] = 500
        with self.assertRaises(ValueError):
            self.reader.validate_setup()

    def test_repeated_same_frame_cannot_make_two_independent_readings(self):
        self.verify()
        self.reader.capture_images()
        with self.assertRaisesRegex(ValueError, "No new frame"):
            self.reader.capture_images()

    def test_source_change_and_stale_feed_revoke_trust(self):
        self.verify()
        self.reader.trusted = True
        self.stream = str(uuid.uuid4())
        self.panel.bridge.begin_stream(self.stream)
        self.feed()
        self.panel.refresh_frame()
        self.assertFalse(self.reader.layout_verified.isChecked())
        self.assertFalse(self.reader.trusted)
        self.verify()
        frame = self.panel.bridge.frame
        self.panel.bridge.frame = replace(frame, received=frame.received - 10)
        self.panel.refresh_frame()
        self.assertFalse(self.reader.trusted)
        self.assertFalse(self.reader.confirm_rules.isChecked())
        self.assertIn("stale", self.panel.status.text())

    def test_cards_changing_while_ocr_runs_withholds_old_result(self):
        self.verify()
        self.reader.capture_images()
        changed = BytesIO()
        Image.new("RGB", (390, 100), "black").save(changed, format="JPEG")
        self.feed(changed.getvalue())
        self.reader.receive_scan(self.reader.generation, [RankReading(r, 99) for r in ("6", "A", "10")], "")
        self.assertFalse(self.reader.trusted)
        self.assertIn("moved", self.reader.status.text())

    def test_saved_coordinates_require_new_confirmation(self):
        self.verify()
        self.reader.save_settings()
        other = LiveTablePanel()
        try:
            self.assertEqual(other.reader.regions, self.reader.regions)
            self.assertFalse(other.reader.layout_verified.isChecked())
            self.assertFalse(other.reader.confirm_rules.isChecked())
            self.assertFalse(other.reader.timer.isActive())
        finally:
            other.shutdown()
            other.deleteLater()

    @unittest.skipUnless(shutil.which("tesseract"), "Tesseract not installed")
    def test_real_shared_frame_ocr_reaches_advisor(self):
        self.verify()
        self.reader.source = "screen"
        readings = None
        for _ in range(2):
            self.feed()
            images = self.reader.capture_images()
            from blackjack_advisor import HandReader
            worker = HandReader(images, self.reader.generation, self.reader)
            worker.result_ready.connect(self.reader.receive_scan)
            spy = QtTest.QSignalSpy(worker.result_ready)
            worker.start()
            self.assertTrue(spy.wait(10000))
            worker.wait()
            readings = spy[0][1]
            worker.deleteLater()
        self.assertEqual([r.rank for r in readings], ["6", "A", "10"])
        self.assertTrue(self.reader.trusted)
        self.assertIn("BLACKJACK", self.reader.advice.text())
