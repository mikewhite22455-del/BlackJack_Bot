# Blackjack Assistant

This is a desktop **count-review prototype**. Player/dealer recognition and
play advice are not implemented. It does not place bets or click a game.

## Run

Use Python 3.10 or newer:

```sh
python -m pip install -r requirements.txt
python blackjack_bot.py
```

Screen reading also requires the Tesseract OCR application to be installed
and available on PATH. Manual rank entry works without Tesseract.

1. Set the estimated decks remaining; this is a manual estimate.
2. Enter the entire visible card snapshot, e.g. `10, A, 5, 5`.
   Alternatively, configure the card-area pixel coordinates and use **Read
   card area for review**. Keep other text and this window outside that area.
3. Correct the ranks before clicking **Apply reviewed snapshot**.
4. Apply subsequent complete snapshots as cards are added. Repeated snapshots
   and reordered cards do not increment the count again.
5. Once the old cards have been cleared, click **New Round** before recording
   the next hand. This preserves the shoe count. Do not click it while the
   previous hand is still displayed.
6. Use **New Shoe** when the shoe changes and update estimated decks remaining.

The counter keeps the largest observed number of each rank within a round.
This prevents recounting after temporary OCR omissions, but does **not** track
individual physical cards. A mistaken extra rank can corrupt the shoe count;
removed or replaced cards of the same rank cannot be distinguished. Review
every OCR result. For now, restart the shoe count if a mistaken snapshot was
applied. Automatic round detection, card tracking and full hand recognition
remain future work.

The displayed schedule retains the original 1/2/4/6/8/10 unit mapping, with
fractional true counts rounded down to a whole-count tier. Units are not
dollars, and the schedule is not a profitability claim or validated strategy.

## Tests

```sh
python -m pip install pytest flake8
python -m pytest -q
```

The core tests also run without desktop packages using
`python -m unittest -v test_blackjack_bot`.
