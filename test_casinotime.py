"""Rule settlement, evidence integrity and persistent-shoe regression tests."""

from collections import Counter
import itertools
import json
import unittest

from casinotime_core import Card, EightDeckShoe, RANKS, Scenario, ShoeLedger, Table, side_bets
from casinotime_lab import report_html, run_experiment, summarize


def rigged(ranks, *, ten="no_peek_all_bets", cut=208, seats=1):
    table = Table(Scenario(ten, cut, seats, 0))
    remaining = list(table.shoe.cards)
    prefix = []
    for rank in ranks:
        card = next(c for c in remaining if c.rank == rank)
        remaining.remove(card)
        prefix.append(card)
    table.shoe.cards = prefix + remaining
    return table


class LedgerTests(unittest.TestCase):
    def test_same_physical_card_is_idempotent_but_same_rank_is_not(self):
        ledger = ShoeLedger("shoe-1")
        self.assertTrue(ledger.observe("first", "5"))
        self.assertFalse(ledger.observe("first", "5"))
        self.assertTrue(ledger.observe("different-card", "5"))
        self.assertEqual(ledger.running_count, 2)
        with self.assertRaises(ValueError):
            ledger.observe("first", "K")
        self.assertEqual(ledger.running_count, 2)

    def test_hidden_card_reveal_counts_once_and_replays(self):
        ledger = ShoeLedger("1")
        ledger.observe("burn")
        ledger.observe("hole")
        ledger.observe("hole", "A")
        ledger.observe("hole", "A")
        self.assertEqual(ledger.unknown_removed, 1)
        self.assertEqual(ledger.physical_remaining, 414)
        self.assertEqual(ledger.running_count, -1)
        restored = ShoeLedger.replay(json.loads(json.dumps(ledger.export())))
        self.assertEqual(restored.cards, ledger.cards)
        self.assertEqual(restored.events, ledger.events)

    def test_unknown_burn_does_not_invent_rank(self):
        ledger = ShoeLedger("1")
        ledger.observe("burn")
        self.assertEqual(set(ledger.probabilities().values()), {1 / 13})
        self.assertEqual(sum(ledger.unseen.values()), 416)
        self.assertEqual(ledger.physical_remaining, 415)

    def test_negative_peek_marginal_against_enumeration(self):
        ledger = ShoeLedger("1")
        leftovers = Counter(["A", "10", "2", "3"])
        for rank in RANKS:
            for index in range(32 - leftovers[rank]):
                ledger.observe(f"{rank}:{index}", rank)
        ledger.observe("dealer-hole")
        possible = [p for p in itertools.permutations(["A", "10", "2", "3"]) if p[0] != "A"]
        actual = ledger.probabilities(("A",))
        for rank in leftovers:
            expected = sum(p[1] == rank for p in possible) / len(possible)
            self.assertAlmostEqual(actual[rank], expected)
        self.assertAlmostEqual(sum(actual.values()), 1)

    def test_gap_disables_probability_and_new_observations(self):
        ledger = ShoeLedger("1")
        ledger.mark_gap("video interrupted")
        for operation in (ledger.probabilities, lambda: ledger.observe("card", "3")):
            with self.assertRaises(ValueError):
                operation()
        self.assertFalse(ShoeLedger.replay(ledger.export()).valid)

    def test_invalid_event_and_capacity(self):
        ledger = ShoeLedger("1")
        for index in range(32):
            ledger.observe(str(index), "2")
        with self.assertRaises(ValueError):
            ledger.observe("33rd", "2")
        payload = {"schema": 1, "profile": ledger.export()["profile"], "shoe_id": "1",
                   "events": [{"type": "reveal", "id": "missing", "rank": "A"}]}
        with self.assertRaises(ValueError):
            ShoeLedger.replay(payload)


class ShoeTests(unittest.TestCase):
    def test_exactly_eight_decks_and_unique_physical_ids(self):
        shoe = EightDeckShoe(7, Scenario("peek", 208))
        self.assertEqual(len(shoe.cards), 416)
        self.assertEqual(len({c.identity for c in shoe.cards}), 416)
        self.assertEqual(set(Counter((c.rank, c.suit) for c in shoe.cards).values()), {8})

    def test_cut_waits_for_round_end_and_resets_next_round(self):
        table = rigged(["10", "6", "7", "10", "5"], cut=52)
        # Simulate 50 public discards without consuming the prepared next deal.
        for card in table.shoe.cards[-50:]:
            table.shoe.ledger.observe(card.identity, card.rank)
        table.shoe.cards = table.shoe.cards[-50:] + table.shoe.cards[:-50]
        table.shoe.position = 50
        table.start()
        self.assertTrue(table.shoe.cut_reached)
        self.assertEqual(table.shoe.number, 1)
        with self.assertRaises(ValueError):
            table.new_shoe()
        table.act("Stand")
        self.assertEqual(table.shoe.number, 1)
        table.start()
        self.assertEqual(table.shoe.number, 2)

    def test_unknown_table_rules_not_silently_defaulted(self):
        for args in (("unconfirmed", 208), ("peek", 400), ("peek", 208, 8), ("peek", 208, 1, -1)):
            with self.assertRaises(ValueError):
                Scenario(*args)


