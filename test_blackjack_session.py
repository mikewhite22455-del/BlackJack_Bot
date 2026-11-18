import json
import math
import tempfile
import unittest
from pathlib import Path

from blackjack_bot import get_bet_size
from blackjack_session import (
    HandResult,
    SessionConfig,
    SessionManager,
    SessionMode,
    SessionStatus,
    check_risk_limits,
    config_from_dict,
    load_config_file,
    suggest_bet,
)


class BetCapTests(unittest.TestCase):
    def test_get_bet_size_respects_max_units(self):
        self.assertEqual(get_bet_size(5, max_units=4), 4)
        self.assertEqual(get_bet_size(1, max_units=4), 2)
        with self.assertRaises(ValueError):
            get_bet_size(2, max_units=0)

    def test_suggest_bet_applies_unit_size_and_caps(self):
        config = SessionConfig(
            starting_bankroll=200,
            unit_size=5,
            max_units=4,
            stop_loss=40,
            take_profit=40,
            table_min=5,
            table_max=100,
        )
        advice = suggest_bet(5, config, bankroll=200)
        self.assertEqual(advice.units, 4)
        self.assertEqual(advice.amount, 20.0)
        self.assertTrue(advice.allowed)
        self.assertTrue(advice.capped)


class SessionConfigTests(unittest.TestCase):
    def test_rejects_stop_loss_covering_entire_bankroll(self):
        with self.assertRaises(ValueError):
            SessionConfig(starting_bankroll=100, stop_loss=100, unit_size=5, table_min=5)

    def test_rejects_unit_below_table_min(self):
        with self.assertRaises(ValueError):
            SessionConfig(unit_size=1, table_min=5)

    def test_round_trip_config_file(self):
        payload = {
            "starting_bankroll": 150,
            "unit_size": 5,
            "max_units": 3,
            "stop_loss": 30,
            "take_profit": 45,
            "mode": "practice",
            "table_min": 5,
            "table_max": 200,
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_config_file(path)
        self.assertEqual(loaded, config_from_dict(payload))
        self.assertEqual(loaded.mode, SessionMode.PRACTICE)


class SessionManagerTests(unittest.TestCase):
    def test_live_requires_confirmation(self):
        manager = SessionManager()
        config = SessionConfig(mode=SessionMode.LIVE, stop_loss=40, take_profit=40)
        with self.assertRaises(ValueError):
            manager.start(config, live_confirmed=False)
        manager.start(config, live_confirmed=True)
        self.assertEqual(manager.state.status, SessionStatus.ACTIVE)

    def test_stop_loss_halts_further_betting_advice(self):
        manager = SessionManager()
        config = SessionConfig(
            starting_bankroll=100,
            unit_size=10,
            max_units=2,
            stop_loss=20,
            take_profit=50,
            table_min=10,
            table_max=100,
        )
        manager.start(config)
        manager.record_hand(HandResult.LOSS, 10)
        manager.record_hand(HandResult.LOSS, 10)
        self.assertEqual(manager.state.status, SessionStatus.STOPPED)
        self.assertIn("Stop-loss", manager.state.stop_reason)
        advice = manager.advice_for(4)
        self.assertFalse(advice.allowed)
        with self.assertRaises(ValueError):
            manager.record_hand(HandResult.WIN, 10)

    def test_take_profit_halts_session(self):
        manager = SessionManager()
        config = SessionConfig(
            starting_bankroll=100,
            unit_size=10,
            max_units=2,
            stop_loss=40,
            take_profit=15,
            table_min=10,
            table_max=100,
        )
        manager.start(config)
        manager.record_hand(HandResult.BLACKJACK, 10)
        self.assertEqual(manager.state.bankroll, 115.0)
        self.assertEqual(manager.state.status, SessionStatus.STOPPED)
        self.assertIn("Take-profit", check_risk_limits(manager.state) or manager.state.stop_reason)

    def test_pause_blocks_recording_and_advice(self):
        manager = SessionManager()
        manager.start(SessionConfig(stop_loss=40, take_profit=40))
        manager.pause()
        with self.assertRaises(ValueError):
            manager.record_hand(HandResult.WIN, 5)
        self.assertFalse(manager.advice_for(3).allowed)
        manager.resume()
        manager.record_hand(HandResult.PUSH, 5)
        self.assertEqual(manager.state.hands_played, 1)

    def test_abort_is_idempotent_for_emergency_stop(self):
        manager = SessionManager()
        manager.start(SessionConfig(stop_loss=40, take_profit=40))
        manager.abort()
        manager.abort("again")
        self.assertEqual(manager.state.status, SessionStatus.STOPPED)

    def test_rejects_bet_above_bankroll(self):
        manager = SessionManager()
        manager.start(SessionConfig(starting_bankroll=25, stop_loss=10, take_profit=10,
                                    unit_size=5, table_min=5))
        with self.assertRaises(ValueError):
            manager.record_hand(HandResult.LOSS, 30)

    def test_session_log_writes_without_card_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "session-log.jsonl"
            manager = SessionManager(log_path=path)
            manager.start(SessionConfig(stop_loss=40, take_profit=40))
            manager.record_hand(HandResult.WIN, 5)
            text = path.read_text(encoding="utf-8")
        self.assertIn("session_start", text)
        self.assertIn("hand", text)
        self.assertNotIn("screenshot", text.lower())
        self.assertNotIn("\"cards\"", text)

    def test_nonfinite_bankroll_inputs_rejected(self):
        for value in (math.nan, math.inf, -1, 0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SessionConfig(starting_bankroll=value, stop_loss=10, take_profit=10)


if __name__ == "__main__":
    unittest.main()
