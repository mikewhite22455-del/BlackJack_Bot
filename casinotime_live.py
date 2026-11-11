"""Browser-pixel preview and calibrated live hand reader, without casino actions."""

import json
from io import BytesIO

import numpy as np
from PIL import Image
from PyQt5 import QtCore, QtGui, QtWidgets

from blackjack_advisor import AdvicePanel
from casinotime_bridge import CaptureBridge


def frame_key(frame):
    return frame.stream_id, frame.width, frame.height


def validate_box(region, frame):
    if not isinstance(region, dict) or region.get("screen") != "Shared tab":
        raise ValueError("Select rank boxes on the shared table preview.")
    if (region.get("screen_width"), region.get("screen_height")) != (frame.width, frame.height):
        raise ValueError("The shared table size changed. Select the rank boxes again.")
    values = [region.get(k) for k in ("x", "y", "width", "height")]
    if any(type(v) is not int for v in values):
        raise ValueError("Invalid rank box.")
    x, y, width, height = values
    if min(x, y) < 0 or min(width, height) < 8 or x + width > frame.width or y + height > frame.height:
        raise ValueError("Rank box falls outside the captured table.")


def crop_frame(frame, regions):
    for region in regions:
        validate_box(region, frame)
    with Image.open(BytesIO(frame.jpeg)) as picture:
        rgb = np.array(picture.convert("RGB"))
    return [rgb[r["y"]:r["y"] + r["height"], r["x"]:r["x"] + r["width"]].copy() for r in regions]


class RankView(QtWidgets.QGraphicsView):
    def __init__(self, picture, parent):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.scene().addPixmap(picture)
        self.setSceneRect(QtCore.QRectF(picture.rect()))
        self.box = self.scene().addRect(QtCore.QRectF(), QtGui.QPen(QtGui.QColor("#00cbb9"), 2))
        self.origin = None
        self.selection = QtCore.QRectF()
        self.setCursor(QtCore.Qt.CrossCursor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.origin = self.mapToScene(event.pos())
            self.selection = QtCore.QRectF()
            self.box.setRect(self.selection)

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.selection = QtCore.QRectF(self.origin, self.mapToScene(event.pos())).normalized()
            self.selection = self.selection.intersected(self.sceneRect())
            self.box.setRect(self.selection)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.mouseMoveEvent(event)
            self.origin = None


class FrameSelector(QtWidgets.QDialog):
    def __init__(self, frame, parent):
        super().__init__(parent)
        self.setWindowTitle("Select one upright card rank")
        self.resize(1000, 680)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Drag around ONE rank, excluding its suit, totals and opposite corner."))
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(frame.jpeg, "JPEG")
        self.view = RankView(pixmap, self)
        layout.addWidget(self.view)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SharedTabAdvisor(AdvicePanel):
    second_scan_delay = 600

    def __init__(self, bridge, parent):
        self.bridge = bridge
        self.verified_key = None
        self.last_read_sequence = 0
        self.read_key = None
        self.read_images = []
        super().__init__(parent)
        self.profile.setCurrentIndex(2)
        self.profile.setEnabled(False)
        self.screen_choice.hide()
        self.layout_verified = QtWidgets.QCheckBox("I checked these rank boxes against the current shared table")
        self.layout_verified.toggled.connect(self.verify_layout)
        self.layout().insertWidget(1, self.layout_verified)
        self.status.setText("Connect a tab, select the current hand's rank boxes, then verify the layout and rules.")

    def verify_layout(self, checked):
        self.stop_monitoring()
        self.verified_key = None
        if not checked:
            return
        try:
            frame = self.bridge.snapshot()
            for region in self.regions:
                validate_box(region, frame)
            self.verified_key = frame_key(frame)
        except ValueError as exc:
            self.layout_verified.setChecked(False)
            self.status.setText(str(exc))

    def invalidate_source(self, reason):
        self.stop_monitoring()
        self.trusted = False
        self.source = "screen"
        self.verified_key = None
        self.last_read_sequence = 0
        self.layout_verified.setChecked(False)
        self.confirm_rules.setChecked(False)
        self.status.setText(reason)
        self.update_advice()

    def validate_setup(self):
        frame = self.bridge.snapshot()
        if self.verified_key != frame_key(frame):
            raise ValueError("Check the selected rank boxes and verify this shared-table layout first.")
        for region in self.regions:
            validate_box(region, frame)
        super().validate_setup()

    def capture_images(self):
        frame = self.bridge.snapshot()
        if frame.sequence == self.last_read_sequence:
            raise ValueError("No new frame arrived. Wait for the feed, then restart reading.")
        self.last_read_sequence = frame.sequence
        self.read_key = frame_key(frame)
        self.read_images = crop_frame(frame, self.regions)
        return self.read_images

    def receive_scan(self, generation, readings, error):
        if generation != self.generation:
            return
        try:
            frame = self.bridge.snapshot()
            if self.read_key != frame_key(frame) or self.verified_key != frame_key(frame):
                raise ValueError("Capture source changed during reading. Verify the layout again.")
            current = crop_frame(frame, self.regions)
            if len(current) != len(self.read_images) or any(
                    a.shape != b.shape or np.mean(np.abs(a.astype(float) - b.astype(float))) > 3
                    for a, b in zip(current, self.read_images)):
                self.stability.reset()
                self.trusted = False
                self.single_remaining = 0
                self.status.setText("Cards moved during reading. Waiting for a stable hand; restart a single read if needed.")
                self.update_advice()
                return
        except ValueError as exc:
            self.invalidate_source(str(exc))
            return
        super().receive_scan(generation, readings, error)

    def select_region(self, index):
        self.stop_monitoring()
        try:
            frame = self.bridge.snapshot()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        selector = FrameSelector(frame, self)
        if selector.exec_() == QtWidgets.QDialog.Accepted:
            rect = selector.view.selection.toAlignedRect()
            region = {"screen": "Shared tab", "x": rect.x(), "y": rect.y(), "width": rect.width(),
                      "height": rect.height(), "screen_width": frame.width, "screen_height": frame.height}
            try:
                validate_box(region, frame)
                self.regions[index] = region
                self.layout_verified.setChecked(False)
                self.refresh_slots()
            except ValueError as exc:
                self.status.setText(str(exc))
        selector.deleteLater()

    def load_settings(self):
        self.settings_path = self.settings_path.with_name("casinotime-shared-tab.json")
        try:
            if not self.settings_path.exists():
                return
            if self.settings_path.stat().st_size > 100_000:
                raise ValueError("Oversized setup.")
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("source") != "shared_tab" or not 3 <= len(data["regions"]) <= 22:
                raise ValueError("Unsupported setup.")
            keys = {"screen", "x", "y", "width", "height", "screen_width", "screen_height"}
            if any(not isinstance(r, dict) or set(r) != keys for r in data["regions"]):
                raise ValueError("Invalid saved rank boxes.")
            self.regions = data["regions"]
            self.refresh_slots()
        except (OSError, ValueError, KeyError, TypeError):
            self.status.setText("Saved tab layout could not be loaded. Select the rank boxes again.")

    def save_settings(self):
        try:
            self.validate_setup()
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"source": "shared_tab", "regions": self.regions}
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data), encoding="utf-8")
            temporary.replace(self.settings_path)
            self.status.setText("Rank boxes saved. Layout and rule confirmation are required again for a new connection.")
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))


class LiveTablePanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = CaptureBridge()
        self.source_key = None
        self.seen_sequence = 0
        self.healthy = False
        self.build_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.refresh_frame)

    def build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel("Share the Casino Time tab from your browser, then check the preview. "
                                 "The full tab is captured; the hand reader reads only your calibrated rank boxes.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QtWidgets.QHBoxLayout()
        for title, callback in (("Connect browser capture", self.connect_browser), ("Disconnect", self.disconnect),
                                ("Save calibration image", self.save_frame)):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QtWidgets.QLabel("Disconnected. No casino account connection or game actions are active.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)
        self.preview = QtWidgets.QLabel("The shared table will appear here.")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setMinimumSize(300, 180)
        self.preview.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        tabs.addTab(self.preview, "Full-table preview")
        self.reader = SharedTabAdvisor(self.bridge, self)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.reader)
        tabs.addTab(scroll, "Calibrated hand reader")
        note = QtWidgets.QLabel("This is a visible-card feed. Automatic whole-table card identities, round and shuffle "
                                "recognition, and betting are not connected. Practice counts remain separate from this feed.")
        note.setWordWrap(True)
        layout.addWidget(note)

    def connect_browser(self):
        try:
            url = self.bridge.start()
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):
                raise OSError("Could not open the capture page in your browser.")
            self.timer.start()
            self.status.setText("Capture page opened. Click Share casino tab there and select the correct table.")
        except OSError as exc:
            self.status.setText(str(exc))

    def disconnect(self):
        self.timer.stop()
        self.reader.invalidate_source("Capture disconnected. Reconnect and verify the table before reading.")
        self.bridge.close()
        self.source_key = None
        self.seen_sequence = 0
        self.healthy = False
        self.preview.clear()
        self.preview.setText("Disconnected.")
        self.status.setText("Disconnected. Captured frames cleared from memory.")

    def refresh_frame(self):
        try:
            frame = self.bridge.snapshot()
        except ValueError as exc:
            if self.healthy:
                self.reader.invalidate_source(str(exc))
                self.preview.clear()
                self.preview.setText("Feed interrupted — waiting for a fresh frame.")
            self.healthy = False
            self.status.setText(str(exc))
            return
        key = frame_key(frame)
        if self.source_key != key:
            self.reader.invalidate_source("Capture source or size changed. Check the table, rank boxes and rules.")
            self.source_key = key
        self.healthy = True
        if self.seen_sequence == frame.sequence:
            return
        self.seen_sequence = frame.sequence
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(frame.jpeg, "JPEG")
        self.preview.setPixmap(pixmap.scaled(self.preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        self.status.setText(f"Receiving shared table: {frame.width} × {frame.height}, frame {frame.sequence}. "
                            "Confirm the table title in the preview before using the reader.")

    def save_frame(self):
        try:
            frame = self.bridge.snapshot()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save table calibration image", "table-calibration.png", "PNG (*.png)")
        if path:
            image = QtGui.QImage.fromData(frame.jpeg, "JPEG")
            if image.save(path, "PNG"):
                self.status.setText("Calibration image saved to the location you selected.")
            else:
                self.status.setText("Could not save the calibration image.")

    def shutdown(self):
        self.disconnect()
        if self.reader.worker is not None:
            self.reader.worker.requestInterruption()
            self.reader.worker.wait()
