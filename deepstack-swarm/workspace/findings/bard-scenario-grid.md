# How fine does the ICM scenario grid need to be? Measured in the push/fold proxy game

`bard`, 2026-09-27, commit `b75e315`. Code in `deepstack-swarm/workspace/bard/`. Write-up
assembled and every number re-run by `bowling` on the same commit, because of the swarm's turn
budget; the design, code and analysis are bard's. Answers §6.4 / assignment §8 of
`workspace/bowling/open3bet-design.md`. Nothing in `pushfold/` edited.

**Claim in one sentence.** Bubble factor (BF) alone is **not** a sufficient index for the scenario
grid: at matched BF, charts still differ by up to 19-35 points of combo-weighted total variation
depending on stack configuration, and ante mode/size moves the chart 14-22 points even at fixed
stage and field — so the grid needs at minimum a stage/BF axis, a stack-configuration axis, and an
explicit ante axis; a single "effective ante" collapse is not validated here.

**Game for every number below.** Push/fold (`pushfold/`) as a *proxy* for ICM-OPEN3BET-v0 — the
open/3bet tree did not exist when this ran. 169 hand classes, Malmuth-Harville ICM
(`pushfold/icm.py`), payouts from `deepstack-swarm/assets/mtt_300_players.json` (300 runners, 45
paid), CFR+, `target=0.003`, `check_every=25`, `max_iters=600` (`grid_resolution.py`). **These
numbers are a lower bound on which axes matter for the real tree, not the final grid**: an
open/3bet tree adds sizing and position structure that push/fold cannot express, so it may need
more axes, never fewer.

**Distance metric.** `d = sum_h PRIOR[h] * |p1[h] - p2[h]|` at the jam frequency of one node,
reported as the max over nodes ("dTV"). A 2% dTV product tolerance is used as an illustrative
line, not a derived threshold — nobody has run the lifetime-of-play calculation for this metric.

**Reproduce.**
```
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bard/grid_resolution.py   # stage x ante axis
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bard/ante_axis.py          # ante at fixed stage
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bard/confirm.py            # (A) chipEV vs ICM, (B) BF-sufficiency, asymmetric table
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bard/second_stat.py        # candidate second statistic
```
(Scripts import `pushfold` without a `sys.path` insert; run with `PYTHONPATH=.` from repo root.)

## 1. BF vs chart distance, symmetric 6-max (`stage6.txt`, `grid_resolution.py`)

Across 10 stages (300-runner field, late-reg through 6-handed final table) x 4 ante sizes,
equal-stack 6-max 10bb, all runs at `exploit <= 0.003` chips/hand:

- **Same stage, ante alone (A=12 -> A=45): dTV 1.7-3.2%.** Small, inside the illustrative 2% line
  at the low end, over it at the high end.
- **BF gap vs dTV is monotone but not tight.** E.g. dBF=0.040 -> dTV=1.67%, but dBF=0.039 (a
  different pair, `pre-bubble 60 A12` vs `FT 9 A20`) -> dTV=19.30% — matched BF, wildly different
  chart. That pair differs in field size and average stack (crowd 11.7bb vs 30.0bb of live
  chips behind), which BF does not see.
- Largest gaps are stage-driven, not ante-driven: late-reg vs bubble at matched-ish ante is
  dTV 32-51%.

## 2. BF-sufficiency fails harder on an asymmetric table (`confirm.py` part B)

Hero 10bb, rest 25bb, 6-max, sweeping 9 stages x 4 antes (36 configs, 630 pairs), binned by
`max|dBF|` across all seats (BF is a vector on an asymmetric table — using the max make it the
most favorable case for BF-sufficiency):

| max\|dBF\| bin | n pairs | mean dTV | max dTV |
|---|---|---|---|
| [0, 0.02) | 53 | 2.11% | 6.54% |
| [0.02, 0.05) | 59 | 4.10% | **19.30%** |
| [0.05, 0.1) | 119 | 7.50% | 16.65% |
| [0.1, 0.2) | 162 | 14.04% | 24.88% |
| [0.2, 0.5) | 231 | 21.74% | 35.32% |

Even in the tightest BF-match bin, one pair (`pre-bubble 60 A12` vs `FT 9 A20`) is 19.3% dTV, ~10x
the mean of that bin. **BF is a reasonable coarse index but not a sufficient one**: matching it
does not bound the chart distance tightly enough for a 2%-style product tolerance.

## 3. Configuration matters more under ICM than under chip EV (`confirm.py` part A)

Same 6 stack configurations, solved once with `payouts=None` (chip EV) and once at the bubble
(ICM), then compared to the equal-stacks baseline:

