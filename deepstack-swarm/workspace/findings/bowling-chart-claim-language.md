# What the shipped ICM chart may say, by seat count

`bowling` (PI), 2026-09-28. **Status: derived from measured numbers already in the repo, not a new
measurement.** Nothing in `pushfold/` edited. This file exists so the product copy cannot drift from
the evidence.

**Claim in one sentence.** The Tier 1 grid's headline "0.0006 ICM chips/hand" is a real
exploitability **only at heads-up**; at 3, 6 and 9 seats it is a solve-to-target *inside a model*
whose own seat-level pricing error is ~40× larger, so the chart must carry a different sentence per
seat count, not one sentence overall.

**Game.** NLHE, preflop only, Tier 1 action set (`floor3.build(..., tier1=True)`), cap 3 at most 3
players with cards at the end of preflop, `fee = 0`, ICM payouts (Malmuth-Harville scaled to chips),
sb 0.5 / bb 1, no ante, equal stacks 8/12/15/20/30bb. Unit: ICM chips/hand.

## The numbers being combined

**Correction, 2026-09-28.** This file was written when the grid used a single `target = 0.0006`,
inherited from the bubble spot. `davis-grid-sigma.md` then measured ε on 47 cells and it is **not a
constant**: 0.408-1.491 mICM/hand, a 3.7x spread driven by stack (x2.2 from 8bb to 30bb), not by
structure. So wherever this file says "0.0006", read "the cell's own ε, between 0.0004 and 0.0015".
The seat-count argument below is unaffected — it turns on the *model* error, which is 5-20x ε
wherever ε lands in that range. The grid now uses `target(n, stack)`; see `tier1chart/README.md`.

| quantity | value | source |
|---|---|---|
| lifetime ε at the bubble, 6-max 10bb | 0.000628 ICM chips/hand | `davis-lifetime-eps.md` §2 |
| lifetime ε over 47 grid cells | **0.000408-0.001491**, by stack | `davis-grid-sigma.md` §2 |
| grid `target` | `target(n, stack)` | `tier1chart/grid.py` |
| Monte Carlo `eq3`/`pw` noise (2000 samples) | moves the chart 0.06-0.11% dTV, exploitability ~0.0001 -> ~6x **below** ε | `davis-lifetime-eps.md`, §12 item 1 here |
| independent-deal pricing error at 3+ seats | up to **0.026 ICM chips/hand = 40x ε** | `davis-lifetime-eps.md` §6, `open3bet-design.md` §12 item 2 |
| **measured** model vs real gap, n=3 exact | **0.0024-0.0121 ICM chips/hand**, varying with stack and stage | `johanson`, exact joint, revised 2026-09-28 |

**Revision, 2026-09-28.** Two corrections from johanson supersede the version of this file that
quoted "5.5e-3 at n=3" and a "~10-40x" multiple:

1. **The multiple is unbounded and must be dropped.** The denominator keeps falling as the solver
   iterates while the real gap stays flat, so the same chart gives 88x at 400 iterations and 8538x
   at 6400 (`curve3.py`). A ratio between an unbounded denominator and a fixed numerator carries no
   information. Quote the **absolute gap**.
2. **5.5e-3 was one cell, not the seat count.** Over the whole n=3 exact range the gap is
   **0.0035 (8bb) -> 0.0121 (30bb)** and **0.0024 (3 left) -> 0.0070 (bubble, 5-6 left) -> 0.0033
   (12 left)** -- about **5x within n=3 alone**, largest near the bubble and at deeper stacks. So
   the per-seat-count rows below are **too coarse**; the range is the honest unit.

3. **n=9 is not the weakest cell.** The max-seat gap over n=3..9 at 15bb is
   0.0061/0.0088/0.0122/0.0131/0.0115/0.0121/0.0131 -- it **saturates at n~5**. The sum over seats
   grows roughly linearly (0.0079 -> 0.0690), so that statement is true only if the quantity quoted
   is NashConv rather than the worst seat. This is a solution-concept choice, and it is `morrill`'s.

The last row is the direct measurement and it replaces the estimate above it. `johanson`'s exact
joint (all 1326 combos, card removal, regression now green) finds that a strategy the model calls
1e-6 exploitable is **5.5e-3** exploitable in the real game at n=3 ICM -- roughly **9x the 0.0006
stop rule**. davis's 0.026 was a worst-case over different spots; the measured figure at this spot is
smaller but the direction and the order of magnitude agree, and both say the same thing: at 3+ seats
the stop rule is far finer than the model's fidelity.

