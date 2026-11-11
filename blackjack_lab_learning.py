"""Tabular Q-learning and frozen-policy evaluation, exclusively offline."""

import json
import math
import random
from dataclasses import asdict
from pathlib import Path

from blackjack_lab_game import (ACTIONS, ExactEvaluator, LabRules, State, World,
                                decision_starts, finish_dealer, hole_cards, legal_actions, play_round)
from blackjack_strategy import hard_action, soft_action, split_pair


def tuple_tree(value):
    return tuple(tuple_tree(item) for item in value) if isinstance(value, list) else value


class QLearner:
    def __init__(self, rules=None, seed=20261111):
        self.rules = rules or LabRules()
        self.seed = seed
        self.rng = random.Random(seed)
        self.choices = random.Random(seed + 1)
        self.q, self.visits = {}, {}
        self.episodes = 0

    def row(self, state):
        return self.q.setdefault(state, [0.0] * len(ACTIONS))

    def greedy(self, state):
        # Evaluation must not insert rows or change the training state.
        values = self.q.get(state, (0.0,) * len(ACTIONS))
        return max(legal_actions(state), key=lambda action: values[ACTIONS.index(action)])

    def best_value(self, state):
        return self.row(state)[ACTIONS.index(self.greedy(state))]

    def update(self, state, action, transition):
        index = ACTIONS.index(action)
        counts = self.visits.setdefault(state, [0] * len(ACTIONS))
        counts[index] += 1
        # gamma=1 for finite undiscounted money returns. Splits create two
        # children, whose expected net returns SUM rather than average.
        target = transition.reward + sum(self.best_value(child) for child in transition.children)
        # These ACTIONS always terminate, so their sample mean reduces variance.
        # Hit must use the same schedule on bust and non-bust transitions;
        # choosing alpha by sampled outcome would bias its learned value.
        stationary = action in ("Stand", "Double") or (action == "Split" and state.pair == 1)
        alpha = counts[index] ** (-1.0 if stationary else -0.6)
        values = self.row(state)
        values[index] += alpha * (target - values[index])

    def train(self, episodes, progress=None):
        if type(episodes) is not int or episodes < 0:
            raise ValueError("Training episodes must be a nonnegative integer.")
        starts = decision_starts(self.rules)
        for index in range(episodes):
            state = self.rng.choice(starts)
            hole = self.rng.choice(hole_cards(state.dealer))
            world = World(self.rng, finish_dealer(state.dealer, hole, self.rng, self.rules), self.rules)
            epsilon = max(0.05, 0.3 / math.sqrt(1 + self.episodes / 50000))
            self._episode(state, world, epsilon)
            self.episodes += 1
            if progress and (index + 1) % 100000 == 0:
                progress(self.episodes)

    def _episode(self, state, world, epsilon):
        pending = [state]
        first_action = True
        while pending:
            current = pending.pop()
            action = self.greedy(current)
            if first_action or self.choices.random() < epsilon:
                action = self.choices.choice(legal_actions(current))
            first_action = False
            transition = world.step(current, action)
            self.update(current, action, transition)
            pending.extend(reversed(transition.children))

    def save(self, path):
        data = {"format": "blackjack-offline-q-v1", "rules": asdict(self.rules), "seed": self.seed,
                "episodes": self.episodes, "rng": self.rng.getstate(), "choices": self.choices.getstate(),
                "rows": [{"state": list(state), "q": values, "visits": self.visits.get(state, [0] * 4)}
                         for state, values in sorted(self.q.items())]}
        Path(path).write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format") != "blackjack-offline-q-v1":
            raise ValueError("Unsupported checkpoint format.")
        model = cls(LabRules(**data["rules"]), data["seed"])
        model.episodes = data["episodes"]
        if type(model.episodes) is not int or model.episodes < 0:
            raise ValueError("Invalid training episode count.")
        valid_states = set(decision_starts(model.rules))
        valid_states.update(State(21, soft, dealer, 0, double, False)
                            for soft in (False, True) for dealer in range(1, 11) for double in (False, True))
        for row in data["rows"]:
            model._load_row(row, valid_states)
        model.rng.setstate(tuple_tree(data["rng"]))
        model.choices.setstate(tuple_tree(data["choices"]))
        return model

    def _load_row(self, row, valid_states):
        state = State(*row["state"])
        values, counts = row["q"], row["visits"]
        if state not in valid_states or state in self.q:
            raise ValueError("Invalid or duplicate checkpoint state.")
        if len(values) != 4 or not all(type(value) in (int, float) and math.isfinite(value) for value in values):
            raise ValueError("Invalid Q values.")
        if len(counts) != 4 or not all(type(count) is int and count >= 0 for count in counts):
            raise ValueError("Invalid action visit counts.")
        self.q[state], self.visits[state] = values, counts


