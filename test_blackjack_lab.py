"""Settlement, probability, learning and isolation checks for the offline lab."""

import json
import math
import random

import pytest

from blackjack_lab import main
from blackjack_lab_game import (ExactEvaluator, LabRules, State, Transition, World, add_card,
                                finish_dealer, hole_cards, legal_actions, new_hand, play_round)
from blackjack_lab_learning import QLearner, evaluate, reference_policy


class Cards:
    def __init__(self, cards):
        self.cards = iter(cards)

    def choice(self, choices):
        card = next(self.cards)
        assert card in choices
        return card


def never_called(state):
    raise AssertionError("Policy must not act before automatic natural settlement")


@pytest.mark.parametrize("cards,payout,expected", [
    ([1, 10, 10, 1], 1.5, 0),
    ([10, 1, 9, 10], 1.5, -1),
    ([1, 9, 10, 7], 1.5, 1.5),
    ([1, 9, 10, 7], 1.2, 1.2),
])
def test_naturals_before_player_actions(cards, payout, expected):
    assert play_round(never_called, Cards(cards), LabRules(blackjack_payout=payout)) == expected


def test_soft_aces_and_dealer_rule():
    assert add_card(12, True, 10) == (12, False)
    assert add_card(20, False, 1) == (21, False)
    assert add_card(12, True, 1) == (13, True)
    assert finish_dealer(1, 6, Cards([]), LabRules()) == 17
    assert finish_dealer(1, 6, Cards([10]), LabRules(hit_soft_17=True)) == 17
    assert finish_dealer(1, 6, Cards([2]), LabRules(hit_soft_17=True)) == 19


def test_peek_conditions_hidden_hole_distribution():
    assert 10 not in hole_cards(1)
    assert 1 not in hole_cards(10)
    assert len(hole_cards(6)) == 13
    assert hole_cards(10).count(10) == 4


@pytest.mark.parametrize("card,dealer,expected", [(10, 20, 2), (10, 21, 0), (10, 22, 2), (2, 17, -2)])
def test_double_net_settlement(card, dealer, expected):
    state = new_hand(5, 6, 6)
    result = World(Cards([card]), dealer, LabRules()).step(state, "Double")
    assert result == Transition(expected, ())


def test_bust_loses_even_when_dealer_busts():
    state = new_hand(10, 6, 6)
    assert World(Cards([10]), 23, LabRules()).step(state, "Hit") == Transition(-1, ())
    assert World(Cards([10]), 23, LabRules()).step(state, "Double") == Transition(-2, ())


def test_split_aces_have_no_natural_bonus_or_further_actions():
    state = new_hand(1, 1, 6)
    assert World(Cards([10, 10]), 20, LabRules()).step(state, "Split") == Transition(2, ())
    assert World(Cards([10, 10]), 21, LabRules()).step(state, "Split") == Transition(0, ())


def test_split_hand_legality_and_shared_dealer():
    state = new_hand(8, 8, 6)
    world = World(Cards([8, 3, 10]), 20, LabRules())
    result = world.step(state, "Split")
    assert len(result.children) == 2
    first, second = result.children
    assert "Split" not in legal_actions(first)
    assert "Double" in legal_actions(second)
    assert world.step(first, "Stand").reward == -1
    assert world.step(second, "Double").reward == 2


def test_no_double_after_split_rule():
    result = World(Cards([3, 3]), 20, LabRules(double_after_split=False)).step(new_hand(8, 8, 6), "Split")
    assert all("Double" not in legal_actions(child) for child in result.children)


def test_illegal_actions_and_double_after_hit():
    world = World(Cards([2]), 20, LabRules())
    child = world.step(new_hand(4, 5, 6), "Hit").children[0]
    assert legal_actions(child) == ("Stand", "Hit")
    with pytest.raises(ValueError, match="Illegal action"):
        world.step(child, "Double")
    with pytest.raises(ValueError, match="Illegal action"):
        world.step(child, "Insurance")


def test_exact_dealer_probabilities_sum_to_one():
    evaluator = ExactEvaluator(LabRules())
    for upcard in range(1, 11):
        distribution = dict(evaluator.dealer_distribution(upcard))
        assert sum(distribution.values()) == pytest.approx(1)
        assert set(distribution) <= {17, 18, 19, 20, 21, 22}
        assert all(value >= 0 for value in distribution.values())
    # Published infinite-deck S17 dealer distribution, with no peek conditioning needed for 6.
    assert dict(evaluator.dealer_distribution(6))[22] == pytest.approx(0.42315, abs=0.00001)


@pytest.mark.parametrize("cards,dealer,expected", [
    ((10, 10), 6, "Stand"), ((5, 6), 6, "Double"), ((8, 8), 10, "Split"),
    ((1, 1), 10, "Split"), ((10, 6), 10, "Hit"), ((1, 7), 9, "Hit"),
    ((10, 3), 6, "Stand"), ((1, 6), 6, "Double"),
])
def test_optimal_decisions_match_independent_basic_strategy_examples(cards, dealer, expected):
    assert ExactEvaluator(LabRules()).action(new_hand(*cards, dealer)) == expected


def test_payout_change_has_known_analytic_cost():
    # Natural frequency 8/169, minus dealer natural ties: payout change costs
    # 0.3 * (8/169) * (161/169) initial units, regardless of hand strategy.
    good = ExactEvaluator(LabRules()).initial_return()
    bad = ExactEvaluator(LabRules(blackjack_payout=1.2)).initial_return()
    assert good - bad == pytest.approx(0.3 * 8 / 169 * 161 / 169)
    assert -0.006 < good < -0.005


