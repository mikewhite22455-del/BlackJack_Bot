"""Reproducible, finite-shoe scenario experiments for Casino Time VIP rules."""

import argparse
import csv
from dataclasses import asdict
import html
import json
import math
from pathlib import Path

from casinotime_core import PROFILE, SOURCE_URL, Scenario, Table


def summarize(rows):
    """Cluster by shoe because consecutive rounds do not use independent decks."""
    n = len(rows)
    if not n:
        raise ValueError("No rounds to summarize.")
    mean = sum(r["profit"] for r in rows) / n
    clusters = {}
    for row in rows:
        clusters.setdefault(row["shoe"], []).append(row["profit"])
    k = len(clusters)
    residuals = [sum(values) - len(values) * mean for values in clusters.values()]
    se = math.sqrt(k / (k - 1) * sum(x * x for x in residuals)) / n if k >= 30 else None
    balance = peak = drawdown = 0.0
    for row in rows:
        balance += row["profit"]
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    return {"rounds": n, "shoes": k, "net_units": balance, "mean_net_per_initial_unit": mean,
            "approx_95pct_shoe_cluster_interval": [mean - 1.96 * se, mean + 1.96 * se] if se is not None else None,
            "observed_max_drawdown_units": drawdown,
            "winning_round_fraction": sum(r["profit"] > 0 for r in rows) / n,
            "interpretation": "Simulation estimate for stated assumptions, not verified live expected value."}


def run_experiment(scenario, rounds, seed):
    if type(rounds) is not int or rounds < 1:
        raise ValueError("rounds must be a positive integer.")
    table = Table(scenario, seed)
    rows = []
    for number in range(1, rounds + 1):
        # Mirror start()'s cut-card handling before recording the pre-deal count.
        if table.shoe.cut_reached:
            table.new_shoe("cut card / completed round")
        before = table.shoe.ledger.running_count
        depth = table.shoe.position
        table.start()
        table.autoplay()
        rows.append({"round": number, "shoe": table.shoe.number, "cards_before": depth,
                     "cards_after": table.shoe.position, "running_count_before": before,
                     "running_count_after": table.shoe.ledger.running_count,
                     "profit": table.profits()[0]})
    return rows, summarize(rows), table.shoe.history


def report_html(report):
    rows = []
    for run in report["runs"]:
        scenario, result = run["scenario"], run["result"]
        interval = result["approx_95pct_shoe_cluster_interval"]
        interval_text = "Insufficient shoes" if interval is None else f"{interval[0]:+.3%} to {interval[1]:+.3%}"
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(x))}</td>" for x in (
            scenario["dealer_ten"], f'{scenario["cut_cards"]}/416', scenario["seats"], scenario["burn_cards"],
            result["rounds"], result["shoes"], f'{result["mean_net_per_initial_unit"]:+.3%}', interval_text,
            f'{result["observed_max_drawdown_units"]:.1f}')) + "</tr>")
    return """<!doctype html><meta charset="utf-8"><title>Casino Time eight-deck lab</title>
<style>body{font:16px system-ui;background:#10181d;color:#e6eff1;margin:40px;max-width:1400px}
h1{color:#55dacb}table{border-collapse:collapse;width:100%}td,th{border:1px solid #3b555d;padding:10px}
th{text-align:left;background:#18353b}a{color:#55dacb}p{line-height:1.6}
.note{border-left:4px solid #e7bc6b;padding:16px}</style>
<h1>Casino Time · eight-deck research lab</h1>
<p>Pragmatic Play VIP Blackjack: 416 cards, S17, 3:2, double after split, one split per box.</p>
<p class="note">These are synthetic experiments. Cut depth, burn count and the dealer's ten-upcard procedure
are explicit assumptions. No real casino hands were collected. Basic strategy is used at every seat;
opening bets are fixed at one unit. These runs do not train Q-learning or establish a profitable strategy.</p>
<table><tr><th>Dealer ten scenario</th><th>Cut at</th><th>Seats</th><th>Burns</th><th>Rounds</th><th>Shoes</th>
<th>Net / initial unit</th><th>Approximate 95% interval</th><th>Observed drawdown</th></tr>""" + "".join(rows) + """</table>
<p>Intervals cluster observations by shoe and require at least 30 shoes. They describe sampling uncertainty,
not model error, real-table accuracy or a guarantee. Drawdown is from each simulated path, not a future bound.
The final shoe can be partial. All seats share a dealer; only seat 1's net return is reported.</p>
<p>Insurance and side bets are declined in these experiments. The main game includes naturals, pushes,
splits, doubles and dealer-blackjack settlement. Model code and seed reproduce the result.</p>"""


def main():
    parser = argparse.ArgumentParser(description="Casino Time VIP eight-deck scenario lab; synthetic hands only")
    parser.add_argument("--rounds", type=int, default=10000, help="Rounds per scenario")
    parser.add_argument("--seats", type=int, default=5)
    parser.add_argument("--burn-cards", type=int, default=1, help="Assumed hidden burns per shoe")
    parser.add_argument("--cut-cards", type=int, nargs="+", default=[208, 312], help="Assumed cut positions")
    parser.add_argument("--dealer-ten", choices=["both", "peek", "no_peek_all_bets"], default="both")
    parser.add_argument("--seed", type=int, default=20261111)
    parser.add_argument("--output", type=Path, default=Path("casinotime-results"))
    args = parser.parse_args()
    variants = ["peek", "no_peek_all_bets"] if args.dealer_ten == "both" else [args.dealer_ten]
    try:
        scenarios = [Scenario(rule, cut, args.seats, args.burn_cards) for rule in variants for cut in args.cut_cards]
        if args.rounds < 1:
            raise ValueError("rounds must be positive")
    except ValueError as exc:
        parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "profile": PROFILE, "source": SOURCE_URL, "data_origin": "synthetic",
              "policy": "fixed-unit basic strategy; no insurance or side bets", "runs": []}
    for index, scenario in enumerate(scenarios):
        seed = args.seed + index
        rows, result, shoes = run_experiment(scenario, args.rounds, seed)
        with (args.output / f"scenario-{index + 1}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        report["runs"].append({"scenario": asdict(scenario), "seed": seed, "result": result, "completed_shoes": shoes})
        print(f"{scenario.dealer_ten}, cut={scenario.cut_cards}: {result['rounds']} rounds, "
              f"{result['shoes']} shoes, sample return {result['mean_net_per_initial_unit']:+.3%}", flush=True)
    (args.output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.output / "report.html").write_text(report_html(report), encoding="utf-8")
    print(f"Saved {args.output / 'report.html'}")


if __name__ == "__main__":
    main()
