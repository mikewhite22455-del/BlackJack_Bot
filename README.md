# Blackjack Assistant

A desktop hand advisor with manual entry, calibrated player/dealer OCR,
background monitoring, and a separate reviewed Hi-Lo count panel.

## Start on Windows

1. Install Python 3.10 or newer from https://www.python.org/downloads/.
2. Download this repository using **Code > Download ZIP**, then extract it.
3. Double-click **Start_Blackjack_Windows.bat**. It creates a local Python
   environment, installs dependencies, and opens the app.
4. Manual hand entry works immediately. For screen reading, install the
   Tesseract application using the Windows options documented at
   https://tesseract-ocr.github.io/tessdoc/Installation.html.
   The app checks PATH and the usual Program Files installation folders.
   A custom location can be supplied using the `TESSERACT_CMD` environment variable.

Other systems can run:

```sh
python -m pip install -r requirements.txt
python blackjack_bot.py
```

macOS may require screen-recording permission. Unsupported capture environments
show an error and retain manual entry.

## Hand Advisor

1. Select S17 or H17, double-after-split and late-surrender rules. Confirm that
   the table uses **4-8 decks, American dealer peek, and doubling on any initial
   two cards**. Other rule families (European no-hole-card, single- or double-
   deck, Spanish 21, early surrender) are outside the supported strategy.
2. Enter your current hand, such as `A, 7`, and the dealer's visible upcard.
   The advisor computes hard/soft totals and hit, stand, double, split or late
   surrender advice. It recognizes blackjack and busts.
3. Update **Can double**, **Can split**, **Hand after split**, and split-ace
   restrictions to match the actions currently available. When managing a
   split, enter or scan only the active hand. Advice does not use count deviations.

The strategy is a total-dependent 4-8 deck reference implementation, checked
against Michael Shackleford's published S17/H17 strategy:
https://wizardofodds.com/games/blackjack/strategy/4-decks/.
It does not promise profits or automate game actions.

## Screen-reading setup

1. Keep the advisor away from the table cards and choose the correct monitor.
2. Click **Select rank** for the dealer upcard and each current player card.
   Drag a tight box around **one upright rank**, excluding suits, text, the
   opposite corner, and other cards. Escape cancels selection.
3. Click **Read hand twice** for a single observation, or **Start monitoring**
   for repeated background reads. Two matching complete readings are required.
   Ambiguous, low-confidence, failed, or changed readings withhold advice.
4. Verify the displayed ranks against the table. After a hit, add a player-card
   box for the new card. Re-select boxes whenever cards move, the browser
   zoom changes, or the table layout changes. Only the configured boxes are read;
   cards outside them cannot be detected. There is no automatic game-state or
   round recognition. Press **New Round** only after the previous cards clear.
5. Use **Save table setup** to remember the coordinates and rule preferences.
   Rule confirmation and monitoring are never automatically restored.

The crop logic handles display scaling and rejects saved screen layouts that
no longer match. OCR runs locally in a background worker with timeouts, keeping
the UI responsive. No screenshots or card histories are uploaded or saved.
The setup still needs calibration and validation on the actual table: synthetic
OCR tests are not evidence of accuracy on a particular casino's card artwork.

## Shoe Count

Enter the entire reviewed visible table snapshot, e.g. `10, A, 5, 5`, or read a
configured table area and correct the OCR result before applying it. Repeated
snapshots, reordering and temporary disappearance do not recount ranks. Use
**New Round** after the table clears; the shoe count is retained. **New Shoe**
resets the count; set the estimated decks remaining manually.

Hand Advisor reads do not automatically enter this count: it should include
all exposed cards, not just the active player hand. The counter tracks the
highest observed quantity of each rank per round, not individual card identities.
An incorrect applied snapshot can corrupt the count; restart the shoe count if
one was applied. The unit schedule retains the original 1/2/4/6/8/10 mapping,
using the lower whole-count tier for fractional counts. Units are not dollars.

## Validation

```sh
python -m pip install pytest flake8
python -m pytest -q
python -m flake8 . --exclude=.venv --max-complexity=10 --max-line-length=127
```

CI runs on Windows and Linux. Linux installs Tesseract and exercises real OCR
on generated rank images, including the background worker-to-advice flow.
On machines without Tesseract, those image integration tests are explicitly
skipped; strategy, counting, confidence, calibration and GUI tests still run.
