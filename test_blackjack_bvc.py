import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from blackjack_bvc import BVC_RULES, EXPECTED, SNAPSHOT, NoRedirect, fetch_ruleset, recommend_bvc, validate_ruleset
from blackjack_strategy import Rules, recommend
from test_blackjack_strategy import ACTIONS, DEALERS, TABLE


@pytest.mark.parametrize("cards,dealer,expected", [
    (cards, dealer, ACTIONS[action]) for cards, row in TABLE for dealer, action in zip(DEALERS, row)
])
def test_no_peek_table_against_published_adjustments(cards, dealer, expected):
    # Reference: wizardofodds.com/ask-the-wizard/blackjack/no-peek/
    if (cards == ["2", "9"] and dealer == "10"
            or cards == ["8", "8"] and dealer in ("10", "A")
            or cards == ["A", "A"] and dealer == "A"):
        expected = "Hit"
    assert recommend_bvc(cards, dealer).action == expected


def test_split_budget_and_forced_split_ace_stand():
    assert recommend_bvc(["8", "8"], "6", splits_used=2, after_split=True).action == "Split"
    assert recommend_bvc(["8", "8"], "6", splits_used=3, after_split=True).action == "Stand"
    assert recommend_bvc(["A", "A"], "10", splits_used=1, after_split=True, split_aces=True).action == "Split"
    assert recommend_bvc(["A", "A"], "A", splits_used=1, after_split=True, split_aces=True).action == "Stand"
    assert recommend_bvc(["A", "A"], "6", splits_used=3, after_split=True, split_aces=True).action == "Stand"
    assert recommend_bvc(["A", "3"], "6", splits_used=1, after_split=True, split_aces=True).action == "Stand"
    assert recommend_bvc(["A", "10"], "6", splits_used=1, after_split=True, split_aces=True).action == "Stand"


@pytest.mark.parametrize("options", [
    {"splits_used": -1}, {"splits_used": 4}, {"splits_used": True},
    {"splits_used": 1}, {"after_split": True},
    {"splits_used": 1, "after_split": True, "split_aces": True},
])
def test_inconsistent_hand_state_is_rejected(options):
    with pytest.raises(ValueError):
        recommend_bvc(["8", "8"], "6", **options)


def test_available_actions_and_no_stale_double():
    assert recommend_bvc(["5", "6"], "6", can_double=False).action == "Hit"
    assert recommend_bvc(["8", "8"], "6", can_split=False).action == "Stand"
    assert recommend_bvc(["2", "3", "6"], "6").action == "Hit"


def test_current_rules_snapshot():
    assert validate_ruleset(json.loads(SNAPSHOT.read_text())) == BVC_RULES


@pytest.mark.parametrize("key", EXPECTED)
def test_changed_or_missing_rules_block_compatibility(key):
    payload = json.loads(SNAPSHOT.read_text())
    del payload["result"][key]
    with pytest.raises(ValueError, match=key):
        validate_ruleset(payload)
    payload["result"][key] = "changed"
    with pytest.raises(ValueError, match=key):
        validate_ruleset(payload)


def test_peek_obo_and_malformed_rules_cannot_silently_change_strategy():
    payload = json.loads(SNAPSHOT.read_text())
    for key in ("dealer_peeks", "loses_only_original_bet_on_dealer_blackjack"):
        changed = deepcopy(payload)
        changed["result"][key] = True
        with pytest.raises(ValueError):
            validate_ruleset(changed)
    for bad in (None, [], {}, {"result": {}}, {"result": payload["result"], "error": "offline"}):
        with pytest.raises(ValueError):
            validate_ruleset(bad)
    for rules in (Rules(dealer_peeks=False), Rules(dealer_peeks=False, no_peek_loses_all_bets=True, hit_soft_17=True),
                  Rules(dealer_peeks=False, no_peek_loses_all_bets=True, late_surrender=True)):
        with pytest.raises(ValueError):
            recommend(["5", "6"], "10", rules)


def test_fetch_only_calls_public_rules_url():
    with patch("blackjack_bvc.build_opener") as opener:
        opener.return_value.open.return_value.__enter__.return_value.read.return_value = SNAPSHOT.read_bytes()
        assert validate_ruleset(fetch_ruleset()) == BVC_RULES
        opener.return_value.open.assert_called_once_with("https://bitcoinvideocasino.com/blackjack/ruleset", timeout=10)


def test_redirect_is_rejected():
    with pytest.raises(ValueError, match="redirected"):
        NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://example.com")
