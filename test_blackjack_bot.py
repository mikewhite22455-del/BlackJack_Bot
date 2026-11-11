import math
import unittest

from blackjack_bot import (
    CardCounter, capture_screen, extract_card_ranks, get_bet_size, parse_cards,
)


class CardParsingTests(unittest.TestCase):
    def test_tens_faces_and_suits(self):
        self.assertEqual(extract_card_ranks("10 A 5 J\u2660 qH"), ["10", "A", "5", "J", "Q"])

    def test_words_and_balances_do_not_become_cards(self):
        self.assertEqual(extract_card_ranks("BLACKJACK 100 PLAYER balance=25"), [])

    def test_manual_snapshot_accepts_separators(self):
        self.assertEqual(parse_cards("10, a; 5\n5"), ["10", "A", "5", "5"])

    def test_manual_snapshot_rejects_bad_tokens(self):
        with self.assertRaises(ValueError):
            parse_cards("10, unknown, A")

    def test_empty_snapshot(self):
        self.assertEqual(parse_cards(""), [])

    def test_capture_requires_an_explicit_area(self):
        for region in (None, {}, {"width": 0, "height": 50}):
            with self.subTest(region=region), self.assertRaises(ValueError):
                capture_screen(region)


class CountingTests(unittest.TestCase):
    def test_hi_lo_and_fractional_decks(self):
        counter = CardCounter(0.5)
        counter.observe(["2", "5", "7", "K", "A", "6"])
        self.assertEqual(counter.running_count, 1)
        self.assertEqual(counter.true_count, 2)

    def test_repeated_reordered_and_temporarily_missing_cards(self):
        counter = CardCounter()
        self.assertEqual(counter.observe(["5", "5", "K"]), 3)
        for cards in (["5", "5", "K"], ["K", "5", "5"], [], ["5"], ["5", "5", "K"]):
            self.assertEqual(counter.observe(cards), 0)
        self.assertEqual(counter.running_count, 1)

    def test_new_same_rank_is_counted_once(self):
        counter = CardCounter()
        counter.observe(["5"])
        self.assertEqual(counter.observe(["5", "5"]), 1)
        self.assertEqual(counter.observe(["5", "5"]), 0)
        self.assertEqual(counter.running_count, 2)

    def test_new_round_retains_shoe_count(self):
        counter = CardCounter()
        counter.observe(["5"])
        counter.new_round()
        self.assertEqual(counter.observe(["5"]), 1)
        self.assertEqual(counter.running_count, 2)

    def test_new_shoe_clears_history_and_count(self):
        counter = CardCounter()
        counter.observe(["K"])
        counter.new_shoe()
        self.assertEqual(counter.true_count, 0)
        self.assertEqual(counter.observe(["K"]), 1)
        self.assertEqual(counter.running_count, -1)

    def test_invalid_snapshot_is_atomic(self):
        counter = CardCounter()
        with self.assertRaises(ValueError):
            counter.observe(["5", "invalid"])
        self.assertEqual(counter.running_count, 0)
        self.assertEqual(counter.observe(["5"]), 1)

    def test_changing_decks_recalculates_true_count(self):
        counter = CardCounter(4)
        counter.observe(["5", "5"])
        counter.set_decks_remaining(2)
        self.assertEqual(counter.true_count, 1)

    def test_invalid_deck_estimate_is_rejected(self):
        for value in (0, -1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CardCounter(value)


class UnitScheduleTests(unittest.TestCase):
    def test_boundaries_and_fractional_counts(self):
        cases = [(-2, 1), (0, 1), (0.25, 1), (0.99, 1), (1, 2), (1.5, 2),
                 (2, 4), (2.75, 4), (3, 6), (3.99, 6), (4, 8), (4.5, 8),
                 (5, 10), (10, 10)]
        for count, expected in cases:
            with self.subTest(count=count):
                self.assertEqual(get_bet_size(count), expected)

    def test_nonfinite_counts_are_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                get_bet_size(value)


if __name__ == "__main__":
    unittest.main()