def evaluate(policy, rules, rounds, seed, session_hands=100):
    if type(rounds) is not int or rounds < 2 or type(session_hands) is not int or session_hands < 1:
        raise ValueError("Use at least two evaluation rounds and a positive session length.")
    rng = random.Random(seed)
    total = squared = session_total = 0.0
    wins = losses = positive_sessions = complete_sessions = 0
    for index in range(rounds):
        result = play_round(policy, rng, rules)
        total += result
        squared += result * result
        wins += result > 0
        losses += result < 0
        session_total += result
        if (index + 1) % session_hands == 0:
            complete_sessions += 1
            positive_sessions += session_total > 0
            session_total = 0.0
    mean = total / rounds
    variance = max(0.0, (squared - total * total / rounds) / (rounds - 1))
    margin = 1.96 * math.sqrt(variance / rounds)
    return {"rounds": rounds, "seed": seed, "mean_net_units": mean,
            "mean_95_ci": [mean - margin, mean + margin], "win_rounds": wins,
            "loss_rounds": losses, "push_rounds": rounds - wins - losses,
            "session_hands": session_hands, "complete_sessions": complete_sessions,
            "positive_sessions": positive_sessions,
            "positive_session_fraction": positive_sessions / complete_sessions if complete_sessions else None}


def reference_policy(state, rules):
    """Existing multi-deck basic strategy, clearly separate from the IID oracle."""
    dealer = 11 if state.dealer == 1 else state.dealer
    pair = 11 if state.pair == 1 else state.pair
    if state.split and split_pair(pair, dealer, rules.double_after_split):
        return "Split"
    strategy = soft_action if state.soft else hard_action
    return strategy(state.total, dealer, rules.hit_soft_17, state.double)


def compare(model, rounds, seed, session_hands=100):
    optimal = ExactEvaluator(model.rules)
    learned = ExactEvaluator(model.rules, model.greedy)

    def reference(state):
        return reference_policy(state, model.rules)

    reference_ev = ExactEvaluator(model.rules, reference).initial_return()
    optimal_ev, learned_ev = optimal.initial_return(), learned.initial_return()
    states = decision_starts(model.rules)
    gaps = [max(optimal.values(state).values()) - optimal.values(state)[model.greedy(state)] for state in states]
    return {"rules": asdict(model.rules), "training_seed": model.seed, "training_episodes": model.episodes,
            "training_method": "Sampled Q-learning; uniform state-action starts; gamma=1; always-terminal actions alpha=1/n",
            "optimal_exact_net_units": optimal_ev, "learned_exact_net_units": learned_ev,
            "reference_exact_net_units": reference_ev,
            "learned_gap_units": optimal_ev - learned_ev,
            "decision_states": len(states), "near_optimal_states": sum(gap <= 0.001 for gap in gaps),
            "optimal": evaluate(optimal.action, model.rules, rounds, seed, session_hands),
            "learned": evaluate(model.greedy, model.rules, rounds, seed + 1, session_hands),
            "reference": evaluate(reference, model.rules, rounds, seed + 2, session_hands),
            "limitation": "Offline IID infinite-deck main game only. No casino connection or live-profit evidence."}
