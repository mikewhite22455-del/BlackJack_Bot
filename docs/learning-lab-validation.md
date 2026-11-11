# Offline learning validation — November 11, 2026

This experiment evaluates the stated IID rule model; it is not a casino audit or a live-casino result.

Command:

```sh
python blackjack_lab.py --train-episodes 2000000 --eval-rounds 200000 --eval-seed 91450231 --output learning-results-validated
```

Training: 2,000,000 uniform state-action decision episodes. Evaluation: 200,000 fresh full rounds per frozen policy.

| Policy | Exact net units / 100 initial bets | Sample net units / 100 initial bets |
| --- | ---: | ---: |
| learned | -0.735344 | -0.685000 |
| reference | -0.571192 | -0.586750 |
| optimal | -0.570388 | -0.277000 |

The learner selected an action within 0.001 units of optimal in 563 of 590 unweighted states.

The learned policy remains worse than basic strategy, and the exact optimal expectation is negative. The existing advisor therefore remains unchanged. A positive short session is not evidence of a positive expected return.

The source rule article describes no resplitting; the model returns approximately 99.4296%, whereas the casino marketing page lists 99.48%. This discrepancy is documented and unresolved.

Checks: 436 tests and 24 subtests passed; repository flake8 checks passed. The tests cover natural payouts and ties, dealer peek conditioning, split/double exposure, split-ace restrictions, stochastic update bias, exact versus sampled probabilities, checkpoint resume and frozen evaluation.

Only the final frozen model is reported here. Earlier development experiments were used to improve action coverage and exposed an outcome-dependent learning-rate bug, which was corrected and covered by a regression test before this run. The final evaluation uses fresh seeds 91450231–91450233.

Source hashes:

```json
{
  "blackjack_lab.py": "f479f0bdaefe910d6c7c26b7bfea20bb6309f15bae730b595b72eecc71012a97",
  "blackjack_lab_game.py": "1ba7f9c497ba5b45328b95571920bdeb6f9a9cc1c199696d96b8cd9f0b2fdddb",
  "blackjack_lab_learning.py": "e380153859be67481791254c8a3cb69e4458c43c20fcc0d0bfc0b586edba1250"
}
```
