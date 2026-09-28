# Tier 1.5 under ICM works and is affordable below 30bb; the shipped chart has no 3bet

`bowling` (PI), 2026-09-28. All numbers run by me from the repo root, `.venv/bin/python`; nothing
in `pushfold/` edited. Probe script:
`workspace/bowling/tier1chart/t15_icm_feasibility.py`, raw records in `tier1chart/t15probe/`.

**Claim in one sentence.** `floor3.build(spot, tier15=True)` solves with the **ICM** pricer and is
leaf-free at equal stacks (flop terminals = 0, a seat still acts at most twice), at ~16x the Tier 1
cost at n=3 and ~10x at n=6 15bb — so the half of the user's request that is **missing from the
shipped grid** (the 3bet) is buildable, and the question is a budget decision, not a blocker.

## The gap this closes

The user asked for ICM charts with "open and 3bet actions". The shipped 80-cell grid is **Tier 1**:
unopened {fold, open 2.2bb, all-in}, facing a raise {fold, all-in}, facing an all-in {fold, call}.
**No 3bet.** Tier 1.5 (`open3bet-design.md` Sec 15, built by burch) adds fold/3bet-to-3x/all-in
when facing a raise. burch priced it in **chip EV** (`burch-tier1.5.md`): the 3bet is worth 0.0002
bb/hand at 15bb and 0.041 at 30bb, a 200x growth with depth. This file is the other half: does the
same tree solve with **ICM payouts**, and what does it cost per cell.

## Game

NLHE, preflop only, `cap = 3`, `fee = 0`, sb 0.5 / bb 1, no ante, equal stacks, 169 classes,
`tier15=True`, `method="cfr+"`, `check_every=25`, `max_iters=20000`, stop rule `grid.target_for`
(the same per-cell rule the Tier 1 grid uses: lifetime eps at n=2, model-fidelity target at n>=3).
Setting `small`, stage `bubble` (46 left), ICM payouts 50/30/20 scaled to chips. Unit: ICM chips/hand.

## Result

| n | stack | nodes | terminals | flop | max own decisions | converged | iters | seconds |
|---|---|---|---|---|---|---|---|---|
| 2 | 20bb | 6 | 9 | **0** | 2 | yes | 3075 | **1.5** |
| 3 | 15bb | 24 | 30 | **0** | 2 | yes | 4000 | **39.2** |
| 3 | 30bb | 24 | 30 | **0** | 2 | yes | 4875 | **50.4** |
| 6 | 15bb | 286 | 307 | **0** | 2 | yes | 2050 | **191.4** |
| 6 | 30bb | 286 | 307 | **0** | 2 | yes | 4850 | **495.9** |

Command (one cell per line, `n stack target`):

```
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bowling/tier1chart/t15_icm_feasibility.py 3 15 0.002
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bowling/tier1chart/t15_icm_feasibility.py 3 30 0.002
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bowling/tier1chart/t15_icm_feasibility.py 6 15 0.0075
```

**The leaf-free check is data, not an argument.** Every cell reports `counts["flop"] == 0`. That is
the same terminal census `verify_cells.py` enforces on the Tier 1 grid, and it is what makes the
ICM pricing exact rather than a flop-value approximation: at equal stacks the 3bet does not create a
new kind of ending, it only adds a decision on paths that already ended in fold/uncontested/showdown.
Confirmed for n=3 (24 nodes) and n=6 (286 nodes), both with `depth_of_own_decisions() == 2`.

**Cost against the shipped Tier 1 grid**, same n, same stage, same stop rule:

| | Tier 1 | Tier 1.5 | ratio |
|---|---|---|---|
| n=3 15bb | ~2.5s | 39.2s | ~16x |
| n=3 30bb | ~5s | 50.4s | ~10x |
| n=6 15bb | ~20s | 191.4s | ~10x |
| n=6 30bb | ~20s | 495.9s | ~25x |

The ratio is depth-dependent, as burch found in chip EV: at 15bb a 3bet is close to a commitment so
fold/shove already spans the decision and the extra branch is cheap; at 30bb the seat uses it
(burch: 22-37% of hands) and the extra branch buys a decision the solver actually spends iterations
on. **The n=3 30bb ICM cell needed only 4875 iterations**, nowhere near the ~1.4e5 burch needed in
chip EV at a 0.001 target — the difference is the target and the stop rule, not the payouts.

**n=9 is not measured.** Extrapolating the 24 -> 286 node jump (n=3 -> n=6) would put an n=9 cell
in the 1000-node range and each 30bb cell around 30-60 minutes. That is an extrapolation and should
be replaced by a measurement before anyone schedules a full grid.

## Note on n=6 30bb (measured, 2026-09-28)

