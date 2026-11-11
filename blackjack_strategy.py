"""Total-dependent basic strategy for 4-8 deck, American peek blackjack.

Reference: https://wizardofodds.com/games/blackjack/strategy/4-decks/
Supports S17/H17, DAS/no DAS and late surrender. No count deviations.
Double is assumed to be allowed on any first two cards when available.
"""

from dataclasses import dataclass


RANKS = tuple("23456789") + ("10", "J", "Q", "K", "A")


@dataclass(frozen=True)
class Rules:
    hit_soft_17: bool = False
    double_after_split: bool = True
    late_surrender: bool = False
    decks: int = 6
    dealer_peeks: bool = True


@dataclass(frozen=True)
class Decision:
    action: str
    total: int
    soft: bool
    reason: str


def rank_value(rank):
    if rank not in RANKS:
        raise ValueError(f"Invalid card rank: {rank}")
    if rank == "A":
        return 11
    return 10 if rank in ("10", "J", "Q", "K") else int(rank)


def hand_value(cards):
    if not cards:
        raise ValueError("Enter the player's cards.")
    total = sum(rank_value(card) for card in cards)
    aces = cards.count("A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def surrender_hand(total, pair, dealer, rules):
    if rules.hit_soft_17 and dealer == 11 and total in (15, 16, 17):
        return True
    return (total == 16 and pair != 8 and dealer in (9, 10, 11)) or (total == 15 and dealer == 10)


def split_pair(pair, dealer, das):
    split_dealers = {
        2: range(2 if das else 4, 8),
        3: range(2 if das else 4, 8),
        4: (5, 6) if das else (),
        6: range(2 if das else 3, 7),
        7: range(2, 8),
        9: (2, 3, 4, 5, 6, 8, 9),
    }
    return pair in (8, 11) or dealer in split_dealers.get(pair, ())


def soft_action(total, dealer, h17, double):
    double_dealers = {
        13: (5, 6), 14: (5, 6), 15: (4, 5, 6), 16: (4, 5, 6),
        17: (3, 4, 5, 6), 18: (2, 3, 4, 5, 6) if h17 else (3, 4, 5, 6),
        19: (6,) if h17 else (),
    }
    if double and dealer in double_dealers.get(total, ()):
        return "Double"
    if total >= 19 or (total == 18 and dealer in (2, 3, 4, 5, 6, 7, 8)):
        return "Stand"
    return "Hit"


def hard_action(total, dealer, h17, double):
    double_dealers = {
        9: (3, 4, 5, 6),
        10: tuple(range(2, 10)),
        11: tuple(range(2, 12 if h17 else 11)),
    }
    if double and dealer in double_dealers.get(total, ()):
        return "Double"
    if total >= 17 or (total == 12 and dealer in (4, 5, 6)):
        return "Stand"
    if 13 <= total <= 16 and dealer in (2, 3, 4, 5, 6):
        return "Stand"
    return "Hit"


def terminal_decision(cards, total, soft, after_split):
    if total > 21:
        return Decision("Bust", total, soft, "The hand is over 21.")
    if total == 21:
        action = "Blackjack" if len(cards) == 2 and not after_split else "Stand"
        return Decision(action, total, soft, "The hand totals 21.")
    return None


def recommend(cards, dealer_card, rules=None, *, can_double=True, can_split=True,
              can_surrender=True, after_split=False, split_aces=False):
    rules = rules or Rules()
    if rules.decks not in (4, 5, 6, 7, 8) or not rules.dealer_peeks:
        raise ValueError("Supported rules: 4-8 decks with American dealer peek.")
    cards = list(cards)
    if len(cards) < 2:
        raise ValueError("Enter at least two player cards.")
    dealer = rank_value(dealer_card)
    total, soft = hand_value(cards)
    terminal = terminal_decision(cards, total, soft, after_split)
    if terminal is not None:
        return terminal
    pair = rank_value(cards[0]) if len(cards) == 2 and cards[0] == cards[1] else None
    if split_aces:
        if not after_split:
            raise ValueError("Split-ace restrictions require a hand that came from a split.")
        if pair == 11 and can_split:
            return Decision("Split", total, soft, "Resplit aces only if the table allows it.")
        return Decision("Stand", total, soft, "Split aces are limited to one additional card.")
    if rules.late_surrender and can_surrender and len(cards) == 2 and not after_split and not soft:
        if surrender_hand(total, pair if can_split else None, dealer, rules):
            return Decision("Surrender", total, soft, "Late surrender after the dealer's blackjack check.")
    if pair and can_split and split_pair(pair, dealer, rules.double_after_split):
        return Decision("Split", total, soft, "Pair strategy for the selected table rules.")
    double = can_double and len(cards) == 2 and (not after_split or rules.double_after_split)
    action = soft_action(total, dealer, rules.hit_soft_17, double) if soft else hard_action(
        total, dealer, rules.hit_soft_17, double
    )
    return Decision(action, total, soft, "Basic strategy for the selected rules and available actions.")
