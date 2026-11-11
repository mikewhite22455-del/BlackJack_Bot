"""Casino Time / Pragmatic VIP Blackjack research model. No network access.

Eight physical decks are sampled without replacement. Unknown table details
are scenario parameters, not asserted facts about a production table.
"""

from collections import Counter
from dataclasses import dataclass, field
import math
import random

from blackjack_strategy import Rules, hand_value, rank_value, recommend


SOURCE_URL = "https://www.casinotime.ca/blog/how-to-play-vip-blackjack-by-pragmatic-play"
PROFILE = "Casino Time - Pragmatic Play VIP Blackjack"
RANKS = tuple("23456789") + ("10", "J", "Q", "K", "A")
SUITS = ("C", "D", "H", "S")
HI_LO = {rank: (1 if rank in "23456" else -1 if rank in ("10", "J", "Q", "K", "A") else 0)
         for rank in RANKS}
TEN_RULES = ("peek", "no_peek_all_bets")


@dataclass(frozen=True)
class Scenario:
    """Only unknown operational details are configurable; published rules fixed."""

    dealer_ten: str
    cut_cards: int
    seats: int = 1
    burn_cards: int = 0

    def __post_init__(self):
        if self.dealer_ten not in TEN_RULES:
            raise ValueError("Choose a dealer-ten scenario: peek or no_peek_all_bets.")
        for name, low, high in (("cut_cards", 52, 312), ("seats", 1, 7), ("burn_cards", 0, 10)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}.")


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str
    identity: str

    def __post_init__(self):
        if self.rank not in RANKS or self.suit not in SUITS or not self.identity:
            raise ValueError("Invalid card.")

    def label(self):
        return self.rank + {"C": "♣", "D": "♦", "H": "♥", "S": "♠"}[self.suit]


class ShoeLedger:
    """Public evidence only. A physical-card identity survives movement/splits.

    A hidden burn or hole card has identity but no rank. Unseen composition
    includes those cards; its marginal draw probabilities never invent ranks.
    """

    def __init__(self, shoe_id):
        if not isinstance(shoe_id, str) or not shoe_id:
            raise ValueError("A shoe identifier is required.")
        self.shoe_id = shoe_id
        self.cards = {}
        self._exposed = Counter()
        self.events = []
        self.valid = True
        self.issue = ""

    def observe(self, identity, rank=None):
        if not self.valid:
            raise ValueError("Shoe has an observation gap; start a verified new shoe.")
        if not isinstance(identity, str) or not identity or (rank is not None and rank not in RANKS):
            raise ValueError("A card identity and valid rank (or null) are required.")
        if identity in self.cards:
            return self._reveal(identity, rank)
        if len(self.cards) >= 416:
            raise ValueError("An eight-deck shoe cannot contain more than 416 cards.")
        self._check_rank(rank)
        self.cards[identity] = rank
        if rank is not None:
            self._exposed[rank] += 1
        self.events.append({"type": "card", "id": identity, "rank": rank})
        return True

    def _check_rank(self, rank):
        if rank is not None and self._exposed[rank] >= 32:
            raise ValueError(f"More than 32 exposed {rank} cards in an eight-deck shoe.")

    def _reveal(self, identity, rank):
        old = self.cards[identity]
        if rank is None or rank == old:
            return False
        if old is not None:
            raise ValueError("Conflicting rank for the same physical card; review the evidence.")
        self._check_rank(rank)
        self.cards[identity] = rank
        self._exposed[rank] += 1
        self.events.append({"type": "reveal", "id": identity, "rank": rank})
        return True

    def mark_gap(self, reason):
        self.valid = False
        self.issue = str(reason) or "Missing card observations"
        self.events.append({"type": "gap", "reason": self.issue})

    @property
    def unseen(self):
        return {rank: 32 - self._exposed[rank] for rank in RANKS}

    @property
    def unknown_removed(self):
        return sum(rank is None for rank in self.cards.values())

    @property
    def running_count(self):
        return sum(HI_LO[rank] * count for rank, count in self._exposed.items())

    @property
    def physical_remaining(self):
        return 416 - len(self.cards)

    @property
    def true_count_estimate(self):
        return self.running_count / (self.physical_remaining / 52) if self.physical_remaining else None

    def probabilities(self, excluded_hole=()):
        """Exact next-card marginal under a uniformly shuffled shoe model.

        excluded_hole conditions ONE hidden dealer card after a negative peek.
        Other unknown removed cards are integrated out by exchangeability.
        """
        if not self.valid or self.physical_remaining == 0:
            raise ValueError("No trustworthy remaining-shoe distribution.")
        counts = self.unseen
        total = sum(counts.values())
        if not excluded_hole:
            return {rank: count / total for rank, count in counts.items()}
        if self.unknown_removed < 1 or any(rank not in RANKS for rank in excluded_hole):
            raise ValueError("A peek condition requires a hidden card and valid excluded ranks.")
        eligible = sum(count for rank, count in counts.items() if rank not in excluded_hole)
        if eligible == 0 or total <= 1:
            raise ValueError("Impossible negative-peek evidence.")
        return {rank: (count - (count / eligible if rank not in excluded_hole else 0)) / (total - 1)
                for rank, count in counts.items()}

    def export(self):
        return {"schema": 1, "profile": PROFILE, "shoe_id": self.shoe_id, "events": list(self.events)}

    @classmethod
    def replay(cls, payload):
        if not isinstance(payload, dict) or payload.get("schema") != 1 or payload.get("profile") != PROFILE:
            raise ValueError("Unsupported shoe-log format or profile.")
        events = payload.get("events")
        if not isinstance(events, list) or len(events) > 1000:
            raise ValueError("Invalid or oversized shoe event log.")
        ledger = cls(payload.get("shoe_id"))
        for event in events:
            ledger._replay_event(event)
        return ledger

    def _replay_event(self, event):
        if not isinstance(event, dict):
            raise ValueError("Invalid event.")
        kind = event.get("type")
        if kind == "gap":
            self.mark_gap(event.get("reason", ""))
        elif kind in ("card", "reveal"):
            if kind == "reveal" and event.get("id") not in self.cards:
                raise ValueError("Cannot reveal a card that was never recorded.")
            self.observe(event.get("id"), event.get("rank"))
        else:
            raise ValueError("Unknown shoe event type.")


