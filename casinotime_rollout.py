"""Action comparisons using public evidence and finite-shoe Monte Carlo.

Every legal current action is followed by fixed basic strategy at all seats.
This is a rollout estimate, not a composition-optimal policy or live edge proof.
"""

from dataclasses import asdict
import math
import random
import statistics

from casinotime_core import Card, Hand, Scenario, ShoeLedger, Table


def public_view(table):
    if table.phase != "player":
        raise ValueError("Action comparison requires an active player decision.")
    hands = [[{"cards": [asdict(card) for card in hand.cards], "bet": hand.bet,
               "after_split": hand.after_split, "split_aces": hand.split_aces,
               "done": hand.done, "profit": hand.profit} for hand in seat] for seat in table.seats]
    return {"scenario": asdict(table.scenario), "hands": hands, "active": table.active,
            "dealer_up": asdict(table.dealer[0]), "hole_id": table.dealer[1].identity,
            "peek_negative": table.peek_negative, "insurance": list(table.insurance),
            "ledger": table.shoe.ledger.export()}


def sample_table(view, seed):
    """Sample hidden cards from observed composition, never the original deck."""
    ledger = ShoeLedger.replay(view["ledger"])
    rng = random.Random(seed)
    pool = [rank for rank, count in ledger.unseen.items() for _ in range(count)]
    excluded = ()
    if view["peek_negative"]:
        excluded = ("10", "J", "Q", "K") if view["dealer_up"]["rank"] == "A" else ("A",)
    eligible = [i for i, rank in enumerate(pool) if rank not in excluded]
    if not ledger.valid or ledger.cards.get(view["hole_id"], "missing") is not None or not eligible:
        raise ValueError("Invalid public evidence for a hidden dealer card.")
    hole = pool.pop(rng.choice(eligible))
    rng.shuffle(pool)
    # Unknown burns are sampled and removed rather than exposed to the policy.
    pool = pool[ledger.unknown_removed - 1:]
    table = Table(Scenario(**view["scenario"]), seed)
    table.shoe.cards = [Card(rank, "C", f"rollout:{seed}:{i}") for i, rank in enumerate(pool)]
    table.shoe.position = 0
    table.shoe.ledger = ledger
    table.dealer = [Card(**view["dealer_up"]), Card(hole, "C", view["hole_id"])]
    table.seats = [[Hand([Card(**card) for card in h["cards"]], h["bet"], h["after_split"],
                         h["split_aces"], h["done"], h["profit"]) for h in seat] for seat in view["hands"]]
    table.phase = "player"
    table.active = tuple(view["active"])
    table.peek_negative = view["peek_negative"]
    table.insurance = list(view["insurance"])
    return table


def interval(values):
    mean = statistics.fmean(values)
    error = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, [mean - error, mean + error]


def compare_actions(view, trials=1000, seed=314159, cancelled=None):
    if type(trials) is not int or not 20 <= trials <= 100000:
        raise ValueError("Use between 20 and 100000 trials per action.")
    actions = sample_table(view, seed).legal_actions()
    outcomes = {action: [] for action in actions}
    rng = random.Random(seed)
    for _ in range(trials):
        if cancelled is not None and cancelled():
            return None
        trial_seed = rng.randrange(2**63)
        for action in actions:
            table = sample_table(view, trial_seed)
            table.act(action)
            table.autoplay()
            outcomes[action].append(table.profits()[view["active"][0]])
    ordered = sorted(actions, key=lambda a: statistics.fmean(outcomes[a]), reverse=True)
    best, runner_up = ordered[:2]
    paired = [a - b for a, b in zip(outcomes[best], outcomes[runner_up])]
    gap, gap_interval = interval(paired)
    results = {a: {"mean_net_seat_units": interval(outcomes[a])[0], "approx_95pct_interval": interval(outcomes[a])[1]}
               for a in ordered}
    return {"data_origin": "synthetic_rollout", "continuation": "basic strategy at all seats",
            "trials_per_action": trials, "seed": seed, "actions": results, "highest_sample_mean": best,
            "gap_vs_runner_up": gap, "paired_gap_interval": gap_interval,
            "note": "Intervals are exploratory and not corrected for selecting the highest sample mean. "
                    "Net units cover the whole active seat. Estimates are not a live expected-return guarantee."}
