"""Desktop hand entry, screen calibration, and background OCR monitoring."""

import json
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

from blackjack_bot import parse_cards
from blackjack_bvc import recommend_bvc
from casinotime_core import recommend_casinotime
from blackjack_strategy import Rules, recommend
from blackjack_vision import StableHand, read_rank


class RegionSelector(QtWidgets.QDialog):
    def __init__(self, screen):
        super().__init__(None)
        self.screen = screen
        self.background = screen.grabWindow(0)
        self.selection = QtCore.QRect()
        self.origin = None
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setGeometry(screen.geometry())
        self.setCursor(QtCore.Qt.CrossCursor)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.drawPixmap(self.rect(), self.background)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 75))
        painter.setPen(QtGui.QPen(QtGui.QColor("#00e6c0"), 3))
        painter.drawRect(self.selection)
        painter.setPen(QtCore.Qt.white)
        painter.drawText(25, 35, "Drag a tight box around ONE rank (not the suit). Escape cancels.")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.origin = event.pos()
            self.selection = QtCore.QRect(self.origin, self.origin)

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.selection = QtCore.QRect(self.origin, event.pos()).normalized().intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self.origin is not None:
            self.mouseMoveEvent(event)
            if self.selection.width() >= 8 and self.selection.height() >= 8:
                self.accept()


def region_for_selection(screen, rect):
    size = screen.geometry().size()
    return {"screen": screen.name(), "x": rect.x(), "y": rect.y(),
            "width": rect.width(), "height": rect.height(),
            "screen_width": size.width(), "screen_height": size.height(),
            "scale": screen.devicePixelRatio()}


def validate_region(region, screen):
    size = screen.geometry().size()
    if region.get("screen") != screen.name():
        raise ValueError("A configured screen is unavailable. Select the card boxes again.")
    if (region.get("screen_width"), region.get("screen_height"), region.get("scale")) != (
            size.width(), size.height(), screen.devicePixelRatio()):
        raise ValueError("The display size or scaling changed. Select the card boxes again.")
    values = [region.get(key) for key in ("x", "y", "width", "height")]
    if any(type(value) is not int for value in values):
        raise ValueError("Invalid card-area coordinates. Select the box again.")
    x, y, width, height = values
    if x < 0 or y < 0 or width < 8 or height < 8 or x + width > size.width() or y + height > size.height():
        raise ValueError("A card box falls outside the display. Select it again.")


def capture_regions(regions):
    """Capture each display once on the GUI thread, then crop in physical pixels."""
    import numpy as np

    screens = {screen.name(): screen for screen in QtWidgets.QApplication.screens()}
    frames = {}
    crops = []
    for region in regions:
        if not region or region.get("screen") not in screens:
            raise ValueError("Select a rank box for every current card and the dealer upcard.")
        screen = screens[region["screen"]]
        validate_region(region, screen)
        if screen.name() not in frames:
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                raise RuntimeError("Screen capture is unavailable. Check screen-recording permission or enter cards manually.")
            frames[screen.name()] = pixmap.toImage().convertToFormat(QtGui.QImage.Format_RGB888)
        image = frames[screen.name()]
        scale_x = image.width() / screen.geometry().width()
        scale_y = image.height() / screen.geometry().height()
        crop = image.copy(round(region["x"] * scale_x), round(region["y"] * scale_y),
                          round(region["width"] * scale_x), round(region["height"] * scale_y))
        pointer = crop.bits()
        pointer.setsize(crop.byteCount())
        pixels = np.frombuffer(pointer, dtype=np.uint8).reshape(crop.height(), crop.bytesPerLine())
        crops.append(pixels[:, :crop.width() * 3].reshape(crop.height(), crop.width(), 3).copy())
    return crops


class HandReader(QtCore.QThread):
    result_ready = QtCore.pyqtSignal(int, object, str)

    def __init__(self, images, generation, parent):
        super().__init__(parent)
        self.images = images
        self.generation = generation

    def run(self):
        try:
            readings = []
            for image in self.images:
                if self.isInterruptionRequested():
                    return
                readings.append(read_rank(image))
            self.result_ready.emit(self.generation, readings, "")
        except Exception as exc:
            self.result_ready.emit(self.generation, [], str(exc))