**8.3 minutes** — 4850 iterations to the 0.0075 stop rule at 286 nodes. This is **much cheaper than
burch's chip-EV reading predicted** and the prediction was mine, not his: I wrote that "burch's
~1.4e5 iterations at n=3 30bb points at tens of minutes, possibly hours". Two things make the ICM
cell 30x cheaper than that arithmetic — the target (0.002/0.0075 here vs 0.001 there) and, more
importantly, **the stop rule differs**: burch was measuring how long Tier 1.5 takes to reach a
*fixed* 0.001, which is a tail measurement, while this cell stops at the model's own fidelity at
n=6 (0.0075), which is 7.5x looser. The correction is worth stating because a bad cost estimate is
exactly the kind of thing that gets a chart cancelled for no reason.

Iteration counts across the four cells: 4000 / 4875 / 2050 / 4850. **Depth does not slow the
iteration count much; it slows the cost per iteration** (24 nodes at n=3 vs 286 at n=6, a 12x
tree for a ~12x wall-clock at matched stack).

## What this does and does not change

- **Does not change the shipped artifact.** The 80 Tier 1 cells stay as they are; `floor3.py`'s
  Tier 1 path is byte-identical (burch verified 7 configurations), so `fingerprint c371df3b` holds.
- **Does change what the deliverable is.** If the user wants a 3bet in the ICM chart, 60 of the
  current cells have to be re-solved in Tier 1.5 — a *different game*, not a refinement. The two
  charts are not comparable cell-for-cell: a Tier 1.5 chart will differ from a Tier 1 chart by the
  value of the 3bet, which is 0.0002 bb/hand at 15bb (below the bar) and 0.041 at 30bb (41x it).
  Said plainly: **at 15bb adding the 3bet changes nothing a player would notice; at 30bb it is the
  single largest thing missing from the chart.**
- **Does not change the seat-count disclaimer.** Tier 1.5 is still 3+ seats at n>=3, still non-zero-
  sum under ICM, still under the same 0.002-0.013 model gap. A Tier 1.5 ICM chart needs the same
  per-seat-count sentence as Tier 1.

## Open item: the n=2 stop rule is borrowed from the wrong game

`grid15.py` reuses `grid.target_for`, so at n=2 the stop rule is `EPS_N2[stack]` — davis's **lifetime
eps measured on Tier 1** heads-up cells (`davis-grid-sigma.md` Sec 2). A lifetime eps comes from the
per-hand standard deviation of results, and Tier 1.5 plays a different strategy (it 3bets), so its
σ is not Tier 1's. At 15bb the difference should be small (the 3bet is rare and near-committing); at
30bb, where burch measures the 3bet in 22-37% of hands and pots get deeper, it is not obviously
small, and using the Tier 1 value could set the bar in the wrong place in either direction.

This affects only the **n=2** cells — at n>=3 the binding bar is the model fidelity, which does not
depend on the strategy. **Not measured; flagged, not fixed.** The right fix is `davis` re-deriving
σ on a Tier 1.5 heads-up cell, and I have asked him. Until then a Tier 1.5 heads-up cell's target
should be read as "Tier 1's lifetime eps, applied by analogy".

## What would change my mind

- A Tier 1.5 ICM cell that is **not** leaf-free (`counts["flop"] > 0`) at equal stacks — none seen
  at n=3 or n=6, but not checked at n=9.
- An n=6 30bb timing that contradicts the "30bb is where it gets expensive" reading.
- A Tier 1.5 chart whose ICM ranking of two nearby hands differs from Tier 1's by less than the
  0.002-0.013 model gap — that would say the 3bet is not resolvable at n>=3 either, and the honest
  move would be to ship Tier 1 and say so.

## Reproduction

```
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bowling/tier1chart/t15_icm_feasibility.py <n> <stack> <target>
```
Writes `tier1chart/t15probe/t15-n<n>-<stack>bb-t<target>.json` and prints the record.

## The driver, if the build is approved

`tier1chart/grid15.py` is the Tier 1.5 counterpart of the frozen `grid.py`: same driver, same
provenance (`code_fingerprint` + per-cell `code` digests + `build` kwargs), its own `cells15/` so
the two artifacts cannot be mixed, and the same `grid.target_for` stop rule. **Its default plan is
the 20bb and 30bb rows only** (32 cells) for the reason in "The gap this closes"; `--all` runs the
full 80 and `--stacks 15 30` picks a row. Smoke-tested on the heads-up 20bb cell (6 nodes, 1.5s,
converged, `flop = 0`). Not run as a grid — that is a budget decision for the user, and it is the
one thing in this file I am deliberately leaving unexecuted.

**Note that a Tier 1.5 grid is a new fingerprint.** `floor3.py` is on the solve path and the Tier 1
snapshot `cells/code-c371df3b/` is frozen; a Tier 1.5 run will record whatever the current digests
are, which is why it writes its own `RUN.json`. Verify the two `RUN.json` files agree on the
modules they share before comparing any cell across the two grids.
