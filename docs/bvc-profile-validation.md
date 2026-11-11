# BVC advisory adaptation — November 11, 2026

## Selection and scope

Bitcoin Video Casino is the documented integration candidate for this saved project.
Its official API explicitly covers blackjack and permits applications/bots without
prior API permission. That API document is dated December 31, 2013; it is not proof
that an unattended client works today. The public rules endpoint was separately
opened in a browser on November 11, 2026 and its response is preserved in
`fixtures/bvc-rules-2026-11-11.json`.

The change reuses the existing desktop advisor and OCR pipeline. It adds a profile,
no-peek strategy adjustments, round-wide split budget, and public rules validator.
It does not connect an account or perform any casino action. No casino hands were
dealt during verification. No positive expected return or Ontario eligibility has
been established. The documented permission to build an API client does not establish
either of those facts.

## Important differences from the old default

| Situation | American-peek default | BVC preset |
|---|---|---|
| Hard 11 versus dealer 10 | Double when available | Hit |
| Pair of 8s versus 10 or ace | Split when available | Hit |
| Pair of aces versus ace | Split when available | Hit |
| Pair of aces versus 10 | Split when available | Split when available |
| Three splits already used | Manually controlled | Further splitting blocked |
| Split aces cannot profitably resplit | One-card restriction | Stand after their one card |
| Cards from prior rounds | Separate manually reviewed shoe count | Count disabled and cleared |

The strategy is a total-dependent basic-strategy table with the published no-peek
adjustments, not an exact composition-dependent five-deck solver. No-peek support is
explicitly limited to S17, no surrender, and loss of all bets on dealer blackjack.
Unknown original-bet-only settlement cannot silently use this strategy.

## Verification

- `python -m pytest -q`: 781 passed, 24 subtests passed on Linux/Python 3.12.
- `python -m flake8 . --exclude=.venv --max-complexity=10 --max-line-length=127 --statistics`: passed.
- `python blackjack_bvc.py --rules-file fixtures/bvc-rules-2026-11-11.json`: compatible.
- Table regression covers 320 BVC situations plus original strategy tests; split-state,
  disabled actions, rule drift, settings reload, and GUI count isolation are checked.
- The public endpoint returned HTTP 403 to this execution environment's direct HTTP
  request. Browser retrieval succeeded. The CLI network path was tested with a mocked
  response; it has not been validated from the user's Windows computer.

The old Q-learning lab is deliberately not relabeled or retrained as BVC. Its infinite
deck, dealer-peek and one-split assumptions differ. Future demo integration needs an
actual response replay/state machine and finite-deck simulator with correct settlement,
then an end-to-end test-credit session. Neither is represented as completed here.

## Sources

- [Official API and blackjack rule-field definitions](https://bitcoinvideocasino.com/api)
- [Public rules endpoint](https://bitcoinvideocasino.com/blackjack/ruleset)
- [Shackleford's no-peek strategy analysis](https://wizardofodds.com/ask-the-wizard/blackjack/no-peek/)
- [Original multi-deck strategy reference](https://wizardofodds.com/games/blackjack/strategy/4-decks/)