class AdvicePanel(QtWidgets.QWidget):
    profile_changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.generation = 0
        self.stability = StableHand()
        self.source = "manual"
        self.trusted = True
        self.updating_fields = False
        self.single_remaining = 0
        self.regions = [None, None, None]  # dealer first, then player cards
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1800)
        self.timer.timeout.connect(self.scan)
        self.settings_path = Path(QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.AppConfigLocation)) / "blackjack-table.json"
        self.build_ui()
        self.load_settings()
        self.update_advice()

    def build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Enter cards manually, or select one rank box per current card. "
            "Add a player box after a hit; use New Round after the table clears.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.build_rules(layout)
        self.build_hand(layout)
        self.advice = QtWidgets.QLabel()
        self.advice.setStyleSheet("font-size: 20px; font-weight: bold; padding: 8px;")
        self.advice.setWordWrap(True)
        layout.addWidget(self.advice)
        self.detail = QtWidgets.QLabel()
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.build_capture(layout)
        self.status = QtWidgets.QLabel("Manual entry is ready. Screen reading needs Tesseract and calibrated boxes.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def build_rules(self, layout):
        group = QtWidgets.QGroupBox("Table profile")
        form = QtWidgets.QFormLayout(group)
        self.profile = QtWidgets.QComboBox()
        self.profile.addItems(["Custom table - American peek", "Bitcoin Video Casino - advisory / practice",
                               "Casino Time - Pragmatic VIP / research"])
        form.addRow(self.profile)
        self.profile_note = QtWidgets.QLabel("Custom rules: 4-8 decks, American peek; double on any first two cards.")
        self.profile_note.setWordWrap(True)
        form.addRow(self.profile_note)
        self.ct_ten = QtWidgets.QComboBox()
        self.ct_ten.addItem("Dealer ten-upcard procedure: unconfirmed", None)
        self.ct_ten.addItem("Confirmed: ten-upcard peek before player decisions", "peek")
        self.ct_ten.addItem("Confirmed: no ten-upcard peek; blackjack takes all bets", "no_peek_all_bets")
        self.ct_ten.hide()
        self.ct_ten.currentIndexChanged.connect(self.rules_changed)
        form.addRow(self.ct_ten)
        self.soft17 = QtWidgets.QComboBox()
        self.soft17.addItems(["Dealer stands on soft 17 (S17)", "Dealer hits soft 17 (H17)"])
        form.addRow(self.soft17)
        self.das = QtWidgets.QCheckBox("Double after split allowed")
        self.das.setChecked(True)
        self.surrender = QtWidgets.QCheckBox("Late surrender allowed")
        form.addRow(self.das, self.surrender)
        self.confirm_rules = QtWidgets.QCheckBox("These match my table; doubling is allowed on any first two cards")
        form.addRow(self.confirm_rules)
        self.soft17.currentIndexChanged.connect(self.rules_changed)
        self.das.toggled.connect(self.rules_changed)
        self.surrender.toggled.connect(self.rules_changed)
        self.confirm_rules.toggled.connect(self.update_advice)
        self.profile.currentIndexChanged.connect(self.change_profile)
        layout.addWidget(group)

    @property
    def is_bvc(self):
        return self.profile.currentIndex() == 1

    @property
    def is_casinotime(self):
        return self.profile.currentIndex() == 2

    def change_profile(self):
        self.stop_monitoring()
        for field in (self.soft17, self.das, self.surrender):
            field.setEnabled(not (self.is_bvc or self.is_casinotime))
        if self.is_bvc or self.is_casinotime:
            self.soft17.setCurrentIndex(0)
            self.das.setChecked(True)
            self.surrender.setChecked(False)
        self.profile_note.setText(
            "5 decks, S17, 3:2, no peek; dealer blackjack takes all bets. "
            "Fresh shuffle each round. No insurance or side-bet advice. "
            "Rules checked November 11, 2026; confirm they still match."
            if self.is_bvc else "Custom rules: 4-8 decks, American peek; double on any first two cards.")
        if self.is_casinotime:
            self.profile_note.setText(
                "Casino Time Pragmatic VIP: 8 decks, S17, 3:2, DAS, one split per box, one card per split ace. "
                "Continuing shoe; ace checked before decisions. Ten-upcard rule needs confirmation. "
                "Use advice only after any dealer blackjack check is complete. Live game actions remain manual.")
        self.ct_ten.setVisible(self.is_casinotime)
        self.ct_ten.setCurrentIndex(0)
        self.splits_used.setVisible(self.is_bvc)
        self.splits_label.setVisible(self.is_bvc)
        self.confirm_rules.setChecked(False)
        self.reset_round()
        self.profile_changed.emit()

    def build_hand(self, layout):
        form = QtWidgets.QFormLayout()
        self.player = QtWidgets.QLineEdit()
        self.player.setPlaceholderText("Example: A, 7")
        self.dealer = QtWidgets.QLineEdit()
        self.dealer.setPlaceholderText("Example: 6")
        form.addRow("Your current hand", self.player)
        form.addRow("Dealer's visible upcard only", self.dealer)
        self.player.textChanged.connect(self.manual_changed)
        self.dealer.textChanged.connect(self.manual_changed)
        layout.addLayout(form)
        actions = QtWidgets.QHBoxLayout()
        self.can_double = QtWidgets.QCheckBox("Can double")
        self.can_double.setChecked(True)
        self.can_split = QtWidgets.QCheckBox("Can split")
        self.can_split.setChecked(True)
        self.after_split = QtWidgets.QCheckBox("Hand after split")
        self.split_aces = QtWidgets.QCheckBox("Split aces: one card only")
        for field in (self.can_double, self.can_split, self.after_split, self.split_aces):
            field.toggled.connect(self.update_advice)
            actions.addWidget(field)
        layout.addLayout(actions)
        split_form = QtWidgets.QFormLayout()
        self.splits_used = QtWidgets.QSpinBox()
        self.splits_used.setRange(0, 3)
        self.splits_used.valueChanged.connect(self.update_advice)
        self.splits_label = QtWidgets.QLabel("Splits used in this round (all hands)")
        split_form.addRow(self.splits_label, self.splits_used)
        self.splits_used.hide()
        self.splits_label.hide()
        layout.addLayout(split_form)

    def build_capture(self, layout):
        self.screen_choice = QtWidgets.QComboBox()
        for index, screen in enumerate(QtWidgets.QApplication.screens(), start=1):
            self.screen_choice.addItem(screen.name() or f"Display {index}", screen.name())
        layout.addWidget(self.screen_choice)
        self.slot_table = QtWidgets.QTableWidget(0, 3)
        self.slot_table.setHorizontalHeaderLabels(["Card", "Screen area", "Set area"])
        self.slot_table.verticalHeader().hide()
        self.slot_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.slot_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.slot_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.slot_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.slot_table.setMaximumHeight(180)
        layout.addWidget(self.slot_table)
        self.refresh_slots()
        buttons = QtWidgets.QHBoxLayout()
        for text, callback in (("Add player card", self.add_slot), ("Remove last card", self.remove_slot),
                               ("Save table setup", self.save_settings)):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        controls = QtWidgets.QHBoxLayout()
        self.read_button = QtWidgets.QPushButton("Read hand twice")
        self.read_button.clicked.connect(self.read_once)
        self.start_button = QtWidgets.QPushButton("Start monitoring")
        self.start_button.clicked.connect(self.start_monitoring)
        self.stop_button = QtWidgets.QPushButton("Stop / enter manually")
        self.stop_button.clicked.connect(self.stop_monitoring)
        for button in (self.read_button, self.start_button, self.stop_button):
            controls.addWidget(button)
        layout.addLayout(controls)

    def rules_changed(self):
        self.confirm_rules.setChecked(False)
        self.update_advice()

    def update_advice(self):
        if not hasattr(self, "advice"):
            return
        self.detail.clear()
        if not self.confirm_rules.isChecked():
            self.advice.setText("Confirm your table rules first")
            return
        if self.source == "screen" and not self.trusted:
            self.advice.setText("Waiting for a clear, stable hand reading")
            return
        try:
            cards = parse_cards(self.player.text())
            dealer = parse_cards(self.dealer.text())
            if len(dealer) != 1:
                raise ValueError("Enter exactly one dealer upcard.")
            result = self.hand_recommendation(cards, dealer[0])
        except ValueError as exc:
            self.advice.setText(str(exc))
            return
        self.advice.setText(f"{result.action.upper()} - {'Soft' if result.soft else 'Hard'} {result.total}")
        self.detail.setText(f"{result.reason} Source: {self.source}. Count deviations are not used.")

    def hand_recommendation(self, cards, dealer):
        options = dict(can_double=self.can_double.isChecked(), can_split=self.can_split.isChecked(),
                       after_split=self.after_split.isChecked(), split_aces=self.split_aces.isChecked())
        if self.is_bvc:
            return recommend_bvc(cards, dealer, splits_used=self.splits_used.value(), **options)
        if self.is_casinotime:
            return recommend_casinotime(cards, dealer, dealer_ten=self.ct_ten.currentData(), **options)
        return recommend(cards, dealer, Rules(
            hit_soft_17=self.soft17.currentIndex() == 1,
            double_after_split=self.das.isChecked(), late_surrender=self.surrender.isChecked()), **options)

    def manual_changed(self):
        if self.updating_fields:
            return
        self.stop_monitoring()
        self.source = "manual"
        self.trusted = True
        self.update_advice()

    def refresh_slots(self):
        self.slot_table.setRowCount(len(self.regions))
        for index, region in enumerate(self.regions):
            self.slot_table.setItem(index, 0, QtWidgets.QTableWidgetItem("Dealer upcard" if index == 0 else f"Player {index}"))
            description = "Not selected" if region is None else (
                f"{region['screen']}: {region['x']},{region['y']} / {region['width']} x {region['height']}")
            self.slot_table.setItem(index, 1, QtWidgets.QTableWidgetItem(description))
            button = QtWidgets.QPushButton("Select rank")
            button.clicked.connect(lambda checked=False, row=index: self.select_region(row))
            self.slot_table.setCellWidget(index, 2, button)

    def add_slot(self):
        if len(self.regions) < 22:
            self.stop_monitoring()
            self.regions.append(None)
            self.refresh_slots()

    def remove_slot(self):
        if len(self.regions) > 3:
            self.stop_monitoring()
            self.regions.pop()
            self.refresh_slots()

    def select_region(self, index):
        self.stop_monitoring()
        screen = next((s for s in QtWidgets.QApplication.screens() if s.name() == self.screen_choice.currentData()), None)
        if screen is None:
            self.status.setText("Select an available screen first.")
            return
        selector = RegionSelector(screen)
        if selector.background.isNull():
            self.status.setText("Screen capture permission is unavailable. Manual entry still works.")
            return
        if selector.exec_() == QtWidgets.QDialog.Accepted:
            self.regions[index] = region_for_selection(screen, selector.selection)
            self.refresh_slots()
        selector.deleteLater()

    def validate_setup(self):
        if any(region is None for region in self.regions):
            raise ValueError("Select a box around each current player rank and the dealer upcard.")
        for i, first in enumerate(self.regions):
            for second in self.regions[i + 1:]:
                if first["screen"] == second["screen"]:
                    one = QtCore.QRect(first["x"], first["y"], first["width"], first["height"])
                    two = QtCore.QRect(second["x"], second["y"], second["width"], second["height"])
                    if one.intersects(two):
                        raise ValueError("Card boxes overlap. Select one separate rank per card.")

    def read_once(self):
        self.stop_monitoring()
        self.single_remaining = 2
        self.scan()

    def start_monitoring(self):
        self.stop_monitoring()
        self.timer.start()
        self.scan()

    def stop_monitoring(self):
        self.timer.stop()
        self.single_remaining = 0
        self.generation += 1
        self.stability.reset()
        if self.worker is not None:
            self.worker.requestInterruption()
        self.player.setReadOnly(False)
        self.dealer.setReadOnly(False)
        if self.source == "screen":
            self.trusted = False
        self.update_advice()

    def scan(self):
        if not self.timer.isActive() and self.single_remaining <= 0:
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.source = "screen"
        self.trusted = False
        self.update_advice()
        try:
            self.validate_setup()
            images = self.capture_images()
        except Exception as exc:
            self.stop_monitoring()
            self.status.setText(str(exc))
            return
        self.player.setReadOnly(True)
        self.dealer.setReadOnly(True)
        self.status.setText("Reading configured rank boxes...")
        self.worker = HandReader(images, self.generation, self)
        self.worker.result_ready.connect(self.receive_scan)
        self.worker.finished.connect(self.scan_finished)
        self.worker.start()

    def capture_images(self):
        return capture_regions(self.regions)

    def receive_scan(self, generation, readings, error):
        if generation != self.generation:
            return
        if self.single_remaining:
            self.single_remaining -= 1
        if error:
            self.stop_monitoring()
            self.status.setText(f"Reading failed: {error}")
            return
        if len(readings) != len(self.regions):
            self.stability.reset()
            self.trusted = False
            self.status.setText("Incomplete hand reading. Advice withheld.")
            self.update_advice()
            return
        signature = self.stability.accept(readings)
        if signature is None:
            problems = [f"{'Dealer' if index == 0 else f'Player {index}'}: {r.error}" for index, r in enumerate(readings)
                        if r.error]
            self.status.setText(" / ".join(problems) or "Waiting for a second matching scan.")
            self.trusted = False
        else:
            self.updating_fields = True
            self.dealer.setText(signature[0])
            self.player.setText(", ".join(signature[1:]))
            self.updating_fields = False
            self.trusted = True
            self.status.setText("Two matching readings. Check the displayed cards; add a box for every new card after a hit.")
        self.update_advice()

    def scan_finished(self):
        worker = self.sender()
        if worker is self.worker:
            self.worker = None
        if worker is not None:
            worker.deleteLater()
        if self.single_remaining:
            QtCore.QTimer.singleShot(getattr(self, "second_scan_delay", 150), self.scan)
        if not self.timer.isActive() and not self.single_remaining:
            self.player.setReadOnly(False)
            self.dealer.setReadOnly(False)

    def reset_round(self):
        self.stop_monitoring()
        self.source = "manual"
        self.trusted = True
        self.updating_fields = True
        self.player.clear()
        self.dealer.clear()
        self.updating_fields = False
        self.regions = self.regions[:3]
        self.refresh_slots()
        self.after_split.setChecked(False)
        self.split_aces.setChecked(False)
        self.can_split.setChecked(True)
        self.can_double.setChecked(True)
        self.splits_used.setValue(0)
        self.status.setText("New round. Check that the selected boxes match the new card positions, then restart reading.")
        self.update_advice()

    def save_settings(self):
        data = {"version": 1, "regions": self.regions, "soft17": self.soft17.currentIndex(),
                "das": self.das.isChecked(), "surrender": self.surrender.isChecked(),
                "profile": "bvc" if self.is_bvc else "casinotime" if self.is_casinotime else "custom"}
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data), encoding="utf-8")
            temporary.replace(self.settings_path)
        except OSError as exc:
            self.status.setText(f"Could not save table setup: {exc}")
            return
        self.status.setText("Table setup saved. Card readings and screenshots are not saved.")

    def load_settings(self):
        try:
            if not self.settings_path.exists():
                return
            if self.settings_path.stat().st_size > 100_000:
                raise ValueError("Settings file is too large.")
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not 3 <= len(data["regions"]) <= 22:
                raise ValueError("Unsupported saved setup.")
            screens = {screen.name(): screen for screen in QtWidgets.QApplication.screens()}
            for region in data["regions"]:
                if region is not None:
                    validate_region(region, screens[region["screen"]])
            self.profile.setCurrentIndex({"bvc": 1, "casinotime": 2}.get(data.get("profile"), 0))
            self.regions = data["regions"]
            if not self.is_bvc and not self.is_casinotime:
                self.soft17.setCurrentIndex(1 if data.get("soft17") == 1 else 0)
                self.das.setChecked(data.get("das") is True)
                self.surrender.setChecked(data.get("surrender") is True)
            self.refresh_slots()
            self.confirm_rules.setChecked(False)
        except (OSError, ValueError, KeyError, TypeError):
            self.status.setText("Saved table setup could not be used. Select the card boxes again.")
