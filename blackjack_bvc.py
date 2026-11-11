"""Bitcoin Video Casino rules profile and read-only compatibility check.

No account credentials, game actions, or wagering endpoints are implemented.
"""

import argparse
import json
from pathlib import Path
from urllib.request import HTTPRedirectHandler, build_opener

from blackjack_strategy import Rules, recommend


RULESET_URL = "https://bitcoinvideocasino.com/blackjack/ruleset"
SNAPSHOT = Path(__file__).parent / "fixtures" / "bvc-rules-2026-11-11.json"
EXPECTED = {
    "number_of_decks": 5, "dealer_hits_on_soft_17": False,
    "dealer_peeks": False, "loses_only_original_bet_on_dealer_blackjack": False,
    "blackjack_pays": [3, 2], "can_double_on": "first two",
    "can_double_after_split": True, "can_hit_split_aces": False,
    "can_resplit_aces": True, "max_split_count": 3,
}
BVC_RULES = Rules(decks=5, dealer_peeks=False, no_peek_loses_all_bets=True)


def validate_ruleset(payload):
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or payload.get("error"):
        raise ValueError("Missing or unsuccessful BVC rules response.")
    differences = [key for key, value in EXPECTED.items()
                   if type(result.get(key)) is not type(value) or result[key] != value]
    if differences:
        raise ValueError("Unsupported or changed BVC rules: " + ", ".join(differences))
    return BVC_RULES


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Rules endpoint redirected; verify the site before continuing.")


def fetch_ruleset():
    # A fresh opener has no account cookies. The sole URL is a public read-only endpoint.
    with build_opener(NoRedirect).open(RULESET_URL, timeout=10) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("Rules response is too large.")
    payload = json.loads(raw)
    validate_ruleset(payload)
    return payload


def recommend_bvc(cards, dealer, *, splits_used=0, after_split=False, split_aces=False,
                  can_double=True, can_split=True):
    if type(splits_used) is not int or not 0 <= splits_used <= 3:
        raise ValueError("Splits used must be 0-3 for the whole round.")
    if after_split != (splits_used > 0):
        raise ValueError("Hand after split must agree with the round's splits used.")
    if split_aces and (not after_split or not cards or cards[0] != "A"):
        raise ValueError("Split-ace hand must start with an ace and follow a split.")
    return recommend(cards, dealer, BVC_RULES, can_surrender=False,
                     can_split=can_split and splits_used < 3, can_double=can_double,
                     after_split=after_split, split_aces=split_aces)


def main():
    parser = argparse.ArgumentParser(description="Check BVC blackjack rules; no account or game actions.")
    parser.add_argument("--rules-file", type=Path, help="Validate saved JSON instead of contacting the public endpoint")
    args = parser.parse_args()
    try:
        payload = json.loads(args.rules_file.read_text(encoding="utf-8")) if args.rules_file else fetch_ruleset()
        validate_ruleset(payload)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Not verified: {exc}\n")
    print("Rules compatible: 5 decks, S17, 3:2, no peek, all bets lost to dealer blackjack, DAS, max 3 splits.")
    print("Fresh shuffle each round. No shoe-count advantage. Advisory compatibility only; no profit edge verified.")


if __name__ == "__main__":
    main()