(The multiple in johanson's message, "1850x", does not follow from the two numbers he quotes
(5.5e-3/1e-6 is ~5500x), so I am quoting the measurements and not the ratio until his full finding
lands. The ratio depends on which model figure is the denominator and that is not stated.)

The `SAMPLES=2000` row is the one that is *not* the problem: payoff-table noise is ~6x below ε.

## What the chart may claim

| seats | cells | what may be said | what may NOT be said |
|---|---|---|---|
| 2 | 20 | "0.0006 ICM chips/hand exploitability, exact best response in this model" | nothing stronger; the game is still Tier 1, not NLHE |
| 3, 6, 9 | 60 | "solved to the stop rule **in a model** whose own seat-level pricing error is **0.002-0.013 ICM chips/hand** (measured, largest near the bubble and at deeper stacks); the real figure is that error, not the stop rule" | "0.0006 exploitability"; "essentially solved"; any comparison of two n>=3 charts whose difference is under ~0.002 |

So **three-quarters of the grid cannot make the headline claim.** 60 of the 80 cells are n>=3. The
0.0006 figure is a statement about the solver's convergence, and at n>=3 it is 40x finer than the
model's own fidelity -- reporting it alone would be exactly the failure the Cepheus standard warns
about (source 9: say what ε is and in which game it was measured).

This does not require a re-solve. The n>=3 cells are correct and quotable; only the sentence
attached to them changes. The fix for the number itself is card removal in the pricer, which is
agenda item 1 and is with `johanson`.

## Two consequences for the deliverable

1. **Per-seat-count copy, generated from the record.** The seat count is already in every cell, so
   the disclaimer can be attached mechanically rather than remembered. A chart page that renders
   n=6 must not print the same footer as n=2.
2. **A comparison rule.** Any two n>=3 charts whose per-hand difference is below ~0.002 ICM
   chips/hand are **not distinguishable** under this model, however converged both are. That is a
   *looser* bar than the lifetime ε and it should be the one quoted for "chart A vs chart B" at 3+
   seats. Said plainly: at 3+ seats the ranking of two nearby charts is not established by this
   pipeline. 0.002 is the **low end** of johanson's measured range (the 3-left spot); at deeper
   stacks and nearer the bubble the bar is up to 0.013, so this is the conservative end.

3. **A residual in the shipped grid, stated rather than hidden.** The n>=3 stop rule uses a single
   value per seat count (0.002 at n=3), but the bar varies ~5x with stack *within* n=3 -- it is
   0.0035 at 8bb and 0.0121 at 30bb. So the n>=3 **8bb** cells stopped slightly *above* their own
   bar (0.002 vs 0.0035 at n=3) and are marginally under-solved, while the 30bb cells are
   over-solved. This is an efficiency/consistency wrinkle and it changes no claim -- both the stop
   rule and the bar are far inside the model's 0.002-0.013 error band -- but if the grid is ever
   re-solved, the stop rule should be indexed by stack as well as seat count.

## What would change my mind

**Answered 2026-09-28, and it went further than I asked.** `johanson`'s exact joint over all 1326
combos confirmed the direction *and* showed the gap is not a per-seat-count constant: it varies ~5x
with stack and stage within n=3 (0.0024-0.0121). The table above is therefore a coarsening, and the
range in the claim text is the honest unit.

What would still change it: a card-removal-aware pricer (the fix, which follows the measurement)
whose 3+ seat pricing error lands at or below ε, which would let the n>=3 rows inherit the heads-up
sentence. Also unresolved: whether the gap varies with stack and stage the *same way* at n=6 and n=9.
johanson measured the n-series at 15bb only, so the 0.002-0.013 range is anchored at n=3 and assumed
to hold for the higher seat counts. That is an assumption, not a measurement, and it is the one the
claim text is resting on.

## Reproduction

No new command: this file only combines numbers whose commands live in `davis-lifetime-eps.md` §2
and §6 and `open3bet-design.md` §11-12. Verify with
`grep -n "0.026\|40x\|40 x\|independent" workspace/findings/davis-lifetime-eps.md`.
