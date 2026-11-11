"""Conservative OCR for one rank per configured screen rectangle."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil

from blackjack_strategy import RANKS


@dataclass(frozen=True)
class RankReading:
    rank: str | None
    confidence: float
    error: str = ""


def configure_tesseract():
    import pytesseract

    candidates = [os.environ.get("TESSERACT_CMD"), shutil.which("tesseract")]
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        folder = os.environ.get(variable)
        if folder:
            candidates.append(str(Path(folder) / "Tesseract-OCR" / "tesseract.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return candidate
    raise RuntimeError("Install Tesseract OCR, or set TESSERACT_CMD to its executable. Manual entry still works.")


def reading_from_data(data, minimum_confidence=80):
    tokens = [(str(text).strip().upper(), float(conf))
              for text, conf in zip(data.get("text", []), data.get("conf", [])) if str(text).strip()]
    if len(tokens) != 1 or tokens[0][0] not in RANKS:
        return RankReading(None, 0, "Select one rank only; the reading is empty or ambiguous.")
    rank, confidence = tokens[0]
    if confidence < minimum_confidence:
        return RankReading(None, confidence, "Low OCR confidence; adjust the box or enter this card manually.")
    return RankReading(rank, confidence)


def read_rank(image):
    import cv2
    import numpy as np
    import pytesseract

    if image is None or image.size == 0:
        return RankReading(None, 0, "Empty screen region.")
    grey = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    if float(np.std(grey)) < 4:
        return RankReading(None, 0, "No visible rank in this box.")
    scale = max(1, min(4, 96 / grey.shape[0]))
    grey = cv2.resize(grey, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    processed = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    if float(np.mean(processed)) < 127:
        processed = 255 - processed
    processed = cv2.copyMakeBorder(processed, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
    configure_tesseract()
    data = pytesseract.image_to_data(
        processed, config="--psm 7", timeout=3, output_type=pytesseract.Output.DICT)
    reading = reading_from_data(data)
    if reading.rank is not None:
        return reading
    candidate = reading_from_data(data, minimum_confidence=0)
    if candidate.rank is not None:
        alternate = pytesseract.image_to_data(
            processed, config="--psm 8", timeout=3, output_type=pytesseract.Output.DICT)
        alternate_reading = reading_from_data(alternate)
        if alternate_reading.rank == candidate.rank:
            return alternate_reading
    return reading


class StableHand:
    """Require two agreeing complete scans; every uncertain scan clears trust."""

    def __init__(self, required_matches=2):
        self.required_matches = required_matches
        self.reset()

    def reset(self):
        self.previous = None
        self.matches = 0

    def accept(self, readings):
        if len(readings) < 3 or any(r.rank is None or r.error for r in readings):
            self.reset()
            return None
        signature = tuple(r.rank for r in readings)
        self.matches = self.matches + 1 if signature == self.previous else 1
        self.previous = signature
        return signature if self.matches >= self.required_matches else None
