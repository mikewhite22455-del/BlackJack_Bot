import json
import unittest

from casinotime_crew import review_payload, run_local_review
from casinotime_core import PROFILE, Scenario, Table
from casinotime_rollout import compare_actions, public_view, sample_table
from test_casinotime import rigged


class RolloutTests(unittest.TestCase):
    def test_hole_card_and_undealt_order_do_not_change_estimate(self):
        one = rigged(["10", "6", "8", "K"])
        two = rigged(["10", "6", "8", "2"])
        one.start()
        two.start()
        a = compare_actions(public_view(one), trials=30, seed=12)
        b = compare_actions(public_view(two), trials=30, seed=12)
        self.assertEqual(a, b)
        self.assertEqual(one.phase, "player")
        self.assertEqual(len(one.current_hand.cards), 2)

    def test_negative_peek_resampling_never_creates_blackjack(self):
        table = rigged(["8", "A", "7", "6"])
        table.start()
        table.insure([False])
        for seed in range(30):
            sampled = sample_table(public_view(table), seed)
            self.assertFalse(sampled.dealer_blackjack)
            self.assertEqual(len(sampled.shoe.cards), table.shoe.ledger.physical_remaining)

    def test_public_identifiers_do_not_encode_hidden_ranks(self):
        table = Table(Scenario("peek", 208, 1, 1))
        table.start()
        for event in table.shoe.ledger.events:
            self.assertRegex(event["id"], r"^\d+:\d+$")
            if event["rank"] is None:
                self.assertEqual(set(event), {"id", "rank", "type"})

    def test_action_comparison_accounts_for_split_and_double(self):
        table = rigged(["8", "6", "8", "10"])
        table.start()
        result = compare_actions(public_view(table), trials=20)
        self.assertEqual(set(result["actions"]), {"Hit", "Stand", "Double", "Split"})
        self.assertEqual(result["data_origin"], "synthetic_rollout")
        self.assertEqual(compare_actions(public_view(table), trials=20, cancelled=lambda: True), None)

    def test_review_only_accepts_synthetic_profile_and_drops_raw_history(self):
        report = {"schema": 1, "profile": PROFILE, "data_origin": "synthetic", "policy": "baseline", "runs": [
            {"scenario": {"cut_cards": 208}, "seed": 123, "result": {"rounds": 1000},
             "completed_shoes": ["not sent"]}]}
        self.assertNotIn("completed_shoes", json.dumps(review_payload(report)))
        report["data_origin"] = "live"
        with self.assertRaises(ValueError):
            review_payload(report)
        with self.assertRaises(ValueError):
            run_local_review({}, None)


if __name__ == "__main__":
    unittest.main()
