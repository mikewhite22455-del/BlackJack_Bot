import os
import shutil
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PyQt5 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402
from blackjack_advisor import AdvicePanel, capture_regions, region_for_selection  # noqa: E402
from blackjack_vision import RankReading  # noqa: E402


@pytest.fixture
def panel():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = AdvicePanel()
    yield widget
    widget.stop_monitoring()
    if widget.worker is not None:
        widget.worker.wait(7000)
    app.processEvents()
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_manual_advice_respects_rules_and_available_actions(panel):
    panel.player.setText("A, 7")
    panel.dealer.setText("6")
    assert "Confirm" in panel.advice.text()
    panel.confirm_rules.setChecked(True)
    assert panel.advice.text().startswith("DOUBLE")
    panel.can_double.setChecked(False)
    assert panel.advice.text().startswith("STAND")
    panel.soft17.setCurrentIndex(1)
    assert not panel.confirm_rules.isChecked()
    assert "Confirm" in panel.advice.text()


def test_bvc_profile_uses_no_peek_strategy_and_requires_split_state(panel):
    panel.profile.setCurrentIndex(1)
    assert not panel.soft17.isEnabled()
    assert not panel.surrender.isEnabled()
    panel.player.setText("8, 8")
    panel.dealer.setText("10")
    assert "Confirm" in panel.advice.text()
    panel.confirm_rules.setChecked(True)
    assert panel.advice.text().startswith("HIT")
    panel.after_split.setChecked(True)
    assert "must agree" in panel.advice.text()
    panel.splits_used.setValue(3)
    panel.dealer.setText("6")
    assert panel.advice.text().startswith("STAND")
    panel.reset_round()
    assert panel.splits_used.value() == 0
    panel.profile.setCurrentIndex(0)
    assert panel.soft17.isEnabled()
    assert not panel.confirm_rules.isChecked()


def test_bvc_saved_profile_remains_unconfirmed_and_preserves_boxes(panel, tmp_path):
    panel.settings_path = tmp_path / "bvc.json"
    panel.profile.setCurrentIndex(1)
    panel.confirm_rules.setChecked(True)
    panel.regions = [None] * 5
    panel.save_settings()
    panel.profile.setCurrentIndex(0)
    panel.load_settings()
    assert panel.is_bvc
    assert len(panel.regions) == 5
    assert not panel.confirm_rules.isChecked()


def test_casinotime_profile_requires_ten_rule_and_limits_splits(panel):
    panel.profile.setCurrentIndex(2)
    panel.player.setText("8, 8")
    panel.dealer.setText("10")
    panel.confirm_rules.setChecked(True)
    assert "Confirm the dealer-ten" in panel.advice.text()
    panel.ct_ten.setCurrentIndex(1)
    assert not panel.confirm_rules.isChecked()
    panel.confirm_rules.setChecked(True)
    assert panel.advice.text().startswith("SPLIT")
    panel.after_split.setChecked(True)
    assert panel.advice.text().startswith("HIT")
    assert not panel.soft17.isEnabled()
    assert not panel.surrender.isChecked()


def test_casinotime_setup_never_restores_rule_confirmation(panel, tmp_path):
    panel.settings_path = tmp_path / "casino-time.json"
    panel.profile.setCurrentIndex(2)
    panel.ct_ten.setCurrentIndex(2)
    panel.confirm_rules.setChecked(True)
    panel.save_settings()
    panel.profile.setCurrentIndex(0)
    panel.load_settings()
    assert panel.is_casinotime
    assert panel.ct_ten.currentData() is None
    assert not panel.confirm_rules.isChecked()


def test_stable_screen_advice_is_removed_on_uncertain_or_incomplete_readings(panel):
    panel.confirm_rules.setChecked(True)
    panel.source = "screen"
    panel.trusted = False
    cards = [RankReading(rank, 96) for rank in ("6", "A", "7")]
    panel.receive_scan(panel.generation, cards, "")
    assert "Waiting" in panel.advice.text()
    panel.receive_scan(panel.generation, cards, "")
    assert panel.advice.text().startswith("DOUBLE")
    panel.receive_scan(panel.generation, [RankReading(None, 0, "unclear")] + cards[1:], "")
    assert "Waiting" in panel.advice.text()
    panel.receive_scan(panel.generation, cards[:2], "")
    assert "Waiting" in panel.advice.text()


