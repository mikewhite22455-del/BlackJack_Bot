"""Blackjack desktop assistant: configured OCR, basic strategy and count review.

Importing the counting logic does not require desktop/OCR dependencies.
"""

from collections import Counter
import math
import re
import sys


card_values = {
    "2": 1, "3": 1, "4": 1, "5": 1, "6": 1,
    "7": 0, "8": 0, "9": 0,
    "10": -1, "J": -1, "Q": -1, "K": -1, "A": -1,
}
CARD_PATTERN = re.compile(
    r"(?<![A-Z0-9])(10|[2-9JQKA])(?:[CDHS\u2660\u2665\u2666\u2663])?(?![A-Z0-9])"
)


def extract_card_ranks(text):
    """Extract separated OCR ranks, including 10 and optional suit suffixes."""
    return CARD_PATTERN.findall(text.upper())


def parse_cards(text):
    """Validate a manually reviewed, comma/space-separated card snapshot."""
    cards = []
    for token in re.split(r"[\s,;]+", text.strip().upper()):
        if not token:
            continue
        match = CARD_PATTERN.fullmatch(token)
        if match is None:
            raise ValueError(f"Unrecognized card: {token}")
        cards.append(match.group(1))
    return cards


def get_bet_size(tc):
    """Return the original unit schedule, using whole-count lower bounds."""
    tc = float(tc)
    if not math.isfinite(tc):
        raise ValueError("True count must be finite.")
    if tc < 1:
        return 1
    return min(10, 2 * math.floor(tc))


class CardCounter:
    """Keep a per-rank high-water mark until the user starts the next round.

    Submit the whole reviewed visible snapshot, not only the newest card.
    This prevents repeated snapshots, reordering and temporary disappearance
    from recounting ranks. It is not physical-card identity tracking.
    """

    def __init__(self, decks_remaining=4):
        self.running_count = 0
        self._seen = Counter()
        self.set_decks_remaining(decks_remaining)

    def set_decks_remaining(self, value):
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Decks remaining must be a positive number.")
        self.decks_remaining = value

    @property
    def true_count(self):
        return self.running_count / self.decks_remaining

    def observe(self, cards):
        cards = list(cards)
        if any(card not in card_values for card in cards):
            raise ValueError("The snapshot contains an invalid card.")
        visible = Counter(cards)
        added = visible - self._seen
        self.running_count += sum(
            card_values[card] * amount for card, amount in added.items()
        )
        self._seen |= visible
        return sum(added.values())

    def new_round(self):
        self._seen.clear()

    def new_shoe(self):
        self.running_count = 0
        self.new_round()


def capture_screen(region):
    """Capture only the explicitly configured card area."""
    if not region or region.get("width", 0) <= 0 or region.get("height", 0) <= 0:
        raise ValueError("Set a card-area width and height before reading.")
    import cv2
    import mss
    import numpy as np

    with mss.mss() as screen:
        return cv2.cvtColor(np.array(screen.grab(region)), cv2.COLOR_BGRA2GRAY)


def detect_cards(img):
    import cv2
    import pytesseract

    processed = cv2.threshold(
        img, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )[1]
    text = pytesseract.image_to_string(processed, config="--psm 6", timeout=5)
    return extract_card_ranks(text)


