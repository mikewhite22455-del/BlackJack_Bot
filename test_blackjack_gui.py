import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtTest, QtWidgets  # noqa: E402
from blackjack_bot import create_overlay  # noqa: E402


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.overlay = create_overlay()

    def tearDown(self):
        if self.overlay.worker is not None:
            self.overlay.worker.wait(6000)
        self.app.processEvents()
        self.overlay.close()
        self.overlay.deleteLater()
        self.app.processEvents()

    def wait_for_scan(self):
        deadline = time.monotonic() + 3
        while not self.overlay.scan_button.isEnabled() and time.monotonic() < deadline:
            QtTest.QTest.qWait(10)
        self.assertTrue(self.overlay.scan_button.isEnabled())

    def test_review_buttons_and_shoe_reset(self):
        self.overlay.cards.setText("5, 5, K")
        self.overlay.apply_button.click()
        self.assertEqual(self.overlay.counter.running_count, 1)
        self.overlay.apply_button.click()
        self.assertEqual(self.overlay.counter.running_count, 1)
        self.overlay.round_button.click()
        self.assertEqual(self.overlay.cards.text(), "")
        self.assertEqual(self.overlay.counter.running_count, 1)
        self.overlay.shoe_button.click()
        self.assertEqual(self.overlay.counter.running_count, 0)

    def test_deck_control_updates_display(self):
        self.overlay.cards.setText("5, 5")
        self.overlay.apply_button.click()
        self.overlay.decks.setValue(2)
        self.assertIn("True count: +1.00", self.overlay.count_label.text())

    def test_invalid_input_and_unconfigured_capture(self):
        self.overlay.cards.setText("5, invalid")
        self.overlay.apply_button.click()
        self.assertEqual(self.overlay.counter.running_count, 0)
        with patch("blackjack_bot.capture_screen") as capture:
            self.overlay.scan_button.click()
            capture.assert_not_called()
        self.assertTrue(self.overlay.scan_button.isEnabled())

    def test_old_ocr_result_cannot_restore_previous_round(self):
        generation = self.overlay.generation
        self.overlay.new_round()
        self.overlay.receive_cards(generation, ["A"], "")
        self.assertEqual(self.overlay.cards.text(), "")

    def test_ocr_is_async_and_requires_review_before_counting(self):
        started = threading.Event()
        release = threading.Event()

        def capture(region):
            started.set()
            release.wait(2)
            return object()

        self.overlay.region_fields["width"].setValue(200)
        self.overlay.region_fields["height"].setValue(100)
        with patch("blackjack_bot.capture_screen", side_effect=capture), patch(
            "blackjack_bot.detect_cards", return_value=["10", "5"]
        ):
            self.overlay.scan_button.click()
            try:
                self.assertTrue(started.wait(1))
                self.assertFalse(self.overlay.scan_button.isEnabled())
                self.assertFalse(self.overlay.apply_button.isEnabled())
                heartbeat = []
                QtCore.QTimer.singleShot(0, lambda: heartbeat.append(True))
                QtTest.QTest.qWait(20)
                self.assertEqual(heartbeat, [True])
                self.assertEqual(self.overlay.counter.running_count, 0)
            finally:
                release.set()
            self.wait_for_scan()
        self.assertEqual(self.overlay.cards.text(), "10, 5")
        self.assertEqual(self.overlay.counter.running_count, 0)
        self.assertTrue(self.overlay.apply_button.isEnabled())

    def test_ocr_error_keeps_count_and_restores_controls(self):
        self.overlay.cards.setText("5")
        self.overlay.apply_button.click()
        self.overlay.region_fields["width"].setValue(200)
        self.overlay.region_fields["height"].setValue(100)
        with patch("blackjack_bot.capture_screen", side_effect=RuntimeError("capture failed")):
            self.overlay.scan_button.click()
            self.wait_for_scan()
        self.assertIn("capture failed", self.overlay.status.text())
        self.assertEqual(self.overlay.counter.running_count, 1)
        self.assertTrue(self.overlay.cards.isEnabled())


if __name__ == "__main__":
    unittest.main()
