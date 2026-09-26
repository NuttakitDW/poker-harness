# GGPoker All-in or Fold (AoF)

- Stable ID: `29-gg-all-in-or-fold`
- Requires: aof, all-in or fold, all in or fold, allin or fold, ออลอินหรือโฟลด์, ออลอินออร์โฟลด์
- Scope: GGPoker's All-in or Fold cash game: blinds, stacks, the fixed per-hand fee and how to solve it as push/fold.
- Thai counterpart: [GGPoker All-in or Fold (AoF)](../../TH/topics/29-gg-all-in-or-fold.md)

## Core idea

All-in or Fold is a GGPoker cash game in which every decision is shove or fold. The lowest Hold'em stake is $0.05/$0.10 at 4-max, with no ante and a $1 buy-in, so everyone starts at 10bb. A seat is often empty, so hands are also played 3-handed or heads-up. Rake is not a share of the pot. Each hand carries fixed fees: at $0.05/$0.10 that is rake 0.06bb, jackpot fee 0.07bb and All-In Fortune $0.007 (0.07bb), about 0.2bb per charged hand in total. Higher stakes pay less in big-blind terms (0.05bb rake plus 0.05bb jackpot from $0.50/$1). The fee is taken outside the pot, so the hand history shows the whole pot going to the winner, with no rake line. Judge your results from your balance or PokerCraft, not from the pots. GGPoker does not say which hands are charged. The solver assumes only players who reach a showdown pay, and that folds or a shove that takes the blinds pay nothing. That makes calling and shoving slightly tighter than no-rake Nash. Half the fee goes back to players as jackpot prizes, which are rare and high-variance.

## Worked example (authored; not quoted from source)

4-handed, 10bb each, CO shoves and it folds to the BB. The pot already holds 11.5bb (CO 10, SB 0.5, BB 1). Calling costs 9bb more, plus the 0.2bb fee. Without the fee the BB needs 9 / 20.5 = 43.9% equity; with it the BB needs 9.2 / 20.5 = 44.9%. The solved chart (`make chart`, then `aof BB vs CO`) calls about 15.5% of hands. The CO first-in shove range at 10bb is about 24%.

## Using the solver

`make chart` or the Discord bot: say `aof` or `all-in or fold` with a seat, e.g. `aof BB vs CO`, `aof 3 handed BTN`, `aof SB 8bb`. The defaults are 4-max, 10bb, no ante and a 0.2bb showdown fee, all changeable. Precompute every chart and export a PDF with `.venv/bin/python scripts/export_aof_charts.py`, which writes to `tmp/aof/`.

## Source pages

[GGPoker All-in or Fold table information](../sources/web/ggpoker-all-in-or-fold.md)

## Related

[Tournament stacks, ICM and push/fold](./13-tournaments-icm-pushfold.md) · [Cash games, microstakes and six-max](./12-cash-microstakes-sixmax.md) · [Equity, pot odds and EV](./04-equity-pot-odds-ev.md) · [Topic index](../INDEX.md)