class EightDeckShoe:
    def __init__(self, seed, scenario):
        self.rng = random.Random(seed)
        self.scenario = scenario
        self.number = 0
        self.history = []
        self.new_shoe("initial")

    def new_shoe(self, reason):
        if self.number:
            self.history.append({"shoe": self.number, "cards_dealt": self.position, "reason": reason})
        self.number += 1
        self.cards = [Card(rank, suit, "not-visible")
                      for _ in range(8) for rank in RANKS for suit in SUITS]
        self.rng.shuffle(self.cards)
        # Identities describe positions in this shuffled shoe, never card ranks.
        self.cards = [Card(card.rank, card.suit, f"{self.number}:{i}") for i, card in enumerate(self.cards)]
        self.position = 0
        self.ledger = ShoeLedger(str(self.number))
        for _ in range(self.scenario.burn_cards):
            self.draw(exposed=False)

    @property
    def cut_reached(self):
        return self.position >= self.scenario.cut_cards

    def draw(self, exposed=True):
        if self.position >= len(self.cards):
            raise ValueError("Shoe exhausted mid-round; scenario cannot be continued.")
        card = self.cards[self.position]
        self.position += 1
        self.ledger.observe(card.identity, card.rank if exposed else None)
        return card


@dataclass
class Hand:
    cards: list = field(default_factory=list)
    bet: float = 1.0
    after_split: bool = False
    split_aces: bool = False
    done: bool = False
    profit: float = 0.0

    @property
    def ranks(self):
        return [card.rank for card in self.cards]

    @property
    def total(self):
        return hand_value(self.ranks)[0]

    @property
    def natural(self):
        return len(self.cards) == 2 and self.total == 21 and not self.after_split


def side_bets(player, upcard):
    """Net win multipliers for the published PP and 21+3 paytables; -1 loses."""
    first, second = player
    pairs = -1
    if first.rank == second.rank:
        same_color = (first.suit in ("D", "H")) == (second.suit in ("D", "H"))
        pairs = 25 if first.suit == second.suit else 12 if same_color else 6
    cards = [first, second, upcard]
    ranks = sorted(14 if c.rank == "A" else {"J": 11, "Q": 12, "K": 13}.get(c.rank, int(c.rank)
                   if c.rank.isdigit() else 0) for c in cards)
    flush = len({c.suit for c in cards}) == 1
    trips = len(set(ranks)) == 1
    straight = ranks == [2, 3, 14] or (len(set(ranks)) == 3 and ranks[-1] - ranks[0] == 2)
    outcomes = ((trips and flush, 100), (straight and flush, 40), (trips, 30), (straight, 10), (flush, 5))
    return {"Perfect Pairs": pairs, "21+3": next((pay for match, pay in outcomes if match), -1)}


