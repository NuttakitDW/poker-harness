# Tier 1 ICM chart — how to run it, and what it is allowed to say

`bowling` (PI). Last updated 2026-09-28. Design and rationale: `../open3bet-design.md` (§§6b, 15-17
are the live ones). Findings that constrain this deliverable:
`../../findings/bowling-grid-provenance.md`, `bowling-chart-claim-language.md`,
`bowling-tier1-chart-format-blocker.md`, `burch-tier1-flop-gap.md`.

## What it is

An open-or-jam chart with ICM payouts: 80 cells = 2 structures (`small` 300 runners / 45 paid,
`big` 1500 runners) x 2 stages (`bubble` = 46 left, `past` = 90 left) x 4 table sizes (n = 2, 3, 6,
9) x 5 stacks (8, 12, 15, 20, 30bb). Equal stacks, sb 0.5 / bb 1, no ante, `fee = 0`,
`cap = 3` (at most 3 players hold cards when preflop ends), `tier1=True`.

Tier 1 action set: unopened {fold, open 2.2bb, all-in}; facing a raise {fold, all-in}; facing an
all-in {fold, call}. **No flat and no 3bet** -- that is the Tier 1.5 gap, see `open3bet-design.md`
§15. At equal stacks every ending is a fold, an uncontested raise or an all-in showdown, so no flop
leaf is consulted; the tree still contains FLOP terminals at *unequal* stacks, which is why the grid
is equal-stack only (`bowling-tier1-flop-gap.md`, resolved by burch).

## Run it

```
cd /Users/nuttakit/project/poker-harness
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bowling/tier1chart/grid.py
```

Resumable: each cell is written as its own `cells/<key>.json` + `.npz` and skipped if present, so
re-running continues rather than restarts. ~4-6h for the whole grid from cold; the `n=9` cells
dominate (~494 nodes, up to ~25 min each) and the `n=2`/`n=3` cells take seconds.

Stop rule: `target_for(n, stack)` = **`EPS_N2[stack]` at n=2, `MODEL_FIDELITY[n]` at n>=3**, with
`check_every=25`, `max_iters=20000`, `method="cfr+"`, auditor `fasticm3.FastAuditor`.

This is the "floor vs ceiling" rule of `../open3bet-design.md` §11, **per cell** rather than global.
Two measured bars decide it, and the larger one binds:

| | n=2 | n=3 | n=6 | n=9 |
|---|---|---|---|---|
| model's own error (`johanson-model-vs-real-gap.md`) | ~0 (exact HU pricing) | 0.0055 | 0.0075 | 0.0119 |
| lifetime eps (`davis-grid-sigma.md` §2) | 0.00059-0.00099 by stack | 0.0005-0.0010 | 0.0004-0.0009 | ~0.0004-0.0011 |
| **target** | lifetime eps | model error | model error | model error |

At n=2 heads-up pricing is exact, so the lifetime bar binds and the target is the per-stack eps
(0.00059 at 8bb rising to 0.00099 at 30bb). At n>=3 the model's own error is 5-20x the lifetime eps,
so **the lifetime bar is not achievable at all** -- solving finer than the model error converges on
the wrong game. `verify_cells.py` enforces it: no cell may carry a `target` looser than its bar, and
a *tighter* target is allowed (older cells are, and are marked over-solved).

It changes **no claim** -- the n>=3 copy already said the real figure is ~10-40x the stop rule.

**Two corrections to earlier versions of this file, both from teammates.** (1) I first set 0.002 at
n>=3 as a "conservative margin" below johanson's n=3 figure; he then measured n=6 and n=9 and the
error *grows* with seat count, so a single value for all n>=3 is wrong in the safe direction and the
per-n values are used instead. (2) davis's eps are **per cell**, 0.408-1.491 mICM/hand, a 3.7x
spread driven by stack, not the single 0.0006 I had been using -- which was too loose for the 8bb
cells and too tight for the 30bb ones.

## The one rule: a cell is quotable only if it matches the run

`deepstack-swarm/workspace/` is **untracked by git**, so `commit: b75e315` in a cell pins
`pushfold/` and nothing about the solver. Every cell therefore carries:

- `code_fingerprint` + `code` — SHA-256[:12] of all 13 modules on the solve path
- `build`, `cap`, `stacks` — **a file hash cannot distinguish `behind_cap=None` from
  `behind_cap=1`** when both live in `floor3.py`, so the kwargs are recorded per cell
- `counts` — terminal counts, including `flop`, checked as data

The exact code is frozen in `cells/code-<fingerprint>/`. `cells/RUN.json` records the whole plan.

```
.venv/bin/python verify_cells.py          # exits nonzero if any cell is not quotable
```

Checks the required fields per cell against the run manifest, verifies the module digests, fails any
cell with `counts["flop"] != 0`, and fails a `target` looser than the seat count's ceiling. Current
fingerprint **`c371df3b`**.

**Superseded, do not quote:**
- `cells-prev-noprov/` — 41 cells solved across a code change, no provenance at all
- `cells-run3/` — partial, before `build` kwargs were recorded
- `cells-fa654842-partial/` — 12 cells, correct and valid but under the previous fingerprint
  (`floor3.py` moved at 00:25 for burch's Tier 1.5, which is opt-in and default-off, so the default
  path is behaviourally identical; the hash moved anyway, and one artifact beats twelve good cells)

