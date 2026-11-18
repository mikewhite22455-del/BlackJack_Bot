"""Qt panel for practice/live bankroll limits and suggested cash bets."""

import json
from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from blackjack_session import (
    HandResult,
    SessionConfig,
    SessionManager,
    SessionMode,
    SessionStatus,
    config_from_dict,
    config_to_dict,
)


class BankrollPanel(QtWidgets.QWidget):
    """Manual bankroll tracker with stop-loss, take-profit, and bet caps."""

    session_changed = QtCore.pyqtSignal()

    def __init__(self, counter, parent=None):
        super().__init__(parent)
        self.counter = counter
        config_root = Path(QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.AppConfigLocation))
        self.settings_path = config_root / "blackjack-session.json"
        self.log_path = config_root / "session-log.jsonl"
        self.manager = SessionManager(log_path=self.log_path)
        self._building = True
        self.build_ui()
        self._building = False
        self.load_settings()
        self.refresh()

    def build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        notice = QtWidgets.QLabel(
            "This panel does not place bets or click a casino site. "
            "It sizes unit bets and stops advice when your limits are hit. "
            "Start in Practice before any Live session."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)

        form = QtWidgets.QFormLayout()
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("Practice (no money at risk)", SessionMode.PRACTICE.value)
        self.mode.addItem("Live (real money; confirm below)", SessionMode.LIVE.value)
        form.addRow("Mode", self.mode)

        self.starting = self._money_spin(200)
        self.unit_size = self._money_spin(5)
        self.max_units = QtWidgets.QSpinBox()
        self.max_units.setRange(1, 20)
        self.max_units.setValue(4)
        self.stop_loss = self._money_spin(50)
        self.take_profit = self._money_spin(50)
        self.table_min = self._money_spin(5)
        self.table_max = self._money_spin(500)
        form.addRow("Starting bankroll ($)", self.starting)
        form.addRow("Unit size ($)", self.unit_size)
        form.addRow("Max units (hard cap)", self.max_units)
        form.addRow("Stop-loss ($)", self.stop_loss)
        form.addRow("Take-profit ($)", self.take_profit)
        form.addRow("Table minimum ($)", self.table_min)
        form.addRow("Table maximum ($)", self.table_max)
        layout.addLayout(form)

        self.live_confirm = QtWidgets.QCheckBox(
            "I understand Live mode tracks real money and will stop advice at my limits"
        )
        layout.addWidget(self.live_confirm)

        controls = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start session")
        self.pause_button = QtWidgets.QPushButton("Pause")
        self.resume_button = QtWidgets.QPushButton("Resume")
        self.abort_button = QtWidgets.QPushButton("Abort / stop advising")
        self.start_button.clicked.connect(self.start_session)
        self.pause_button.clicked.connect(self.pause_session)
        self.resume_button.clicked.connect(self.resume_session)
        self.abort_button.clicked.connect(self.abort_session)
        for button in (self.start_button, self.pause_button, self.resume_button, self.abort_button):
            controls.addWidget(button)
        layout.addLayout(controls)

        results = QtWidgets.QHBoxLayout()
        self.bet_amount = self._money_spin(5)
        self.bet_amount.setMaximum(100000)
        results.addWidget(QtWidgets.QLabel("Hand bet ($)"))
        results.addWidget(self.bet_amount)
        for label, result in (
            ("Win", HandResult.WIN),
            ("Loss", HandResult.LOSS),
            ("Push", HandResult.PUSH),
            ("BJ +3:2", HandResult.BLACKJACK),
            ("Surrender", HandResult.SURRENDER),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(lambda checked=False, value=result: self.record(value))
            results.addWidget(button)
        layout.addLayout(results)

        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-size: 16px; font-weight: bold; padding: 6px;")
        layout.addWidget(self.summary)
        self.bet_label = QtWidgets.QLabel()
        self.bet_label.setWordWrap(True)
        layout.addWidget(self.bet_label)
        self.status = QtWidgets.QLabel(
            "Configure limits, start Practice, then record each hand result manually."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        persist = QtWidgets.QHBoxLayout()
        save = QtWidgets.QPushButton("Save risk settings")
        save.clicked.connect(self.save_settings)
        persist.addWidget(save)
        layout.addLayout(persist)

    def _money_spin(self, value):
        field = QtWidgets.QDoubleSpinBox()
        field.setDecimals(2)
        field.setRange(0.01, 1000000)
        field.setSingleStep(1)
        field.setValue(value)
        return field

    def current_config(self):
        return SessionConfig(
            starting_bankroll=self.starting.value(),
            unit_size=self.unit_size.value(),
            max_units=self.max_units.value(),
            stop_loss=self.stop_loss.value(),
            take_profit=self.take_profit.value(),
            mode=SessionMode(self.mode.currentData()),
            table_min=self.table_min.value(),
            table_max=self.table_max.value(),
        )

    def set_inputs_enabled(self, enabled):
        for widget in (
            self.mode, self.starting, self.unit_size, self.max_units,
            self.stop_loss, self.take_profit, self.table_min, self.table_max,
            self.live_confirm,
        ):
            widget.setEnabled(enabled)

    def start_session(self):
        try:
            config = self.current_config()
            self.manager.start(config, live_confirmed=self.live_confirm.isChecked())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.set_inputs_enabled(False)
        self.status.setText(
            f"{config.mode.value.title()} session started. "
            f"Logging to {self.log_path.name} (no cards or screenshots)."
        )
        self.refresh(notify=True)

    def pause_session(self):
        try:
            self.manager.pause()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.status.setText("Session paused. Betting advice is withheld.")
        self.refresh(notify=True)

    def resume_session(self):
        try:
            self.manager.resume()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.status.setText("Session resumed.")
        self.refresh(notify=True)

    def abort_session(self):
        self.manager.abort("Session aborted. Do not place another bet.")
        self.set_inputs_enabled(True)
        self.status.setText("Session aborted. Advice stopped. Reconfigure and start again if needed.")
        self.refresh(notify=True)

    def record(self, result):
        try:
            self.manager.record_hand(result, self.bet_amount.value())
        except ValueError as exc:
            self.status.setText(str(exc))
            self.refresh(notify=True)
            return
        state = self.manager.state
        if state.status is SessionStatus.STOPPED:
            self.set_inputs_enabled(True)
            self.status.setText(state.stop_reason)
        else:
            self.status.setText(
                f"Recorded {result.value}. Bankroll ${state.bankroll:.2f} "
                f"(P/L {state.profit:+.2f})."
            )
        self.refresh(notify=True)

    def refresh(self, notify=False):
        if self._building:
            return
        state = self.manager.state
        advice = self.manager.advice_for(self.counter.true_count)
        mode = state.config.mode.value
        self.summary.setText(
            f"Status: {state.status.value} | Mode: {mode} | "
            f"Bankroll: ${state.bankroll:.2f} | P/L: {state.profit:+.2f} | "
            f"Hands: {state.hands_played}"
        )
        if advice.allowed:
            self.bet_label.setText(
                f"Suggested bet: {advice.units} units = ${advice.amount:.2f}. {advice.reason}"
            )
            if state.status is SessionStatus.ACTIVE:
                self.bet_amount.setValue(advice.amount)
        else:
            self.bet_label.setText(advice.reason)
        active = state.status is SessionStatus.ACTIVE
        paused = state.status is SessionStatus.PAUSED
        self.start_button.setEnabled(state.status in (SessionStatus.IDLE, SessionStatus.STOPPED))
        self.pause_button.setEnabled(active)
        self.resume_button.setEnabled(paused and not state.stop_reason)
        self.abort_button.setEnabled(state.status in (SessionStatus.ACTIVE, SessionStatus.PAUSED))
        if notify:
            self.session_changed.emit()

    def save_settings(self):
        try:
            data = config_to_dict(self.current_config())
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.settings_path)
        except (OSError, ValueError) as exc:
            self.status.setText(f"Could not save risk settings: {exc}")
            return
        self.status.setText("Risk settings saved locally. No card data is stored.")

    def load_settings(self):
        try:
            if not self.settings_path.exists():
                return
            if self.settings_path.stat().st_size > 20_000:
                raise ValueError("Settings file is too large.")
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            config = config_from_dict(data)
        except (OSError, ValueError, TypeError, KeyError):
            self.status.setText("Saved risk settings could not be used. Check the values below.")
            return
        self.starting.setValue(config.starting_bankroll)
        self.unit_size.setValue(config.unit_size)
        self.max_units.setValue(config.max_units)
        self.stop_loss.setValue(config.stop_loss)
        self.take_profit.setValue(config.take_profit)
        self.table_min.setValue(config.table_min)
        self.table_max.setValue(config.table_max)
        index = self.mode.findData(config.mode.value)
        if index >= 0:
            self.mode.setCurrentIndex(index)
        self.live_confirm.setChecked(False)