class SettlementTests(unittest.TestCase):
    def test_natural_pays_three_to_two(self):
        table = rigged(["A", "6", "K", "10"])
        table.start()
        self.assertEqual(table.phase, "settled")
        self.assertEqual(table.profits(), [1.5])

    def test_ace_check_and_insurance(self):
        table = rigged(["10", "A", "9", "K"])
        table.start()
        self.assertEqual(table.public_state()["dealer"], [table.dealer[0].label(), "Hidden"])
        table.insure([True])
        self.assertEqual(table.profits(), [0])
        self.assertEqual(table.shoe.ledger.unknown_removed, 0)

    def test_ten_check_prevents_exposing_double(self):
        table = rigged(["5", "K", "6", "A"], ten="peek")
        table.start()
        self.assertEqual(table.phase, "settled")
        self.assertEqual(table.profits(), [-1])

    def test_no_ten_check_double_loses_both_units_to_blackjack(self):
        table = rigged(["5", "K", "6", "A", "10"])
        table.start()
        table.act("Double")
        self.assertEqual(table.profits(), [-2])

    def test_split_aces_draw_once_and_21_is_even_money(self):
        table = rigged(["A", "10", "A", "9", "K", "Q"])
        table.start()
        table.act("Split")
        self.assertEqual(table.phase, "settled")
        self.assertEqual([h.bet for h in table.seats[0]], [1, 1])
        self.assertEqual(table.profits(), [2])
        self.assertTrue(all(not h.natural and len(h.cards) == 2 for h in table.seats[0]))

    def test_single_split_per_box_and_double_after_split(self):
        table = rigged(["8", "6", "8", "10", "8", "3", "2", "10", "10"])
        table.start()
        table.act("Split")
        self.assertNotIn("Split", table.legal_actions())
        self.assertIn("Double", table.legal_actions())
        table.act("Stand")
        table.act("Double")
        self.assertEqual(len(table.seats[0]), 2)
        self.assertEqual(table.seats[0][1].bet, 2)

    def test_equal_value_face_cards_can_split(self):
        table = rigged(["K", "6", "Q", "10"])
        table.start()
        self.assertIn("Split", table.legal_actions())

    def test_dealer_stands_soft_seventeen(self):
        table = rigged(["10", "6", "7", "A", "K"])
        table.start()
        table.act("Stand")
        self.assertEqual(len(table.dealer), 2)
        self.assertEqual(table.profits(), [0])

    def test_player_bust_loses_even_if_dealer_busts(self):
        table = rigged(["10", "6", "8", "10", "K", "K"])
        table.start()
        table.act("Hit")
        self.assertEqual(table.profits(), [-1])

    def test_public_state_does_not_leak_hole_or_undealt_cards(self):
        one = rigged(["5", "6", "7", "K"])
        two = rigged(["5", "6", "7", "2"])
        one.start()
        two.start()
        self.assertEqual(one.public_state(), two.public_state())
        self.assertEqual(one.next_card_probabilities(), two.next_card_probabilities())

    def test_seven_seats_share_one_dealer_and_reproducible_shoes(self):
        first = run_experiment(Scenario("peek", 208, 7, 1), 100, 123)
        second = run_experiment(Scenario("peek", 208, 7, 1), 100, 123)
        self.assertEqual(first, second)
        self.assertGreater(first[1]["shoes"], 5)

    def test_report_is_explicitly_synthetic(self):
        rows, result, _ = run_experiment(Scenario("peek", 208), 30, 4)
        self.assertEqual(summarize(rows), result)
        self.assertIsNone(result["approx_95pct_shoe_cluster_interval"])
        report = {"runs": [{"scenario": {"dealer_ten": "peek", "cut_cards": 208, "seats": 1, "burn_cards": 0},
                            "result": result}]}
        self.assertIn("synthetic experiments", report_html(report))


class SideBetTests(unittest.TestCase):
    def test_published_paytables(self):
        fixtures = [(("QH", "QH", "QH"), 25, 100), (("QH", "QD", "QS"), 12, 30),
                    (("QH", "QS", "3C"), 6, -1), (("AH", "2H", "3H"), -1, 40),
                    (("QH", "KD", "AS"), -1, 10), (("2S", "5S", "9S"), -1, 5),
                    (("2S", "3D", "KC"), -1, -1)]
        for labels, pairs, three in fixtures:
            with self.subTest(labels=labels):
                cards = [Card(label[:-1], label[-1], str(i)) for i, label in enumerate(labels)]
                self.assertEqual(side_bets(cards[:2], cards[2]), {"Perfect Pairs": pairs, "21+3": three})


if __name__ == "__main__":
    unittest.main()