def test_reset_ignores_old_worker_results(panel):
    generation = panel.generation
    panel.reset_round()
    cards = [RankReading(rank, 96) for rank in ("6", "A", "7")]
    panel.receive_scan(generation, cards, "")
    panel.receive_scan(generation, cards, "")
    assert panel.player.text() == ""
    assert panel.dealer.text() == ""
    assert panel.worker is None


def test_stopped_queued_scan_does_not_capture(panel):
    panel.stop_monitoring()
    with patch("blackjack_advisor.capture_regions") as capture:
        panel.scan()
        capture.assert_not_called()


def test_missing_setup_or_overlapping_boxes_blocks_scanning(panel):
    panel.regions = [None, None, None]
    panel.read_once()
    assert "Select a box" in panel.status.text()
    assert panel.worker is None
    screen = QtWidgets.QApplication.screens()[0]
    region = region_for_selection(screen, QtCore.QRect(10, 10, 20, 20))
    panel.regions = [region, region, region]
    with pytest.raises(ValueError, match="overlap"):
        panel.validate_setup()


def test_settings_preserve_boxes_but_require_rules_confirmation(panel, tmp_path):
    panel.settings_path = tmp_path / "setup.json"
    panel.soft17.setCurrentIndex(1)
    panel.das.setChecked(False)
    panel.confirm_rules.setChecked(True)
    panel.save_settings()
    panel.soft17.setCurrentIndex(0)
    panel.load_settings()
    assert panel.soft17.currentIndex() == 1
    assert not panel.das.isChecked()
    assert not panel.confirm_rules.isChecked()
    assert "screenshot" not in panel.settings_path.read_text()


def test_capture_scales_logical_boxes_to_physical_pixels(panel):
    class Screen:
        def name(self):
            return "test-display"

        def geometry(self):
            return QtCore.QRect(0, 0, 400, 200)

        def devicePixelRatio(self):
            return 2.0

        def grabWindow(self, window):
            image = QtGui.QImage(800, 400, QtGui.QImage.Format_RGB888)
            image.fill(QtGui.QColor("red"))
            return QtGui.QPixmap.fromImage(image)

    screen = Screen()
    region = region_for_selection(screen, QtCore.QRect(10, 20, 30, 40))
    with patch("blackjack_advisor.QtWidgets.QApplication.screens", return_value=[screen]):
        crops = capture_regions([region])
        assert crops[0].shape == (80, 60, 3)
        assert tuple(crops[0][0, 0]) == (255, 0, 0)
        with pytest.raises(ValueError, match="scaling changed"):
            capture_regions([{**region, "scale": 1.0}])


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract application is not installed")
def test_real_ocr_worker_to_advice_end_to_end(panel):
    images = []
    for rank in ("6", "A", "10"):
        image = np.full((100, 130, 3), 255, dtype=np.uint8)
        cv2.putText(image, rank, (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3, cv2.LINE_AA)
        images.append(image)
    screen = QtWidgets.QApplication.screens()[0]
    panel.regions = [region_for_selection(screen, QtCore.QRect(10 + i * 40, 10, 30, 30)) for i in range(3)]
    panel.confirm_rules.setChecked(True)
    with patch("blackjack_advisor.capture_regions", return_value=images):
        panel.read_once()
        deadline = time.monotonic() + 12
        while (panel.worker is not None or panel.single_remaining) and time.monotonic() < deadline:
            QtTest.QTest.qWait(20)
    assert panel.single_remaining == 0
    assert panel.worker is None
    assert panel.dealer.text() == "6"
    assert panel.player.text() == "A, 10"
    assert panel.advice.text().startswith("BLACKJACK")
