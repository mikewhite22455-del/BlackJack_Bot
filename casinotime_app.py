"""Desktop practice and public-card replay for the Casino Time VIP profile."""

import json
from pathlib import Path
import sys

from PyQt5 import QtCore, QtWidgets

from casinotime_core import PROFILE, RANKS, SOURCE_URL, Scenario, ShoeLedger, Table
from casinotime_rollout import compare_actions, public_view
from casinotime_live import LiveTablePanel


RULES_TEXT = """<h2>Casino Time · Pragmatic Play VIP Blackjack</h2>
<p>Eight decks (416 cards). Dealer stands on soft 17. Blackjack pays 3:2;
ordinary wins pay 1:1 and ties push. Double on any first two cards, including
after a split except split aces. One split per box. Split aces receive one card;
a split 21 pays 1:1. Insurance costs half the opening bet and pays 2:1.</p>
<p>The cut card ends the shoe after the current round. Early shoe replacement is
possible. The lab implements both ordinary and early shoe replacement.</p>
<h3>Unconfirmed table details</h3>
<p>Actual cut position, burn procedure, minimum/maximum bets, and the dealer's
ten-upcard peek/settlement rule are not established by the public article.
The controls select research assumptions. The article confirms an ace-upcard check.
Browser tab sharing provides a live pixel feed and a calibrated hand reader.
Automatic whole-table identities, round/shuffle detection and a casino API are
not validated or connected.</p>
<h3>What the program calculates</h3>
<p>Whole-table play across 1–7 seats; physical cards sampled without replacement;
stable card identities; observed Hi-Lo count; and next-card probabilities from
exposed cards. Hidden burns are not guessed. The negative dealer-peek result is
included in the next-card probabilities. Basic advice is a total-dependent
strategy, not a composition-optimal solver or a prediction of the next card.</p>
<p>Compare actions samples hidden cards from public evidence and simulates 1,000
continuations per legal action. Later decisions use basic strategy. The displayed
intervals quantify sampling noise; selecting the highest sample mean does not
prove that action is optimal. Practice sessions start from reproducible seed 1.</p>
<p>All cards in Practice are generated locally. Replay reads public-card logs only.
Live table connection receives the browser tab you choose; its configured rank boxes
can feed the hand advisor. It does not feed practice counts or execute game actions.</p>
<h3>Specialists</h3>
<p>The observation ledger records evidence; the shoe engine owns the deck; the
probability calculator handles arithmetic; the strategy module supplies baseline
actions; tests audit settlement. Optional CrewAI reviewers inspect exported
experiment results after a run. They do not alter counts or choose table actions.</p>
<p>Published rules checked 11 November 2026. Source: <a href=""" + '"' + SOURCE_URL + '"' + ">official game guide</a>.</p>"


class RolloutWorker(QtCore.QThread):
    result_ready = QtCore.pyqtSignal(object, str)

    def __init__(self, view, parent):
        super().__init__(parent)
        self.view = view

    def run(self):
        try:
            result = compare_actions(self.view, cancelled=self.isInterruptionRequested)
            self.result_ready.emit(result, "")
        except Exception as exc:
            self.result_ready.emit(None, str(exc))


class CasinoTimeWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Casino Time eight-deck blackjack lab")
        self.resize(1080, 820)
        self.table = None
        self.replay_ledger = None
        self.unit_balance = 0.0
        self.last_settled = 0
        self.rollout_worker = None
        self.build_ui()

    def build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("Casino Time · Eight-deck blackjack lab")
        title.setStyleSheet("font-size:24px;color:#44d5c5;font-weight:bold")
        root.addWidget(title)
        root.addWidget(QtWidgets.QLabel("Pragmatic Play VIP rules · Practice, research and live hand reading · 416-card shoe"))
        tabs = QtWidgets.QTabWidget()
        root.addWidget(tabs)
        practice = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(practice)
        self.build_controls(layout)
        self.status = QtWidgets.QLabel("Choose the unconfirmed table assumptions, then start practice.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.display = QtWidgets.QTextBrowser()
        layout.addWidget(self.display)
        self.build_actions(layout)
        self.compare_button = QtWidgets.QPushButton("Compare actions — 1,000 simulated continuations each")
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self.start_comparison)
        layout.addWidget(self.compare_button)
        self.comparison = QtWidgets.QLabel("Action comparisons use exposed-card composition and basic-strategy continuations.")
        self.comparison.setWordWrap(True)
        layout.addWidget(self.comparison)
        self.probabilities = QtWidgets.QLabel()
        self.probabilities.setWordWrap(True)
        layout.addWidget(self.probabilities)
        tabs.addTab(practice, "Practice table")
        self.live_panel = LiveTablePanel(self)
        tabs.addTab(self.live_panel, "Live table connection")
        self.build_replay(tabs)
        rules = QtWidgets.QTextBrowser()
        rules.setOpenExternalLinks(True)
        rules.setHtml(RULES_TEXT)
        tabs.addTab(rules, "Rules and model")
        self.setStyleSheet("QWidget{font-size:14px} QPushButton{padding:7px} QGroupBox{margin-top:10px}")

    def build_controls(self, layout):
        form = QtWidgets.QFormLayout()
        self.ten_rule = QtWidgets.QComboBox()
        self.ten_rule.addItem("Unconfirmed — choose a simulation scenario", None)
        self.ten_rule.addItem("Assume dealer checks ten before decisions", "peek")
        self.ten_rule.addItem("Assume no ten check; dealer blackjack takes all bets", "no_peek_all_bets")
        form.addRow("Dealer ten-upcard scenario", self.ten_rule)
        row = QtWidgets.QHBoxLayout()
        self.cut = QtWidgets.QSpinBox()
        self.cut.setRange(52, 312)
        self.cut.setValue(208)
        self.seats = QtWidgets.QSpinBox()
        self.seats.setRange(1, 7)
        self.seats.setValue(5)
        self.burn = QtWidgets.QSpinBox()
        self.burn.setRange(0, 10)
        self.burn.setValue(1)
        for text, field in (("Assumed cut position", self.cut), ("Occupied seats", self.seats),
                            ("Assumed hidden burns", self.burn)):
            row.addWidget(QtWidgets.QLabel(text))
            row.addWidget(field)
        form.addRow(row)
        layout.addLayout(form)
        self.begin = QtWidgets.QPushButton("Start new practice session")
        self.begin.clicked.connect(self.start_session)
        layout.addWidget(self.begin)

    def build_actions(self, layout):
        grid = QtWidgets.QGridLayout()
        self.actions = {}
        labels = ("Deal", "Hit", "Stand", "Double", "Split", "Insurance", "Decline insurance",
                  "Finish using basic strategy")
        for index, action in enumerate(labels):
            button = QtWidgets.QPushButton(action)
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, a=action: self.apply_action(a))
            grid.addWidget(button, index // 4, index % 4)
            self.actions[action] = button
        layout.addLayout(grid)
        row = QtWidgets.QHBoxLayout()
        for text, callback in (("Replace shoe early", self.replace_shoe), ("Export public shoe log", self.export_log)):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)

    def start_session(self):
        if self.ten_rule.currentData() is None:
            self.status.setText("The published guide does not settle the dealer-ten rule. Choose a labelled assumption first.")
            return
        self.table = Table(Scenario(self.ten_rule.currentData(), self.cut.value(), self.seats.value(), self.burn.value()))
        self.unit_balance = 0.0
        self.last_settled = 0
        self.comparison.setText("Action comparisons use exposed-card composition and basic-strategy continuations.")
        self.refresh()

    def start_comparison(self):
        if self.rollout_worker is not None or self.table is None or self.table.phase != "player":
            return
        self.rollout_worker = RolloutWorker(public_view(self.table), self)
        self.rollout_worker.result_ready.connect(self.receive_comparison)
        self.rollout_worker.finished.connect(self.comparison_finished)
        self.comparison.setText("Comparing actions from public cards only...")
        self.refresh_actions(self.table.public_state())
        self.rollout_worker.start()

    def receive_comparison(self, result, error):
        if error or result is None:
            self.comparison.setText(error or "Comparison cancelled.")
            return
        lines = ["Rollout estimates: net units for your whole seat, with basic strategy after this decision."]
        for action, estimate in result["actions"].items():
            low, high = estimate["approx_95pct_interval"]
            lines.append(f"{action}: {estimate['mean_net_seat_units']:+.3f} (approx. 95% interval {low:+.3f} to {high:+.3f})")
        lines.append("Highest sample mean: " + result["highest_sample_mean"] + ". Sampling noise can change the ranking.")
        self.comparison.setText("\n".join(lines))

    def comparison_finished(self):
        worker = self.rollout_worker
        self.rollout_worker = None
        if worker is not None:
            worker.deleteLater()
        self.refresh_actions(self.table.public_state())

    def closeEvent(self, event):
        self.live_panel.shutdown()
        if self.rollout_worker is not None:
            self.rollout_worker.requestInterruption()
            self.rollout_worker.wait()
        event.accept()

    def apply_action(self, action):
        try:
            self._apply_action(action)
            self.comparison.setText("Action comparisons use exposed-card composition and basic-strategy continuations.")
            self.refresh()
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def _apply_action(self, action):
        if self.table is None:
            raise ValueError("Start a practice session first.")
        if action == "Deal":
            self.table.start()
        elif action in ("Insurance", "Decline insurance"):
            self.table.insure([action == "Insurance"] + [False] * (self.table.scenario.seats - 1))
        elif action == "Finish using basic strategy":
            self.table.autoplay()
        else:
            self.table.act(action)
        # The user controls seat 1. All other seats use deterministic basic strategy.
        while self.table.phase == "player" and self.table.active[0] != 0:
            self.table.act(self.table.basic_action())

    def refresh(self):
        state = self.table.public_state()
        if state["phase"] == "settled" and self.last_settled != state["round"]:
            self.unit_balance += self.table.profits()[0]
            self.last_settled = state["round"]
        self.begin.setEnabled(state["phase"] in ("ready", "settled"))
        for control in (self.ten_rule, self.cut, self.seats, self.burn):
            control.setEnabled(state["phase"] in ("ready", "settled"))
        self.status.setText(f"Shoe {state['shoe']} · Round {state['round']} · {state['phase']} · "
                            f"Seat 1 practice balance: {self.unit_balance:+.1f} units")
        lines = [f"<h2>Dealer: {' &nbsp; '.join(state['dealer']) or 'Waiting for deal'}</h2>"]
        for i, seat in enumerate(state["seats"]):
            for j, hand in enumerate(seat):
                marker = " → " if state["active"] == (i, j) else ""
                result = f" · net {hand['profit']:+.1f}" if state["phase"] == "settled" else ""
                lines.append(f"<p><b>{marker}Seat {i + 1}, hand {j + 1}:</b> {' &nbsp; '.join(hand['cards'])}"
                             f" — {hand['total']} · {hand['bet']:g} units{result}</p>")
        self.display.setHtml("".join(lines))
        self.refresh_actions(state)
        probabilities = self.table.next_card_probabilities()
        tc = state["true_count_estimate"]
        tc_text = "unavailable" if tc is None else f"{tc:+.2f}"
        text = " · ".join(f"{rank}: {probabilities[rank]:.1%}" for rank in RANKS)
        self.probabilities.setText(f"Cards left in shoe: {state['remaining']} · Unknown removed: {state['unknown_removed']}\n"
                                   f"Observed Hi-Lo: {state['running_count']:+d} · True-count estimate: {tc_text}\n"
                                   f"Next-card probabilities: {text}\n"
                                   + ("Cut reached: shuffle after this round."
                                      if state["cut_reached"] else "Same shoe continues."))

    def refresh_actions(self, state):
        allowed = set(self.table.legal_actions())
        if state["phase"] in ("ready", "settled"):
            allowed.add("Deal")
        if state["phase"] == "insurance":
            allowed.update(("Insurance", "Decline insurance"))
        if state["phase"] in ("player", "insurance"):
            allowed.add("Finish using basic strategy")
        for action, button in self.actions.items():
            button.setEnabled(action in allowed and self.rollout_worker is None)
        self.compare_button.setEnabled(state["phase"] == "player" and self.rollout_worker is None)
        if state["phase"] == "player":
            base = self.status.text().split(" · Basic-strategy reference:", 1)[0]
            self.status.setText(base + f" · Basic-strategy reference: {self.table.basic_action()}")

    def replace_shoe(self):
        if self.table is None:
            return
        try:
            self.table.new_shoe()
            self.comparison.setText("New shoe started; previous action estimates cleared.")
            self.refresh()
        except ValueError as exc:
            self.status.setText(str(exc))

    def export_log(self):
        if self.table is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save observed shoe", "shoe-log.json", "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(json.dumps(self.table.shoe.ledger.export(), indent=2), encoding="utf-8")
                self.status.setText("Saved the public-card shoe log. Hidden ranks are excluded.")
            except OSError as exc:
                self.status.setText(str(exc))

    def build_replay(self, tabs):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        label = QtWidgets.QLabel(
            "Load an exported shoe log to reconstruct its exposed cards. "
            "Unobserved ranks remain unknown; a reported observation gap disables probabilities.")
        label.setWordWrap(True)
        layout.addWidget(label)
        button = QtWidgets.QPushButton("Open public-card log")
        button.clicked.connect(self.import_log)
        layout.addWidget(button)
        self.replay_display = QtWidgets.QTextBrowser()
        layout.addWidget(self.replay_display)
        tabs.addTab(page, "Shoe replay")

    def import_log(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open observed shoe", "", "JSON (*.json)")
        if not path:
            return
        try:
            if Path(path).stat().st_size > 1024 * 1024:
                raise ValueError("Shoe log is too large.")
            self.replay_ledger = ShoeLedger.replay(json.loads(Path(path).read_text(encoding="utf-8")))
            ledger = self.replay_ledger
            data = {"profile": PROFILE, "shoe": ledger.shoe_id, "valid": ledger.valid, "issue": ledger.issue,
                    "cards_recorded": len(ledger.cards), "unknown_removed": ledger.unknown_removed,
                    "running_count": ledger.running_count, "unseen_rank_counts": ledger.unseen,
                    "unconditioned_next_card": ledger.probabilities() if ledger.valid and ledger.physical_remaining else None,
                    "note": "Replay does not retain dealer-peek conditions; probabilities here are unconditioned."}
            self.replay_display.setPlainText(json.dumps(data, indent=2))
        except (OSError, ValueError, TypeError) as exc:
            self.replay_display.setPlainText(f"Unable to use this log: {exc}")


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Casino Time eight-deck lab")
    window = CasinoTimeWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