A fingerprint move is not evidence of a behaviour change — it is evidence that the record would
otherwise have been ambiguous. The frozen snapshot `cells/code-c371df3b/` is what a cell should be
re-run against.

## What the chart may claim, by seat count

The 0.0006 stop rule is a real exploitability **only at heads-up**. At n>=3 the model's own
opponent-dealing error dominates: johanson's exact joint measures a strategy the model calls **1e-6**
exploitable as **5.5e-3** ICM chips/hand exploitable in the real game at n=3 (~9x the stop rule).

| seats | cells | may say |
|---|---|---|
| 2 | 20 | "0.0006 ICM chips/hand exploitability, exact best response in this model" |
| 3, 6, 9 | 60 | "solved to a 0.0006 stop rule **in a model**; ~10-40x that in the real game" |

So do not print one footer for all table sizes -- `export_chart.py` attaches the right sentence per
cell. And at n>=3, two charts differing by less than ~0.006 ICM chips/hand are **not
distinguishable** by this pipeline however converged both are. Detail and caveats:
`../../findings/bowling-chart-claim-language.md`.

## Serve it

```
.venv/bin/python export_chart.py small bubble 2 15    # one cell, JSON to stdout
.venv/bin/python export_chart.py --all                # every solved cell -> charts/
```

Per cell: `meta` (structure, stage, seats, stack, crowd, paid, `target`, `unit`,
`code_fingerprint`), `claim` (the sentence that cell is allowed to make), `leaves` (terminal
counts), and `nodes` -- **every** decision node for **every** seat, each with `context`
(`unopened` / `facing N raise(s)` / `facing all-in`), the raw `actions`, their four-letter `codes`,
and per-hand shares over the 169 classes.

Four codes, not three: `F` fold, `R` non-all-in raise, `J` all-in, `C` call.

## Known blocker: the shipped renderer cannot draw this

`scripts/voice/chart_grid.py:29` fixes the vocabulary at three codes
(`{"raise": "R", "call": "C", "fold": "F"}`) and resolves anything unknown to **fold**; its producer
`pushfold_chart._cells` is binary (`code = "C" if action == "call" else "R"`, 0.5 threshold) and
names that one raise code `"shove"`. Fed a Tier 1 cell, an open and a jam come out as the same
letter printed as **shove** -- the chart would tell users to shove hands the solver min-raises.

`render.py` is a working four-code renderer demonstrating the fix (`F`/`R`/`J`/`C`, no silent
fallback). The change needed is a fourth code in `chart_grid.py` plus a non-binary producer; it is
specified in `bowling-tier1-chart-format-blocker.md` but **not applied** -- `scripts/` is outside
the swarm's write scope.

## Cost, and the target lever if the grid must finish sooner

Timed: `n=2` under a second; `n=3` 25-80s; **`n=6` 824s at target 0.0006, 220s at 0.002** (5000 vs
1850 iters); **`n=9` 554s at 0.0055** (494 nodes). Full grid from cold at the per-cell target is
**~2h**, dominated by the 10 `n=9` cells.

**Tier 1.5 is much more expensive and that matters for the next build** (`burch-tier1.5.md`): at
30bb, Tier 1.5 converges ~100x slower than Tier 1 (~1.4e5 iterations to reach 0.001 at n=3), because
it is the first game here where a seat acts twice on a path. At 15bb it is cheap (n=6: 1225 iters /
191s). Do not ship a deep-stack Tier 1.5 cell without its iteration history.

**Why n>=3 is not solved to 0.0006.** That cost would be out of proportion to what it buys.
johanson's exact joint measures the model's *own* error at n=3 as **5.5e-3** — about 9x the stop
rule — so solving 60 cells to 0.0006 refines the wrong thing: the solve converges, the chart does
not get more correct, and it costs 3.7x the time. The rule applied is

    target(n) = min(lifetime eps, model fidelity at n seats)

which is the "floor vs ceiling" rule from `../open3bet-design.md` §11, per seat count instead of
globally. **This changes no claim**: at n>=3 the chart already says "solved to a stop rule in a
model whose real figure is ~10-40x larger", and 0.002 vs 0.0006 is invisible under that sentence.
Cells solved earlier at the global 0.0006 are *tighter* than required and were valid; they were
re-solved anyway only to keep the artifact on one fingerprint.

Residual risk, stated: 5.5e-3 is **one spot at one seat count**. If the model error *shrinks* with
seat count, 0.002 would be too loose at n=6/n=9. The direction of the risk is that card-removal
error grows with the number of independently dealt opponents, so n=6/n=9 are unlikely to be better
than n=3 — but that is an argument, not a measurement, which is why lisy is measuring it. If his
bound disagrees, the `n>=6` cells are the ones to re-solve, and `target_for` is the one line to
change.

## Open items

- **`davis`**: is `TARGET = 0.0006` right for the `past` stage (90 left) as well as the bubble? The
  ε was measured at the bubble only; past the money the ladder is flatter so ε is probably *lower*,
  which would mean the 40 `past` cells are under-solved rather than wrong. `open3bet-design.md` §17.
- **`lisy`**: lower bound on real-game exploitability at n=6 and n=9, validated against johanson's
  n=3 exact figure. Determines whether the gap grows with seat count.
- **`waugh`**: abstraction pathologies in the 169-class / cap-3 model.
- **`burch`**: Tier 1.5 (add the 3bet) -- will move the `floor3.py` hash; that is fine, the snapshot
  is frozen, but do not expect a new build to hash to `fa654842`.
