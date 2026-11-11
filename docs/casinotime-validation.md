# Casino Time / Pragmatic Play VIP Blackjack

Rules checked on 11 November 2026 against the operator's
[VIP Blackjack guide](https://www.casinotime.ca/blog/how-to-play-vip-blackjack-by-pragmatic-play).
This is a profile of that named game, not every blackjack product on Casino Time.
No authenticated table or player API has been validated.

## Rule coverage

| Detail | Implementation |
|---|---|
| Shoe | Eight standard decks; 416 unique physical cards; draws without replacement |
| Dealer | Stands on soft 17; one shared hand for all occupied seats |
| Main payout | Natural 3:2, ordinary win 1:1, equal totals push |
| Double | Any initial two cards; one additional card; permitted after splitting except aces |
| Split | Equal card values, one split per box; split aces get one card; split 21 is an ordinary 21 |
| Insurance | Ace upcard, half the opening stake, 2:1 net win; followed by dealer blackjack check |
| Dealing | First card to each seat and dealer, then second cards; dealer hole card hidden |
| Shoe change | Finish the round after the cut; early replacement between rounds also supported |
| Side-bet payouts | Perfect Pairs and 21+3 settlement helper tested; no side-bet wagers in practice or benchmarks |

The model uses 1–7 occupied seats. Only seat 1's return is reported in experiments.
Other seats follow the same baseline strategy and affect card consumption. This is
not equivalent to earning the returns of every seat or a Bet Behind integration.
All bets in the benchmark open at one unit; there is no stake progression.

## Details still unverified

| Detail | Current treatment |
|---|---|
| Dealer ten-upcard check and extra-bet settlement | Explicit alternatives: peek, or no peek with all bets lost to dealer blackjack. Other variants are unsupported. |
| Actual cut depth | User-selected assumption; benchmark uses 208 and 312 cards consumed, including burns. Neither is asserted to be the site's depth. |
| Burn count and exposure | Unknown removed cards; benchmark assumes one hidden burn per shoe. |
| Table minimums, maximums and available bankroll | Unit-only model; no monetary limits, funds checks or currency integration. |
| Dealer drawing when every player is bust/natural | Simulator reveals the hole and omits unnecessary draws. Actual table procedure needs observation. |
| Timeout/disconnection | The guide gives conflicting defaults. No live timer, fallback click or disconnection behavior is implemented. |
| Failed double/split, early decisions, multiple seats per account, Bet Behind | No server requests; operational workflows are not implemented. |
| Video artwork, animations and shuffle recognition | Existing rank OCR needs calibration; complete-table recognition and automatic shoe resets are not validated. |
| Online API | No supported player API confirmed. A loopback browser-pixel connection is available; no account or betting API is included. |

The GUI requires an explicit dealer-ten scenario before practice starts. The
legacy advisor withholds ten-upcard advice until that procedure is selected.
Ace-upcard hand advice assumes the insurance/check phase has already finished
without dealer blackjack. A scenario is not evidence that the live table uses it.

## Evidence and calculations

`casinotime_core.py` assigns opaque, stable identities to physical cards. Repeated
observations of one identity do not increment the count. A newly exposed card
with the same rank has its own identity and does count. Conflicting ranks and
impossible rank totals are rejected. A recorded observation gap invalidates
remaining-card probabilities until a new verified shoe.

Hidden burns and the dealer's hole card retain unknown ranks. Their distribution
is integrated out; they are not inserted into the observed Hi-Lo count. Displayed
true count is an estimate from exposed ranks and the physical cards remaining.
The next-card marginal conditions on a negative dealer peek where applicable.
It is a probability distribution under a uniform shuffle, not a predicted card.

`casinotime_rollout.py` receives only public evidence, never the original shuffled
order, hidden rank, or RNG state. It samples a possible hole card, unknown burns
and future ranks, then evaluates each legal current action with basic-strategy
continuations at every seat. Common samples enable paired comparisons. Return is
the net of the whole active seat, including split hands and doubled stakes.
The GUI uses 1,000 samples per action on a cancellable background thread.

Per-action and paired approximate intervals describe Monte Carlo noise. Selecting
the largest sampled mean introduces selection effects; intervals are exploratory
and not adjusted for choosing the winner. This is not exhaustive dynamic
programming or a proven composition-optimal policy. Rollouts use ranks only for
future cards and do not evaluate suit-dependent side bets.

Replay reconstructs a public-card ledger, not an executable complete session.
It does not preserve the current negative-peek condition, so replay probabilities
are explicitly unconditioned. Logs contain no hidden ranks or original RNG seed.

## Completed benchmark

Command, on Python 3.12.14 / Linux:

```sh
python casinotime_lab.py --rounds 25000 --seats 5 --burn-cards 1 --cut-cards 208 312 --dealer-ten both --output casinotime-results-validation
```

Seed starts at 20261111 and increments for each scenario. Five occupied seats,
one assumed hidden burn, fixed one-unit opening stakes, basic strategy, no
insurance or side bets. All data are synthetic. Raw summary:
[casinotime-benchmark.json](casinotime-benchmark.json).

| Ten scenario | Cut position | Rounds | Net units | Net / initial unit | Approx. 95% shoe-cluster interval |
|---|---:|---:|---:|---:|---:|
| Peek | 208 | 25,000 | +42.0 | +0.168% | −1.270% to +1.606% |
| Peek | 312 | 25,000 | +13.5 | +0.054% | −1.398% to +1.506% |
| No peek, all bets | 208 | 25,000 | −176.5 | −0.706% | −2.086% to +0.674% |
| No peek, all bets | 312 | 25,000 | −263.5 | −1.054% | −2.433% to +0.325% |

Every interval includes zero. These runs establish neither an advantage nor a
reliable ranking. Positive paths are sample outcomes. Independent seeds across
scenarios mean this table is not a paired test of rule differences. The cluster
estimate groups dependent rounds by shoe; the final shoe can be partial. It
does not account for rule uncertainty, capture errors, or live-table differences.

The finite-shoe benchmark does not update a learned policy. The existing
`blackjack_lab.py` Q learner remains a separate infinite-deck experiment.

## Verification

```sh
python -m pytest -q
python -m flake8 . --exclude=.venv --max-complexity=10 --max-line-length=127
```

The suite covers duplicate and hidden-card evidence, exact deck composition,
peek-conditioned distributions, cut handling across rounds, insurance, natural
and split payouts, split-ace restrictions, doubles, dealer blackjack, repeatable
shared-dealer simulations, public-view independence from hidden ranks, and GUI
profile persistence. Linux Qt was rendered offscreen; a real Casino Time screen
and Windows desktop have not been exercised in this workspace. CI runs Windows
and Linux. No real-money or casino-account action was performed.

## Live browser capture addition

The desktop app now includes **Live table connection**. `casinotime_bridge.py`
starts only when the user clicks Connect. It serves a capture page from a random
port on 127.0.0.1. The user chooses a browser tab through the browser's own screen
sharing picker. `capture/capture.js` sends JPEG frames at approximately two per
second, scaled to at most 2560 × 1440, to this same-computer receiver.

Requests require a random per-connection token, the exact loopback Host and
same-origin Origin. The server rejects cross-origin requests, unexpected paths,
oversized bodies and invalid images. No casino cookies, passwords, network game
messages or hidden DOM state are accessed. Frames are retained in memory only;
Save calibration image is an explicit user action. Browser sharing transmits no
audio. Disconnect stops the receiver, clears its frame, and rotates its token.

The full selected tab appears in the preview. The existing advisor can read
calibrated rank boxes from that feed, using two agreeing readings from distinct
received frames. The reader checks whether the selected card crops changed while
OCR was running. A stale transport, new sharing stream or changed dimensions
withdraws trust. Saved coordinates do not restore layout or rule confirmation.

This is **pixel transport plus a current-hand reader**, not full-table physical
card recognition. Adding new hit-card boxes, managing split hands, choosing
available actions and resetting rounds still require user input. Whole-table
identity tracking, automatic round/shuffle detection and a betting connector
remain unimplemented. The practice shoe and live pixel stream are not joined.
The browser cannot independently certify the selected casino/table identity;
navigation inside an existing shared tab may retain its stream identifier.
Stop monitoring before changing tables, layouts or browser zoom.

Validation after the addition: 827 tests and 39 subtests passed locally; lint
passed. New coverage includes actual local HTTP frame delivery, token/origin/host
checks, source replacement, stale frames, crop coordinates, changed cards during
OCR, calibration persistence and a JPEG-to-Tesseract-to-advisor integration on
generated ranks. The JavaScript lifecycle tests use mocked browser interfaces,
covering permission denial, frame delivery, stop and connection failure. Qt
screens were rendered offscreen. A real user's browser sharing picker and an
authenticated Casino Time table have not been exercised here; no site-accuracy
or uninterrupted-capture claim follows from generated-image tests.

Browser API references:
[getDisplayMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia),
[screen capture](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Capture_API/Using_Screen_Capture).

## Optional CrewAI specialists

`casinotime_crew.py` defines an evidence auditor, statistical reviewer and
experiment planner. The planner receives the two reviews. The crew receives only
labelled summary data and has no tools or ability to modify the calculation code.
Pydantic output requires synthetic origin and rejects a live-edge claim. These
are review roles, not a collection of agents predicting secret cards.

Create a review brief without installing CrewAI or running a model:

```sh
python casinotime_crew.py casinotime-results/results.json --brief-only
```

For optional model reviews, use a separate Python 3.10–3.13 environment if required
by the installed CrewAI release. Install `requirements-crew.txt`, run Ollama
locally, and explicitly choose an installed model:

```sh
python -m pip install -r requirements-crew.txt
python casinotime_crew.py casinotime-results/results.json --model ollama/YOUR_INSTALLED_MODEL
```

The adapter targets local Ollama at `localhost:11434` with no hosted-model default.
The brief export and payload validation were exercised. No local model is
configured in this workspace; model-backed CrewAI execution remains unverified.
The core simulator and desktop app do not require CrewAI or an AI API key.

CrewAI references: [repository](https://github.com/crewAIInc/crewAI),
[LLMs](https://docs.crewai.com/en/concepts/llms),
[tasks and structured output](https://docs.crewai.com/en/concepts/tasks).
