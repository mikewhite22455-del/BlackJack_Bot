"""Run an offline blackjack learning experiment and open the resulting report."""

import argparse
import html
import json
from pathlib import Path

from blackjack_lab_game import ExactEvaluator, LabRules, decision_starts
from blackjack_lab_learning import QLearner, compare


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Use a positive integer.")
    return number


def nonnegative_integer(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("Use zero or a positive integer.")
    return number


def result_rows(report):
    rows = []
    for key, title in (("learned", "Frozen Q-learning policy"), ("reference", "Existing basic strategy"),
                       ("optimal", "Exact model optimum")):
        result = report[key]
        exact = report[f"{key}_exact_net_units"] * 100
        low, high = (number * 100 for number in result["mean_95_ci"])
        sessions = result["positive_session_fraction"]
        session_text = f"{sessions:.1%}" if sessions is not None else "Not enough complete sessions"
        rows.append(f"<tr><th>{title}</th><td>{exact:+.3f}</td>"
                    f"<td>{result['mean_net_units'] * 100:+.3f}</td><td>{low:+.3f} to {high:+.3f}</td>"
                    f"<td>{session_text}</td></tr>")
    return "".join(rows)


def decision_rows(model):
    oracle = ExactEvaluator(model.rules)
    rows = []
    for state in decision_starts(model.rules):
        learned, best = model.greedy(state), oracle.action(state)
        values = oracle.values(state)
        gap = max(values.values()) - values[learned]
        if gap <= 0.001:
            continue
        label = f"{'Soft' if state.soft else 'Hard'} {state.total}"
        if state.pair:
            label = f"Pair {'A' if state.pair == 1 else state.pair}"
        dealer = "A" if state.dealer == 1 else str(state.dealer)
        visits = model.visits.get(state, [0] * 4)
        rows.append(f"<tr><td>{label}</td><td>{dealer}</td><td>{state.double}</td>"
                    f"<td>{learned}</td><td>{best}</td><td>{gap:.4f}</td><td>{sum(visits):,}</td></tr>")
    return "".join(rows) or '<tr><td colspan="7">All sampled decision states are within 0.001 units of optimal.</td></tr>'


def write_report(report, model, path):
    rules = report["rules"]
    dealer = "hits" if rules["hit_soft_17"] else "stands on"
    payout = "3:2" if rules["blackjack_payout"] == 1.5 else "6:5"
    das = "allowed" if rules["double_after_split"] else "not allowed"
    conclusion = ("The exact model optimum remains negative. This experiment does not establish a profitable strategy."
                  if report["optimal_exact_net_units"] < 0 else
                  "Check the rule model and independent validation before interpreting a positive modeled expectation.")
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Blackjack Learning Lab</title>
<style>body{{margin:0;background:#101820;color:#edf3f4;font:16px system-ui,sans-serif}}
main{{max-width:1160px;margin:auto;padding:36px 22px}}h1{{font-size:36px;margin:12px 0}}
h2{{font-size:23px;margin-top:30px}}p,li{{line-height:1.6}}.tag{{color:#64ded4;font-weight:700}}
.notice{{border-left:5px solid #64ded4;padding:14px 20px;background:#1b2b34}}
.table{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;border-bottom:1px solid #37505a;padding:12px}}thead{{background:#20333e}}
small{{color:#b6cbd0}}a{{color:#64ded4}}code{{color:#f3d99b}}details{{margin-top:28px}}
</style><main><div class="tag">OFFLINE RESEARCH · NO CASINO CONNECTION</div>
<h1>Blackjack Learning Lab</h1><p class="notice">{conclusion}</p>
<p>Q-learning practiced on <strong>{report['training_episodes']:,} decision-start episodes</strong>.
Its policy was then frozen and tested on <strong>{report['learned']['rounds']:,} fresh full rounds</strong>.
Each comparison policy has its own fixed evaluation seed. Training starts are not full casino rounds.</p>
<h2>Does the learning improve the decisions?</h2><div class="table"><table><thead><tr>
<th>Policy</th><th>Exact net units / 100 rounds</th><th>Sample net units / 100 rounds</th>
<th>95% interval for sample mean</th><th>Sessions finishing ahead</th>
</tr></thead><tbody>{result_rows(report)}</tbody></table></div>
<p>One starting unit per round. Splits and doubles can increase the amount exposed to four units.
Net units include all added stakes. A 95% interval describes uncertainty in the estimated mean,
not the range of outcomes for your next session. Session length: {report['learned']['session_hands']} rounds;
no stop-loss, profit target, compounding, bonuses, fees or bankroll limit.
An incomplete final session is excluded from the session fraction.</p>
<p><strong>{report['near_optimal_states']} of {report['decision_states']} states</strong> choose an action
within 0.001 expected units of optimal. This unweighted state count is not a win percentage.
The exact frozen-policy shortfall is <strong>{report['learned_gap_units'] * 100:.3f} units per 100 rounds</strong>.</p>
<h2>Precisely what was modeled</h2><ul>
<li>Independent infinite-deck draws: ace through nine each 1/13; ten-valued cards 4/13.</li>
<li>Dealer {dealer} soft 17; American peek before player decisions; natural pays {payout}.</li>
<li>Hit, stand, double on the first two cards, and one split into two hands. No resplitting.</li>
<li>Double after splitting is {das}. Split aces receive one card. Split 21 pays even money.</li>
<li>No insurance, surrender, side bets, card counting, screen reading, API keys or wagers.</li>
</ul><p>The exact benchmark enumerates card probabilities; it does not train the Q-table.
The existing basic strategy is a multi-deck reference, evaluated here under this model.
The policy never receives the dealer's hidden card or final total.</p>
<p>Rules source: <a href="https://help.shuffle.com/en/articles/8231559-shuffle-original-blackjack-game-information">
Shuffle's published main-game rules</a>. This is a rule-based research model, not a certified
replica or an endorsement of casino automation. The default model yields about 99.43% return
per initial unit, while Shuffle's marketing page lists 99.48%. That discrepancy is unresolved;
do not interpret this report as a verified site RTP.</p>
<details><summary>Inspect remaining decision differences</summary><div class="table"><table><thead>
<tr><th>Hand</th><th>Dealer</th><th>Double available</th><th>Learned</th><th>Optimal</th>
<th>Action EV shortfall</th><th>Training visits</th></tr></thead><tbody>{decision_rows(model)}</tbody>
</table></div></details><p><small>Training seed: {report['training_seed']}; optimal evaluation seed:
{report['optimal']['seed']}; learned evaluation seed: {report['learned']['seed']}; reference evaluation seed:
{report['reference']['seed']}. {html.escape(report['training_method'])}.
Full numeric results are in results.json; the resumable Q-table is in checkpoint.json.</small></p></main></html>"""
    Path(path).write_text(page, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-episodes", type=nonnegative_integer, default=1000000)
    parser.add_argument("--eval-rounds", type=positive_integer, default=200000)
    parser.add_argument("--session-hands", type=positive_integer, default=100)
    parser.add_argument("--seed", type=int, default=20261111)
    parser.add_argument("--eval-seed", type=int, default=817293)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--output", type=Path, default=Path("learning-results"))
    parser.add_argument("--six-to-five", action="store_true", help="Study a 6:5 payout instead of 3:2.")
    args = parser.parse_args(argv)
    if args.eval_rounds < 2:
        parser.error("--eval-rounds must be at least 2")
    if args.resume and args.six_to_five:
        parser.error("A resumed checkpoint retains its saved rules; omit --six-to-five.")
    model = QLearner.load(args.resume) if args.resume else QLearner(
        LabRules(blackjack_payout=1.2 if args.six_to_five else 1.5), args.seed)
    print("Offline research only. Training uses simulated cards; no casino is contacted.", flush=True)
    model.train(args.train_episodes, lambda count: print(f"Trained {count:,} decision episodes", flush=True))
    args.output.mkdir(parents=True, exist_ok=True)
    model.save(args.output / "checkpoint.json")
    print("Evaluating frozen policies on fresh full rounds...", flush=True)
    report = compare(model, args.eval_rounds, args.eval_seed, args.session_hands)
    (args.output / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    write_report(report, model, args.output / "report.html")
    print(f"Learned exact net / 100 rounds: {report['learned_exact_net_units'] * 100:+.3f}")
    print(f"Optimal exact net / 100 rounds: {report['optimal_exact_net_units'] * 100:+.3f}")
    print(f"Open {(args.output / 'report.html').resolve()}")
    return report


if __name__ == "__main__":
    main()
