import shutil
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from blackjack_vision import RankReading, StableHand, read_rank, reading_from_data


@pytest.mark.parametrize("text,confidence,rank", [
    ("10", 96, "10"), ("a", 90, "A"), ("5", 79, None),
    ("A K", 98, None), ("O", 99, None), ("100", 99, None), ("", -1, None),
])
def test_ocr_requires_one_rank_and_high_confidence(text, confidence, rank):
    assert reading_from_data({"text": [text], "conf": [confidence]}).rank == rank


def test_stability_requires_agreement_and_clears_after_uncertainty():
    stable = StableHand()
    cards = [RankReading(rank, 95) for rank in ("6", "A", "7")]
    assert stable.accept(cards) is None
    assert stable.accept(cards) == ("6", "A", "7")
    changed = cards[:2] + [RankReading("8", 95)]
    assert stable.accept(changed) is None
    assert stable.accept(changed) == ("6", "A", "8")
    assert stable.accept([RankReading(None, 0, "unclear")] + cards[1:]) is None
    assert stable.accept(changed) is None
    stable.reset()
    assert stable.accept(changed) is None


def test_blank_image_does_not_invoke_tesseract():
    with patch("blackjack_vision.configure_tesseract") as configure:
        assert read_rank(np.full((50, 50), 255, dtype=np.uint8)).rank is None
        configure.assert_not_called()


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract application is not installed")
@pytest.mark.parametrize("rank", ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"])
def test_real_ocr_on_generated_rank_images(rank):
    image = np.full((100, 130, 3), 255, dtype=np.uint8)
    cv2.putText(image, rank, (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3, cv2.LINE_AA)
    reading = read_rank(image)
    # Recognition may withhold a low-confidence rank; it must never substitute another rank.
    assert reading.rank in (rank, None)
    if reading.rank is None:
        assert reading.error
    else:
        assert reading.confidence >= 80


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract application is not installed")
def test_real_ocr_complete_hand_reaches_stable_reader():
    readings = []
    for rank in ("6", "A", "10"):
        image = np.full((100, 130, 3), 255, dtype=np.uint8)
        cv2.putText(image, rank, (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3, cv2.LINE_AA)
        readings.append(read_rank(image))
    stable = StableHand()
    assert stable.accept(readings) is None
    assert stable.accept(readings) == ("6", "A", "10")