# Keep the desktop classes lazy so core tests and imports need no Qt runtime.
def create_overlay():  # noqa: C901
    from PyQt5 import QtCore, QtWidgets
    from blackjack_advisor import AdvicePanel

    class OCRWorker(QtCore.QThread):
        result_ready = QtCore.pyqtSignal(int, object, str)

        def __init__(self, region, generation, parent):
            super().__init__(parent)
            self.region = region
            self.generation = generation

        def run(self):
            try:
                cards = detect_cards(capture_screen(self.region))
                self.result_ready.emit(self.generation, cards, "")
            except Exception as exc:
                self.result_ready.emit(self.generation, [], str(exc))

    class BlackjackOverlay(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.counter = CardCounter()
            self.worker = None
            self.generation = 0
            self.setWindowTitle("Blackjack Assistant")
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
            self.resize(780, 800)
            root = QtWidgets.QVBoxLayout(self)
            self.tabs = QtWidgets.QTabWidget()
            root.addWidget(self.tabs)
            self.advisor = AdvicePanel()
            advisor_scroll = QtWidgets.QScrollArea()
            advisor_scroll.setWidgetResizable(True)
            advisor_scroll.setWidget(self.advisor)
            self.tabs.addTab(advisor_scroll, "Hand Advisor")
            count_panel = QtWidgets.QWidget()
            self.tabs.addTab(count_panel, "Shoe Count")
            layout = QtWidgets.QVBoxLayout(count_panel)

            instructions = QtWidgets.QLabel(
                "Enter all visible cards, or read a card area and review the result. "
                "Use New Round only after the previous cards have been cleared."
            )
            instructions.setWordWrap(True)
            layout.addWidget(instructions)

            form = QtWidgets.QFormLayout()
            self.decks = QtWidgets.QDoubleSpinBox()
            self.decks.setRange(0.25, 12)
            self.decks.setSingleStep(0.25)
            self.decks.setValue(4)
            self.decks.valueChanged.connect(self.change_decks)
            form.addRow("Estimated decks remaining", self.decks)
            self.cards = QtWidgets.QLineEdit()
            self.cards.setPlaceholderText("Example: 10, A, 5, 5")
            form.addRow("Visible cards (review before applying)", self.cards)
            layout.addLayout(form)

            self.apply_button = QtWidgets.QPushButton("Apply reviewed snapshot")
            self.apply_button.clicked.connect(self.apply_snapshot)
            layout.addWidget(self.apply_button)

            region_layout = QtWidgets.QFormLayout()
            self.region_fields = {}
            for key in ("left", "top", "width", "height"):
                field = QtWidgets.QSpinBox()
                field.setRange(-32768 if key in ("left", "top") else 0, 32768)
                self.region_fields[key] = field
                region_layout.addRow(f"Card area {key} (pixels)", field)
            layout.addLayout(region_layout)
            self.scan_button = QtWidgets.QPushButton("Read card area for review")
            self.scan_button.clicked.connect(self.read_screen)
            layout.addWidget(self.scan_button)

            self.count_label = QtWidgets.QLabel()
            layout.addWidget(self.count_label)
            self.status = QtWidgets.QLabel("Ready for a reviewed snapshot.")
            self.status.setWordWrap(True)
            layout.addWidget(self.status)
            note = QtWidgets.QLabel(
                "Hand Advisor readings do not change this count. "
                "Apply a reviewed snapshot covering all visible table cards here.")
            note.setWordWrap(True)
            layout.addWidget(note)

            buttons = QtWidgets.QHBoxLayout()
            self.round_button = QtWidgets.QPushButton("New Round (table cleared)")
            self.round_button.clicked.connect(self.new_round)
            buttons.addWidget(self.round_button)
            self.shoe_button = QtWidgets.QPushButton("New Shoe")
            self.shoe_button.clicked.connect(self.new_shoe)
            buttons.addWidget(self.shoe_button)
            root.addLayout(buttons)
            self.advisor.profile_changed.connect(self.change_profile)
            self.change_profile()
            self.refresh_count()

        def change_profile(self):
            self.generation += 1
            self.counter.new_shoe()
            if self.advisor.is_casinotime:
                self.decks.setValue(8)
            self.cards.clear()
            self.tabs.setTabEnabled(1, not self.advisor.is_bvc)
            self.refresh_count()

        def refresh_count(self):
            if self.advisor.is_bvc:
                self.count_label.setText("Shoe count disabled: BVC reshuffles each round.")
                return
            self.count_label.setText(
                f"Running count: {self.counter.running_count:+d} | "
                f"True count: {self.counter.true_count:+.2f} | "
                f"Schedule: {get_bet_size(self.counter.true_count)} units"
            )

        def change_decks(self, value):
            self.counter.set_decks_remaining(value)
            self.refresh_count()

        def apply_snapshot(self):
            if self.advisor.is_bvc:
                return
            try:
                added = self.counter.observe(parse_cards(self.cards.text()))
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self.generation += 1
            self.refresh_count()
            self.status.setText(f"Added {added} newly observed card(s) this round.")

        def new_round(self):
            self.generation += 1
            self.counter.new_round()
            self.cards.clear()
            self.advisor.reset_round()
            if self.advisor.is_bvc:
                self.counter.new_shoe()
                self.refresh_count()
                self.status.setText("New BVC round. Fresh shuffle; no count carried forward.")
                return
            self.status.setText("New round. Shoe count retained.")

        def new_shoe(self):
            self.generation += 1
            self.counter.new_shoe()
            self.cards.clear()
            self.advisor.reset_round()
            self.refresh_count()
            self.status.setText("New shoe. Set estimated decks remaining for this shoe.")

        def read_screen(self):
            region = {key: field.value() for key, field in self.region_fields.items()}
            if region["width"] <= 0 or region["height"] <= 0:
                self.status.setText("Set a card-area width and height first.")
                return
            if self.worker is not None and self.worker.isRunning():
                return
            self.scan_button.setEnabled(False)
            self.cards.setEnabled(False)
            self.apply_button.setEnabled(False)
            self.status.setText("Reading card area...")
            self.worker = OCRWorker(region, self.generation, self)
            self.worker.result_ready.connect(self.receive_cards)
            self.worker.finished.connect(self.scan_finished)
            self.worker.start()

        def scan_finished(self):
            self.scan_button.setEnabled(True)
            self.cards.setEnabled(True)
            self.apply_button.setEnabled(True)

        def receive_cards(self, generation, cards, error):
            if generation != self.generation:
                return
            if error:
                self.status.setText(f"Screen reading failed: {error}")
                return
            self.cards.setText(", ".join(cards))
            self.status.setText("Review the detected ranks before applying this snapshot.")

        def closeEvent(self, event):
            self.advisor.stop_monitoring()
            workers = (self.worker, self.advisor.worker)
            if any(worker is not None and worker.isRunning() for worker in workers):
                self.status.setText("Wait for screen reading to finish, then close.")
                event.ignore()
                return
            event.accept()

    return BlackjackOverlay()


def run_bot():
    from PyQt5 import QtWidgets

    app = QtWidgets.QApplication(sys.argv)
    app.setOrganizationName("BlackjackAssistant")
    app.setApplicationName("BlackjackAssistant")
    overlay = create_overlay()
    overlay.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(run_bot())