def test_existing_strategy_is_near_model_optimum():
    rules = LabRules()
    optimal = ExactEvaluator(rules).initial_return()
    reference = ExactEvaluator(rules, lambda state: reference_policy(state, rules)).initial_return()
    assert reference <= optimal + 1e-12
    assert optimal - reference < 0.0001


def test_split_q_target_adds_both_hands():
    model = QLearner()
    state = new_hand(8, 8, 6)
    first = new_hand(8, 2, 6, split=False)
    second = new_hand(8, 3, 6, split=False)
    model.q[first] = [0.1, 0.2, 0.3, 99]
    model.q[second] = [-0.1, 0.1, 0.4, 99]
    model.update(state, "Split", Transition(0, (first, second)))
    assert model.q[state][3] == pytest.approx(0.7)
    assert model.visits[state][3] == 1


def test_q_hit_bootstrap_ignores_unavailable_actions():
    model = QLearner()
    state, child = new_hand(4, 5, 6), State(11, False, 6, 0, False, False)
    model.q[child] = [0.2, 0.3, 999, 999]
    model.update(state, "Hit", Transition(0, (child,)))
    assert model.q[state][1] == pytest.approx(0.3)


def test_hit_learning_rate_does_not_depend_on_bust_outcome():
    model = QLearner()
    state, child = new_hand(10, 6, 10), State(18, False, 10, 0, False, False)
    model.update(state, "Hit", Transition(0, (child,)))
    model.update(state, "Hit", Transition(-1, ()))
    assert model.q[state][1] == pytest.approx(-(2 ** -0.6))


def test_stand_uses_unbiased_sample_mean():
    model = QLearner()
    state = new_hand(10, 6, 6)
    for reward in (1, -1, -1, 1):
        model.update(state, "Stand", Transition(reward, ()))
    assert model.q[state][0] == pytest.approx(0)


def test_checkpoint_resume_matches_uninterrupted_learning(tmp_path):
    continued = QLearner(seed=12)
    continued.train(5000)
    path = tmp_path / "checkpoint.json"
    continued.save(path)
    resumed = QLearner.load(path)
    continued.train(1000)
    resumed.train(1000)
    assert continued.q == resumed.q
    assert continued.episodes == resumed.episodes == 6000
    assert continued.rng.getstate() == resumed.rng.getstate()
    assert continued.choices.getstate() == resumed.choices.getstate()


def test_frozen_evaluation_does_not_mutate_training(tmp_path):
    model = QLearner(seed=3)
    model.train(500)
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    model.save(before)
    evaluate(model.greedy, model.rules, 500, 999)
    model.save(after)
    assert before.read_bytes() == after.read_bytes()


def test_evaluation_matches_exact_expected_return():
    oracle = ExactEvaluator(LabRules())
    result = evaluate(oracle.action, oracle.rules, 100000, 19937)
    error = abs(result["mean_net_units"] - oracle.initial_return())
    margin = (result["mean_95_ci"][1] - result["mean_95_ci"][0]) / 2
    assert error < 3 * margin
    assert sum(result[key] for key in ("win_rounds", "loss_rounds", "push_rounds")) == 100000
    assert result["complete_sessions"] == 1000


def test_episode_learning_improves_over_untrained_policy():
    model = QLearner(seed=11)
    initial = ExactEvaluator(model.rules, model.greedy).initial_return()
    model.train(100000)
    after = ExactEvaluator(model.rules, model.greedy).initial_return()
    assert after > initial + 0.04
    assert all(math.isfinite(value) for row in model.q.values() for value in row)


def test_report_and_resume_cli(tmp_path):
    report = main(["--train-episodes", "200", "--eval-rounds", "200", "--output", str(tmp_path)])
    assert report["training_episodes"] == 200
    assert report["optimal_exact_net_units"] < 0
    page = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "OFFLINE RESEARCH" in page
    assert "discrepancy is unresolved" in page
    assert "<script" not in page
    main(["--resume", str(tmp_path / "checkpoint.json"), "--train-episodes", "0",
          "--eval-rounds", "200", "--output", str(tmp_path)])


def test_bad_checkpoint_and_argument_validation(tmp_path):
    model = QLearner()
    path = tmp_path / "bad.json"
    model.train(10)
    model.save(path)
    data = json.loads(path.read_text())
    data["rows"][0]["q"][0] = float("nan")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Invalid Q values"):
        QLearner.load(path)
    with pytest.raises(ValueError):
        model.train(-1)
    with pytest.raises(ValueError):
        evaluate(model.greedy, model.rules, 1, 5)
    with pytest.raises(SystemExit):
        main(["--train-episodes", "-1"])
    with pytest.raises(ValueError):
        LabRules(blackjack_payout=2)


def test_sampled_double_value_agrees_with_probability_enumeration():
    state = new_hand(5, 6, 6)
    rng, rules = random.Random(45), LabRules()
    total = 0
    for _ in range(50000):
        hole = rng.choice(hole_cards(6))
        world = World(rng, finish_dealer(6, hole, rng, rules), rules)
        total += world.step(state, "Double").reward
    expected = ExactEvaluator(rules).values(state)["Double"]
    assert total / 50000 == pytest.approx(expected, abs=0.025)