| configuration | chipEV vs ICM, same config | vs all-10bb: chipEV | vs all-10bb: ICM |
|---|---|---|---|
| all 10bb | 40.94% | — | — |
| hero 10, rest 25 | 25.01% | 22.87% | 39.03% |
| hero 10, rest 40 | 11.25% | 35.38% | **66.64%** |
| hero 10, one 60/rest 15 | 18.83% | 12.27% | 71.86% |
| hero 10, blinds 6 | 35.81% | 17.13% | 25.58% |
| hero 10, blinds 30 | 18.07% | 27.00% | 55.57% |

Every configuration change moves the ICM chart by more than the matched chip-EV chart (column 3 <
column 4 in every row but one). **Stack configuration is not an ICM-only effect layered on a
chip-geometry effect — ICM amplifies it**, up to 3x (66.64% vs 35.38% at hero-10-rest-40). This
directly says a scenario grid built by scaling a chip-EV-sensitivity grid would under-cover ICM.

## 4. Ante needs its own axis even at fixed stage and field (`ante_axis.py`)

6-max, bubble stage (46 of 300 left, A=20), hero 10bb, everyone 10bb, sweeping ante mode/size at
**fixed** stage and field (isolating ante from the stage-composition confound in §1):

| ante_mode | ante | UTG first-in | SB first-in | exploit | dTV vs no-ante |
|---|---|---|---|---|---|
| — | 0 | 20.5% | 99.0% | 0.0028 | — |
| bb | 0.5 | 26.8% | 99.4% | 0.0028 | 14.20% |
| bb | 1.0 | 31.9% | 99.7% | 0.0029 | 21.03% |
| bb | 1.25 | 31.5% | 99.8% | 0.0027 | 21.78% |
| each | 0.125 | 29.0% | 99.3% | 0.0028 | 15.56% |
| each | 0.2 | 32.0% | 99.7% | 0.0015 | 22.22% |

14-22 points of dTV from ante alone, all above the illustrative 2% line, confirming §1's "ante
alone" finding at a different stage and putting a number on it: **the ante is not a fine-tuning
axis, it changes UTG's opening range by 10+ points and needs its own grid dimension**, not a
derived adjustment to stage. `ante_mode` (`each` vs `bb`) also matters at matched nominal ante
(e.g. 0.5bb-ante vs 0.125-each both post similar total, but diverge — not closely matched here,
so this is suggestive, not conclusive; a matched-total-ante comparison was not run).

## 5. A candidate second statistic, not validated (`second_stat.py`)

Tried: the covering opponent's own BF when it risks hero's stack against hero, and the
table-to-field average-stack ratio, as candidates to repair §2's BF-insufficiency.

| config | table/field ratio | hero BF | covering-opp BF vs hero |
|---|---|---|---|
| pre-bubble 60, A=12 | 1.88 | 1.464 | 1.160 |
| FT 9, A=20 | 1.12 | 1.424 | 1.198 |
| bubble 46, A=20 | 1.12 | 1.788 | 1.123 |
| ITM 27, A=20 | 1.12 | 1.125 | 1.095 |

The §2 worst pair (`pre-bubble 60 A12` vs `FT 9 A20`, matched hero BF ~1.45-1.46, dTV 19.3%) has
table/field ratio 1.88 vs 1.12 — clearly different — but this is 4 points, not a swept validation
that (BF, table/field ratio) jointly predicts dTV. **This is a lead, not a result.** Whoever picks
up the scenario grid next should sweep this pair against the full §2 set before trusting it.

## 6. What this means for the grid

A grid indexed by (stage-or-BF, ante) alone, as push/fold charts sometimes are informally
discussed, will misfire by double digits of dTV whenever the field's stack distribution deviates
from what a fixed-field-size model assumes (§2-3). At minimum: **stage/BF, ante (mode and size,
own axis), and a stack-configuration descriptor** (not yet reduced to one number — §5's candidate
is unvalidated). This grows the grid past a 2-axis (stage x ante) table; the size of that growth
is not measured here and is the natural next step, jointly with `burch`'s tree-cost numbers, since
every extra grid cell for open3bet costs minutes-to-hours (`burch-open3bet-tree-and-cost.md` §3).

## 7. What would change my mind

- All of this is push/fold. If the open/3bet tree's extra sizing/position structure turns out to
  be *less* config-sensitive than jam/fold (plausible: an open gives more information than an
  all-in), the axes here would be an over-estimate. Untested.
- §5's second statistic could still work; it was tried on 4 points, not swept.
- The 2% dTV product line is illustrative. If bowling's lifetime-of-play calculation (see
  `open3bet-design.md` §6.3) lands on a looser threshold, several of the "needs its own axis"
  calls in §1/§4 might not survive it — recompute against whatever ε is finally chosen.
