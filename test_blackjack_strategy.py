import pytest

from blackjack_strategy import Rules, hand_value, recommend


DEALERS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "A")
ACTIONS = {"H": "Hit", "S": "Stand", "D": "Double", "P": "Split"}

# Independent S17, DAS, no-surrender table fixtures (dealer 2 through ace).
TABLE = [
    (["2", "3"], "HHHHHHHHHH"), (["2", "6"], "HHHHHHHHHH"),
    (["2", "7"], "HDDDDHHHHH"), (["3", "7"], "DDDDDDDDHH"),
    (["2", "9"], "DDDDDDDDDH"), (["10", "2"], "HHSSSHHHHH"),
    (["10", "3"], "SSSSSHHHHH"), (["10", "4"], "SSSSSHHHHH"),
    (["10", "5"], "SSSSSHHHHH"), (["10", "6"], "SSSSSHHHHH"),
    (["10", "7"], "SSSSSSSSSS"), (["10", "8"], "SSSSSSSSSS"),
    (["10", "9"], "SSSSSSSSSS"), (["J", "K"], "SSSSSSSSSS"),
    (["A", "2"], "HHHDDHHHHH"), (["A", "3"], "HHHDDHHHHH"),
    (["A", "4"], "HHDDDHHHHH"), (["A", "5"], "HHDDDHHHHH"),
    (["A", "6"], "HDDDDHHHHH"), (["A", "7"], "SDDDDSSHHH"),
    (["A", "8"], "SSSSSSSSSS"), (["A", "9"], "SSSSSSSSSS"),
    (["2", "2"], "PPPPPPHHHH"), (["3", "3"], "PPPPPPHHHH"),
    (["4", "4"], "HHHPPHHHHH"), (["5", "5"], "DDDDDDDDHH"),
    (["6", "6"], "PPPPPHHHHH"), (["7", "7"], "PPPPPPHHHH"),
    (["8", "8"], "PPPPPPPPPP"), (["9", "9"], "PPPPPSPPSS"),
    (["10", "10"], "SSSSSSSSSS"), (["A", "A"], "PPPPPPPPPP"),
]


@pytest.mark.parametrize("cards,dealer,expected", [
    (cards, dealer, ACTIONS[action]) for cards, row in TABLE for dealer, action in zip(DEALERS, row)
])
def test_s17_reference_table(cards, dealer, expected):
    assert recommend(cards, dealer).action == expected


@pytest.mark.parametrize("cards,dealer,expected", [
    (["5", "6"], "A", "Double"), (["A", "7"], "2", "Double"),
    (["A", "8"], "6", "Double"), (["10", "5"], "A", "Surrender"),
    (["8", "8"], "A", "Surrender"), (["10", "7"], "A", "Surrender"),
])
def test_h17_rule_changes(cards, dealer, expected):
    assert recommend(cards, dealer, Rules(hit_soft_17=True, late_surrender=True)).action == expected


@pytest.mark.parametrize("rank,dealer,expected", [
    ("2", "2", "Hit"), ("3", "3", "Hit"), ("4", "5", "Hit"),
    ("6", "2", "Hit"), ("6", "3", "Split"), ("8", "10", "Split"),
])
def test_no_double_after_split_changes_pairs(rank, dealer, expected):
    assert recommend([rank, rank], dealer, Rules(double_after_split=False)).action == expected


@pytest.mark.parametrize("cards,dealer,options,expected", [
    (["A", "7"], "6", {"can_double": False}, "Stand"),
    (["5", "6"], "6", {"can_double": False}, "Hit"),
    (["8", "8"], "10", {"can_split": False}, "Hit"),
    (["8", "8"], "6", {"can_split": False}, "Stand"),
    (["A", "7"], "9", {}, "Hit"),
    (["2", "3", "6"], "6", {}, "Hit"),
    (["A", "2", "5"], "6", {}, "Stand"),
    (["A", "10"], "9", {}, "Blackjack"),
    (["A", "10"], "9", {"after_split": True}, "Stand"),
    (["10", "6", "9"], "9", {}, "Bust"),
    (["A", "3"], "6", {"after_split": True, "split_aces": True}, "Stand"),
    (["A", "A"], "6", {"after_split": True, "split_aces": True, "can_split": False}, "Stand"),
])
def test_hand_state_and_unavailable_actions(cards, dealer, options, expected):
    assert recommend(cards, dealer, **options).action == expected


def test_surrender_and_split_restrictions():
    rules = Rules(late_surrender=True)
    assert recommend(["10", "6"], "10", rules).action == "Surrender"
    assert recommend(["8", "8"], "10", rules).action == "Split"
    assert recommend(["8", "8"], "10", rules, can_split=False).action == "Surrender"
    assert recommend(["10", "6"], "10", rules, after_split=True).action == "Hit"
    assert recommend(["10", "6"], "10", rules, can_surrender=False).action == "Hit"
    assert recommend(["5", "6"], "6", Rules(double_after_split=False), after_split=True).action == "Hit"


def test_ace_values_and_rejected_inputs():
    assert hand_value(["A", "A", "9"]) == (21, True)
    assert hand_value(["A", "9", "5"]) == (15, False)
    for cards, dealer, rules in [(["A"], "7", Rules()), (["0", "7"], "7", Rules()),
                                 (["5", "6"], "1", Rules()), (["5", "6"], "A", Rules(decks=1)),
                                 (["5", "6"], "A", Rules(dealer_peeks=False))]:
        with pytest.raises(ValueError):
            recommend(cards, dealer, rules)
