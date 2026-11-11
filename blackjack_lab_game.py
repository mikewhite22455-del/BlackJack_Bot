"""Offline infinite-deck blackjack, with no casino or screen connection.

Default main-game rules match Shuffle's published May 14, 2026 rules.
Insurance and side bets are excluded. All returns are net initial-bet units.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import NamedTuple


CARDS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10)
PROBABILITIES = tuple((rank, CARDS.count(rank) / 13) for rank in range(1, 11))
ACTIONS = ("Stand", "Hit", "Double", "Split")


@dataclass(frozen=True)
class LabRules:
    blackjack_payout: float = 1.5
    hit_soft_17: bool = False
    double_after_split: bool = True

    def __post_init__(self):
        if self.blackjack_payout not in (1.2, 1.5):
            raise ValueError("Supported natural payouts are 3:2 and 6:5.")
        if type(self.hit_soft_17) is not bool or type(self.double_after_split) is not bool:
            raise ValueError("Rule switches must be booleans.")


class State(NamedTuple):
    total: int
    soft: bool
    dealer: int
    pair: int
    double: bool
    split: bool


class Transition(NamedTuple):
    reward: float
    children: tuple


def add_card(total, soft, rank):
    if rank == 1:
        if total + 11 <= 21:
            return total + 11, True
        total += 1
    else:
        total += rank
    if total > 21 and soft:
        return total - 10, False
    return total, soft


def new_hand(first, second, dealer, *, split=True, double=True):
    total, soft = add_card(*add_card(0, False, first), second)
    pair = first if first == second and split else 0
    return State(total, soft, dealer, pair, double, bool(pair))


def hit_state(state, card):
    total, soft = add_card(state.total, state.soft, card)
    return State(total, soft, state.dealer, 0, False, False)


@lru_cache(maxsize=None)
def legal_actions(state):
    if state.total > 21:
        return ()
    if state.total == 21:
        return ("Stand",)
    actions = ["Stand", "Hit"]
    if state.double:
        actions.append("Double")
    if state.split and state.pair:
        actions.append("Split")
    return tuple(actions)


def natural(first, second):
    return {first, second} == {1, 10}


def natural_probability(upcard):
    return {1: 4 / 13, 10: 1 / 13}.get(upcard, 0.0)


def hole_cards(upcard):
    """Condition on the completed American dealer peek: no dealer blackjack."""
    return tuple(card for card in CARDS if not natural(upcard, card))


def dealer_hits(total, soft, rules):
    return total < 17 or (total == 17 and soft and rules.hit_soft_17)


def finish_dealer(upcard, hole, rng, rules):
    total, soft = add_card(*add_card(0, False, upcard), hole)
    while dealer_hits(total, soft, rules):
        total, soft = add_card(total, soft, rng.choice(CARDS))
    return total


def settle(total, dealer_total):
    if total > 21:
        return -1.0
    if dealer_total > 21 or total > dealer_total:
        return 1.0
    return 0.0 if total == dealer_total else -1.0


class World:
    """Private dealer outcome; policies are passed only a public State."""

    def __init__(self, rng, dealer_total, rules):
        self.rng = rng
        self.dealer_total = dealer_total
        self.rules = rules

    def step(self, state, action):
        if action not in legal_actions(state):
            raise ValueError(f"Illegal action {action} for {state}")
        if action == "Stand":
            return Transition(settle(state.total, self.dealer_total), ())
        if action == "Split":
            return self._split(state)
        child = hit_state(state, self.rng.choice(CARDS))
        if action == "Double":
            return Transition(2 * settle(child.total, self.dealer_total), ())
        if child.total > 21:
            return Transition(-1.0, ())
        return Transition(0.0, (child,))

    def _split(self, state):
        children = tuple(new_hand(state.pair, self.rng.choice(CARDS), state.dealer,
                                  split=False, double=self.rules.double_after_split) for _ in range(2))
        if state.pair == 1:
            # Split aces get exactly one card each; a split 21 pays even money.
            return Transition(sum(settle(child.total, self.dealer_total) for child in children), ())
        return Transition(0.0, children)


def play_hand(state, world, policy):
    pending, result = [state], 0.0
    while pending:
        current = pending.pop()
        transition = world.step(current, policy(current))
        result += transition.reward
        pending.extend(reversed(transition.children))
    return result


def play_round(policy, rng, rules):
    first, upcard, second, hole = (rng.choice(CARDS) for _ in range(4))
    player_natural, dealer_natural = natural(first, second), natural(upcard, hole)
    if dealer_natural:
        return 0.0 if player_natural else -1.0
    if player_natural:
        return rules.blackjack_payout
    dealer_total = finish_dealer(upcard, hole, rng, rules)
    return play_hand(new_hand(first, second, upcard), World(rng, dealer_total, rules), policy)


def decision_starts(rules):
    """Reachable abstract states, including no-resplit hands; no hidden cards."""
    states = set()
    for dealer in range(1, 11):
        for first in range(1, 11):
            for second in range(1, 11):
                if not natural(first, second):
                    states.add(new_hand(first, second, dealer))
                states.add(new_hand(first, second, dealer, split=False, double=rules.double_after_split))
        for total in range(6, 22):
            states.add(State(total, False, dealer, 0, False, False))
        for total in range(13, 22):
            states.add(State(total, True, dealer, 0, False, False))
    return tuple(sorted(state for state in states if state.total < 21))


class ExactEvaluator:
    """Enumerates all card probabilities: optimal or a fixed supplied policy.

    This is separate from sampled training and never supplies Q-learning labels.
    Split hands share a dealer in simulation; expectation adds their values.
    """

    def __init__(self, rules, policy=None):
        self.rules = rules
        self.policy = policy
        self.dealer_distribution = lru_cache(None)(self._dealer_distribution)
        self.dealer_tail = lru_cache(None)(self._dealer_tail)
        self.values = lru_cache(None)(self._values)
        self.value = lru_cache(None)(self._value)

    def _dealer_tail(self, total, soft):
        if not dealer_hits(total, soft, self.rules):
            return ((min(total, 22), 1.0),)
        outcomes = {}
        for card, probability in PROBABILITIES:
            for outcome, chance in self.dealer_tail(*add_card(total, soft, card)):
                outcomes[outcome] = outcomes.get(outcome, 0.0) + probability * chance
        return tuple(outcomes.items())

    def _dealer_distribution(self, upcard):
        outcomes, holes = {}, hole_cards(upcard)
        for hole in holes:
            total, soft = add_card(*add_card(0, False, upcard), hole)
            for outcome, chance in self.dealer_tail(total, soft):
                outcomes[outcome] = outcomes.get(outcome, 0.0) + chance / len(holes)
        return tuple(outcomes.items())

    def stand_value(self, total, dealer):
        return sum(chance * settle(total, outcome) for outcome, chance in self.dealer_distribution(dealer))

    def _values(self, state):
        values = {"Stand": self.stand_value(state.total, state.dealer)}
        if state.total == 21:
            return values
        values["Hit"] = sum(prob * self.value(hit_state(state, card)) for card, prob in PROBABILITIES)
        if state.double:
            values["Double"] = 2 * sum(prob * self.stand_value(hit_state(state, card).total, state.dealer)
                                       for card, prob in PROBABILITIES)
        if state.split:
            values["Split"] = self._split_value(state)
        return values

    def _split_value(self, state):
        result = 0.0
        for card, prob in PROBABILITIES:
            child = new_hand(state.pair, card, state.dealer, split=False, double=self.rules.double_after_split)
            value = self.stand_value(child.total, state.dealer) if state.pair == 1 else self.value(child)
            result += 2 * prob * value
        return result

    def _value(self, state):
        if state.total > 21:
            return -1.0
        values = self.values(state)
        return values[self.policy(state)] if self.policy else max(values.values())

    def action(self, state):
        values = self.values(state)
        return max(legal_actions(state), key=values.__getitem__)

    def initial_return(self):
        result = 0.0
        for first, p1 in PROBABILITIES:
            for second, p2 in PROBABILITIES:
                for upcard, p3 in PROBABILITIES:
                    blackjack = natural_probability(upcard)
                    value = self.rules.blackjack_payout if natural(first, second) else self.value(
                        new_hand(first, second, upcard))
                    loss = 0.0 if natural(first, second) else blackjack
                    result += p1 * p2 * p3 * ((1 - blackjack) * value - loss)
        return result