class Table:
    """Whole-table simulator: all occupied seats share one physical dealer hand."""

    def __init__(self, scenario, seed=1):
        self.scenario = scenario
        self.shoe = EightDeckShoe(seed, scenario)
        self.round_number = 0
        self.phase = "ready"
        self.seats = []
        self.dealer = []
        self.insurance = []
        self.peek_negative = False
        self.active = None

    def start(self, bets=None):
        if self.phase not in ("ready", "settled"):
            raise ValueError("Finish the current round first.")
        bets = [1.0] * self.scenario.seats if bets is None else list(bets)
        if len(bets) != self.scenario.seats or any(
                isinstance(b, bool) or not isinstance(b, (int, float)) or not math.isfinite(b) or b <= 0 for b in bets):
            raise ValueError("Supply one positive finite opening bet per occupied seat.")
        if self.shoe.cut_reached:
            self.shoe.new_shoe("cut card / completed round")
        self.round_number += 1
        self.seats = [[Hand(bet=float(bet))] for bet in bets]
        self.insurance = [0.0] * len(bets)
        self.peek_negative = False
        self.active = None
        for seat in self.seats:
            seat[0].cards.append(self.shoe.draw())
        self.dealer = [self.shoe.draw()]
        for seat in self.seats:
            seat[0].cards.append(self.shoe.draw())
            seat[0].done = seat[0].natural
        self.dealer.append(self.shoe.draw(exposed=False))
        if self.dealer[0].rank == "A":
            self.phase = "insurance"
        elif rank_value(self.dealer[0].rank) == 10 and self.scenario.dealer_ten == "peek":
            self._peek()
        else:
            self._advance()

    def insure(self, choices):
        if self.phase != "insurance" or len(choices) != len(self.seats) or any(type(x) is not bool for x in choices):
            raise ValueError("Supply one insurance yes/no choice per seat during the insurance phase.")
        self.insurance = [seat[0].bet / 2 if yes else 0 for yes, seat in zip(choices, self.seats)]
        self._peek()

    def _peek(self):
        if self.dealer_blackjack:
            self._settle()
        else:
            self.peek_negative = True
            self._advance()

    @property
    def dealer_blackjack(self):
        return len(self.dealer) == 2 and hand_value([c.rank for c in self.dealer])[0] == 21

    @property
    def current_hand(self):
        if self.phase != "player" or self.active is None:
            raise ValueError("No active player hand.")
        seat, hand = self.active
        return self.seats[seat][hand]

    def legal_actions(self):
        if self.phase != "player":
            return ()
        hand = self.current_hand
        actions = ["Hit", "Stand"]
        if len(hand.cards) == 2 and not hand.split_aces:
            actions.append("Double")
            if not hand.after_split and rank_value(hand.cards[0].rank) == rank_value(hand.cards[1].rank):
                actions.append("Split")
        return tuple(actions)

    def act(self, action):
        if action not in self.legal_actions():
            raise ValueError("Action is not available for this hand.")
        hand = self.current_hand
        if action == "Split":
            self._split()
        elif action == "Stand":
            hand.done = True
        else:
            hand.cards.append(self.shoe.draw())
            if action == "Double":
                hand.bet *= 2
            hand.done = action == "Double" or hand.total >= 21
        self._advance()

    def _split(self):
        seat, index = self.active
        hand = self.current_hand
        aces = hand.cards[0].rank == "A"
        hands = [Hand([card, self.shoe.draw()], hand.bet, True, aces) for card in hand.cards]
        for child in hands:
            child.done = aces or child.total >= 21
        self.seats[seat][index:index + 1] = hands

    def _advance(self):
        for i, seat in enumerate(self.seats):
            for j, hand in enumerate(seat):
                if not hand.done:
                    self.active = (i, j)
                    self.phase = "player"
                    return
        self._finish_dealer()

    def _finish_dealer(self):
        needs_total = any(not hand.natural and hand.total <= 21 for seat in self.seats for hand in seat)
        while needs_total and not self.dealer_blackjack and hand_value([c.rank for c in self.dealer])[0] < 17:
            self.dealer.append(self.shoe.draw())
        self._settle()

    def _settle(self):
        self.shoe.ledger.observe(self.dealer[1].identity, self.dealer[1].rank)
        total = hand_value([c.rank for c in self.dealer])[0]
        for seat in self.seats:
            for hand in seat:
                hand.profit = hand.bet * self._net_multiplier(hand, total)
                hand.done = True
        self.phase = "settled"
        self.active = None

    def _net_multiplier(self, hand, dealer_total):
        if hand.total > 21:
            return -1
        if self.dealer_blackjack:
            return 0 if hand.natural else -1
        if hand.natural:
            return 1.5
        if dealer_total > 21 or hand.total > dealer_total:
            return 1
        return 0 if hand.total == dealer_total else -1

    def profits(self):
        if self.phase != "settled":
            raise ValueError("The round is not settled.")
        return [sum(h.profit for h in seat) + insurance * (2 if self.dealer_blackjack else -1)
                for seat, insurance in zip(self.seats, self.insurance)]

    def basic_action(self):
        hand = self.current_hand
        no_peek = self.dealer[0].rank in ("10", "J", "Q", "K") and self.scenario.dealer_ten == "no_peek_all_bets"
        rules = Rules(decks=8, dealer_peeks=not no_peek, no_peek_loses_all_bets=no_peek)
        return recommend(hand.ranks, self.dealer[0].rank, rules,
                         can_double="Double" in self.legal_actions(), can_split="Split" in self.legal_actions(),
                         can_surrender=False, after_split=hand.after_split, split_aces=hand.split_aces).action

    def autoplay(self):
        while self.phase in ("insurance", "player"):
            if self.phase == "insurance":
                self.insure([False] * len(self.seats))
            else:
                self.act(self.basic_action())

    def new_shoe(self, reason="manual / early replacement"):
        if self.phase not in ("ready", "settled"):
            raise ValueError("A shoe replacement must wait until this round is completed.")
        self.shoe.new_shoe(reason)
        self.phase = "ready"
        self.seats = []
        self.dealer = []
        self.insurance = []
        self.peek_negative = False
        self.active = None

    def public_state(self):
        """Does not expose the dealer hole rank, shuffled order or RNG state."""
        dealer = [c.label() for c in self.dealer] if self.phase == "settled" else [
            self.dealer[0].label(), "Hidden"] if self.dealer else []
        return {"profile": PROFILE, "round": self.round_number, "shoe": self.shoe.number,
                "phase": self.phase, "active": self.active, "dealer": dealer,
                "seats": [[{"cards": [c.label() for c in h.cards], "total": h.total, "bet": h.bet,
                            "after_split": h.after_split, "profit": h.profit} for h in seat] for seat in self.seats],
                "running_count": self.shoe.ledger.running_count,
                "true_count_estimate": self.shoe.ledger.true_count_estimate,
                "unknown_removed": self.shoe.ledger.unknown_removed,
                "remaining": self.shoe.ledger.physical_remaining, "cut_reached": self.shoe.cut_reached}

    def next_card_probabilities(self):
        excluded = ()
        if self.peek_negative and self.phase != "settled":
            excluded = ("10", "J", "Q", "K") if self.dealer[0].rank == "A" else ("A",)
        return self.shoe.ledger.probabilities(excluded)


def recommend_casinotime(cards, dealer, *, dealer_ten=None, after_split=False, split_aces=False,
                         can_double=True, can_split=True):
    """Published VIP baseline; require the unresolved ten-upcard rule explicitly."""
    ten_up = dealer in ("10", "J", "Q", "K")
    if ten_up and dealer_ten not in TEN_RULES:
        raise ValueError("Confirm the dealer-ten peek and blackjack settlement rule first.")
    if split_aces and (not after_split or not cards or cards[0] != "A"):
        raise ValueError("Split aces must be an ace hand following a split.")
    no_peek = ten_up and dealer_ten == "no_peek_all_bets"
    rules = Rules(decks=8, dealer_peeks=not no_peek, no_peek_loses_all_bets=no_peek)
    return recommend(cards, dealer, rules, can_double=can_double, can_split=can_split and not after_split,
                     can_surrender=False, after_split=after_split, split_aces=split_aces)
