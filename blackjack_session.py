"""Session bankroll and risk controls for live or practice play.

This module does not place bets or automate a casino site. It tracks
manual bankroll entries and caps suggested unit bets so a user can stop
before a configured loss or gain is exceeded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import math
from pathlib import Path
from typing import Any

from blackjack_bot import get_bet_size


class SessionMode(str, Enum):
    PRACTICE = "practice"
    LIVE = "live"


class HandResult(str, Enum):
    WIN = "win"
    LOSS = "loss"
    PUSH = "push"
    BLACKJACK = "blackjack"
    SURRENDER = "surrender"


class SessionStatus(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass(frozen=True)
class SessionConfig:
    starting_bankroll: float = 200.0
    unit_size: float = 5.0
    max_units: int = 4
    stop_loss: float = 50.0
    take_profit: float = 50.0
    mode: SessionMode = SessionMode.PRACTICE
    table_min: float = 5.0
    table_max: float = 500.0

    def __post_init__(self):
        validate_session_config(self)


def validate_session_config(config: SessionConfig) -> None:
    """Reject non-finite or inverted risk settings before a session starts."""
    fields = {
        "starting_bankroll": config.starting_bankroll,
        "unit_size": config.unit_size,
        "stop_loss": config.stop_loss,
        "take_profit": config.take_profit,
        "table_min": config.table_min,
        "table_max": config.table_max,
    }
    for name, value in fields.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be a number.")
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(f"{name} must be a positive finite number.")
    if not isinstance(config.max_units, int) or isinstance(config.max_units, bool):
        raise ValueError("max_units must be a positive integer.")
    if config.max_units < 1 or config.max_units > 20:
        raise ValueError("max_units must be between 1 and 20.")
    if config.table_min > config.table_max:
        raise ValueError("table_min cannot exceed table_max.")
    if config.unit_size < config.table_min:
        raise ValueError("unit_size must be at least the table minimum.")
    if config.stop_loss >= config.starting_bankroll:
        raise ValueError("stop_loss must be less than starting_bankroll.")
    if config.mode not in (SessionMode.PRACTICE, SessionMode.LIVE):
        raise ValueError("mode must be practice or live.")


@dataclass(frozen=True)
class BetAdvice:
    units: int
    amount: float
    capped: bool
    reason: str
    allowed: bool


@dataclass
class SessionState:
    config: SessionConfig
    bankroll: float
    status: SessionStatus = SessionStatus.IDLE
    hands_played: int = 0
    paused: bool = False
    stop_reason: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def profit(self) -> float:
        return self.bankroll - self.config.starting_bankroll

    @property
    def is_betting_allowed(self) -> bool:
        return self.status == SessionStatus.ACTIVE and not self.paused and not self.stop_reason


def _round_money(value: float) -> float:
    return round(float(value) + 0.0, 2)


def suggest_bet(true_count: float, config: SessionConfig, bankroll: float) -> BetAdvice:
    """Map true count to a capped cash bet that respects table and risk limits."""
    units = get_bet_size(true_count, max_units=config.max_units)
    amount = _round_money(units * config.unit_size)
    capped = units < get_bet_size(true_count, max_units=20)
    reasons = []
    if capped:
        reasons.append(f"capped at {config.max_units} units")
    if amount > config.table_max:
        amount = _round_money(config.table_max)
        capped = True
        reasons.append("table max")
    if amount < config.table_min:
        amount = _round_money(config.table_min)
        units = max(1, math.ceil(amount / config.unit_size))
        reasons.append("raised to table min")
    room_to_stop = bankroll - (config.starting_bankroll - config.stop_loss)
    if amount > bankroll:
        amount = _round_money(bankroll)
        capped = True
        reasons.append("bankroll remaining")
    if amount > room_to_stop > 0:
        amount = _round_money(room_to_stop)
        capped = True
        reasons.append("stop-loss room")
    if amount < config.table_min or amount <= 0:
        return BetAdvice(
            units=0,
            amount=0.0,
            capped=True,
            reason="Bankroll or stop-loss room is below the table minimum.",
            allowed=False,
        )
    units = max(1, min(config.max_units, math.floor(amount / config.unit_size + 1e-9)))
    reason = "Suggested bet from true count."
    if reasons:
        reason = "Suggested bet from true count (" + ", ".join(reasons) + ")."
    return BetAdvice(units=units, amount=amount, capped=capped, reason=reason, allowed=True)


def _result_delta(result: HandResult, bet: float) -> float:
    if result is HandResult.WIN:
        return bet
    if result is HandResult.LOSS:
        return -bet
    if result is HandResult.PUSH:
        return 0.0
    if result is HandResult.BLACKJACK:
        return _round_money(bet * 1.5)
    if result is HandResult.SURRENDER:
        return _round_money(-bet * 0.5)
    raise ValueError(f"Unsupported hand result: {result}")


def check_risk_limits(state: SessionState) -> str:
    """Return a stop reason when stop-loss or take-profit is reached."""
    profit = state.profit
    if profit <= -state.config.stop_loss:
        return (
            f"Stop-loss reached ({profit:+.2f} vs limit "
            f"-{state.config.stop_loss:.2f}). End the session."
        )
    if profit >= state.config.take_profit:
        return (
            f"Take-profit reached ({profit:+.2f} vs target "
            f"+{state.config.take_profit:.2f}). End the session."
        )
    if state.bankroll < state.config.table_min:
        return "Bankroll is below the table minimum. End the session."
    return ""


class SessionManager:
    """Track one practice or live bankroll session with hard stop rules."""

    def __init__(self, log_path: Path | None = None):
        self.log_path = log_path
        self.state = SessionState(
            config=SessionConfig(),
            bankroll=SessionConfig().starting_bankroll,
            status=SessionStatus.IDLE,
        )

    def start(self, config: SessionConfig, *, live_confirmed: bool = False) -> SessionState:
        validate_session_config(config)
        if config.mode is SessionMode.LIVE and not live_confirmed:
            raise ValueError("Live mode requires an explicit confirmation that money is at risk.")
        self.state = SessionState(
            config=config,
            bankroll=_round_money(config.starting_bankroll),
            status=SessionStatus.ACTIVE,
        )
        self._log("session_start", {"config": config_to_dict(config)})
        return self.state

    def pause(self) -> SessionState:
        if self.state.status != SessionStatus.ACTIVE:
            raise ValueError("Only an active session can be paused.")
        self.state.paused = True
        self.state.status = SessionStatus.PAUSED
        self._log("session_pause", {})
        return self.state

    def resume(self) -> SessionState:
        if self.state.status != SessionStatus.PAUSED:
            raise ValueError("Only a paused session can be resumed.")
        if self.state.stop_reason:
            raise ValueError(self.state.stop_reason)
        self.state.paused = False
        self.state.status = SessionStatus.ACTIVE
        self._log("session_resume", {})
        return self.state

    def abort(self, reason: str = "Session aborted by user.") -> SessionState:
        self.state.paused = True
        self.state.status = SessionStatus.STOPPED
        self.state.stop_reason = reason
        self._log("session_abort", {"reason": reason})
        return self.state

    def record_hand(self, result: HandResult, bet: float) -> SessionState:
        if self.state.status not in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
            raise ValueError("Start a session before recording hands.")
        if self.state.status is SessionStatus.PAUSED:
            raise ValueError("Resume or end the session before recording another hand.")
        if self.state.stop_reason:
            raise ValueError(self.state.stop_reason)
        bet = _round_money(bet)
        if not math.isfinite(bet) or bet <= 0:
            raise ValueError("Bet amount must be a positive finite number.")
        if bet > self.state.bankroll + 1e-9:
            raise ValueError("Bet cannot exceed current bankroll.")
        delta = _result_delta(result, bet)
        self.state.bankroll = _round_money(self.state.bankroll + delta)
        self.state.hands_played += 1
        entry = {
            "result": result.value,
            "bet": bet,
            "delta": delta,
            "bankroll": self.state.bankroll,
        }
        self.state.history.append(entry)
        self._log("hand", entry)
        reason = check_risk_limits(self.state)
        if reason:
            self.state.stop_reason = reason
            self.state.paused = True
            self.state.status = SessionStatus.STOPPED
            self._log("session_limit", {"reason": reason})
        return self.state

    def advice_for(self, true_count: float) -> BetAdvice:
        if not self.state.is_betting_allowed:
            reason = self.state.stop_reason or f"Session is {self.state.status.value}; betting advice paused."
            return BetAdvice(0, 0.0, True, reason, False)
        return suggest_bet(true_count, self.state.config, self.state.bankroll)

    def _log(self, event: str, payload: dict[str, Any]) -> None:
        if self.log_path is None:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **payload,
        }
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            # Logging must never crash a live session.
            return


def config_to_dict(config: SessionConfig) -> dict[str, Any]:
    data = asdict(config)
    data["mode"] = config.mode.value
    return data


def config_from_dict(data: dict[str, Any]) -> SessionConfig:
    mode = data.get("mode", SessionMode.PRACTICE.value)
    if isinstance(mode, SessionMode):
        mode_value = mode
    else:
        mode_value = SessionMode(str(mode))
    return SessionConfig(
        starting_bankroll=float(data.get("starting_bankroll", 200)),
        unit_size=float(data.get("unit_size", 5)),
        max_units=int(data.get("max_units", 4)),
        stop_loss=float(data.get("stop_loss", 50)),
        take_profit=float(data.get("take_profit", 50)),
        mode=mode_value,
        table_min=float(data.get("table_min", 5)),
        table_max=float(data.get("table_max", 500)),
    )


def load_config_file(path: Path) -> SessionConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Session config must be a JSON object.")
    return config_from_dict(data)
