# The auditor's number at 3+ seats is not the real-deal number

**The model number is *not* an estimate of the real number. The number to quote is the absolute
per-seat gap: 0.002–0.013 ICM chips/hand (or bb/hand in chip EV), largest near the bubble and at
deeper stacks. At `coach.solve`'s default stop rule at n=3 the model reports 0.0009 (chip) /
0.0020 (ICM) where the real values are 0.0018 / 0.0083. Do not quote a multiple: past
convergence it is unbounded and meaningless — see "The multiple, and why it should not be
quoted".**

Whether the error has a sign in general is not proved here — see "What is exact" for exactly
what the measurement covers.

Signed: Johanson persona (swarm agent). Written 2026-09-28, on repo revision `b75e315`.
`pushfold/` was not modified; every edit is under `deepstack-swarm/workspace/johanson/`.

## Claim in one sentence

A chart solved to `coach.solve`'s default stop rule is 0.0009 (chip, n=3) to 0.0020 (ICM, n=3)
exploitable *in the Pricer's deal model*, but 0.0018 to 0.0083 exploitable *under real dealing*;
solving further drives the model number to ~0 while the real one stops near 0.0019 (chip) /
0.0054 (ICM). Per-seat gaps: 0.0024-0.0088 (n=3, exact, over depth and stage) / up to 0.0075
(n=6) / up to 0.0130 (n=9) ICM chips per hand.

## The games

Push/fold, all-in-or-fold, at most 3 players to a showdown (`floor.MAX_ALLIN`), 169 hand
classes. Chip EV in bb/hand; ICM in ICM chips/hand, the ICM value of the final stack minus the
starting stack (`pushfold/icm_pricer.py` convention). Spots, all in `gap.py`:

| label | seats | stacks | ante | payouts |
|---|---|---|---|---|
| 3max 10bb chip | 3 | 10,10,10 | 0 | chip EV |
| 3max 10bb ICM | 3 | 10,10,10 | 0 | 50/30/20, field (10,) |
| 3max 12/10/8 ICM | 3 | 12,10,8 | 0 | 50/30/20, field (10,)*3 |
| 6max 15bb a1 ICM | 6 | 15 x6 | 1.0 | 50/30/20, field (15,)*3 |
| 9max 15bb ICM | 9 | 15 x9 | 0 | 50/30/20, field (15,)*4 |

The chart is `coach.solve(spot, payouts=..., target=...)` — i.e. solved against the model, which
is what the product does. The **model** number is the auditor's: `seqbr.audit(...).gain`
(`seqbr.py` is an independent re-derivation of `pushfold/auditor.py`; they agree to 5e-6 on
push/fold trees, `check_against_auditor.py`). The **real** number is the same best-response
gain recomputed with the counterfactual values of `cardbr.py` under the real deal.

Units and combination rule: `gain` is per seat in bb/hand or ICM chips/hand. The auditor's
convention is max over seats; that is the number quoted below. Per-seat values are in the
table. NashConv (sum over seats) is not reported because these are chip-conserving spots and
the sum is a different question (Morrill's).

## Command

```
.venv/bin/python deepstack-swarm/workspace/johanson/check_cardbr.py      # regression, exits nonzero on failure
.venv/bin/python deepstack-swarm/workspace/johanson/gap.py --iters 3000 --target 1e-4 --mc 500000 --batches 6
.venv/bin/python deepstack-swarm/workspace/johanson/sweep3.py all    # ratio denominator, depth, stage
.venv/bin/python deepstack-swarm/workspace/johanson/sweepN.py --mc 400000 --batches 4   # the n-series
.venv/bin/python deepstack-swarm/workspace/johanson/stoprule3.py    # what the default rule reports
.venv/bin/python deepstack-swarm/workspace/johanson/check_mc_gain.py # MC vs exact joint at n=3
.venv/bin/python deepstack-swarm/workspace/johanson/curve3.py            # the curve below
```

## Result 1 — the regression (this is the blocker Bowling asked about)

`analytic_values(kind="model")` reproduces `seqbr.values` to float precision. The two bugs that
made it fail by 0.5–4.2:

1. a folded seat's value multiplied only the reaches of *folded* opponents, dropping the live
   opponents' reach (2max chip, seat 1, ending `jf`: model said -1.0, truth -0.5067);
2. a folded seat's payoff was treated as order-independent. True in chip EV, **false under ICM**:
   a folded player's ICM worth still moves with who busts. This one is the 4max ICM error.

`check_cardbr.py` now asserts and exits nonzero. Worst over all cases:

| test | what it pins down | worst |
|---|---|---|
| T1 | `model - seqbr` | 4.8e-09 (float32 `eq3`/`pw`), 5e-15 float64 |
| T2 | `independent - seqbr`, through the both-opponents-on-axes path the joint uses | 4.8e-09 |
| T3 | two independent onebody implementations | 6.7e-16 |

T1 covers the factored path, T2 the tensor path; every line the exact-joint path runs is
covered by one of them, and the only difference between "independent" and "joint" is the deal
tensor `D = deal.joint2()`, which `check_deal.py` checks has `M` for its marginal.

## Result 2 — model vs real exploitability, n=3, exact joint

`curve3.py`, 3max, `target=0` so the solver never stops early. "Real" here is exact: at n=3 the
two-opponent class joint is enumerated exactly (`deal.joint2()`, 270,725 four-card sets), and
both opponents sit on axes, so no independence is assumed anywhere. (The `ratio` column uses the model value at full precision; see the next section.)

3max 10bb chip:

| iters | model | real | ratio | seat gaps |
|---|---|---|---|---|
| 10 | 0.017433 | 0.016358 | 0.9x | +0.0006 -0.0011 -0.0009 |
| 50 | 0.000904 | 0.001811 | 2.0x | +0.0012 +0.0007 +0.0004 |
| 200 | 0.000073 | 0.001848 | 25.3x | +0.0018 +0.0010 +0.0004 |
| 800 | 0.000007 | 0.001861 | 266x | +0.0019 +0.0011 +0.0006 |
| 3200 | 0.000001 | 0.001897 | 3117x | +0.0019 +0.0012 +0.0006 |

3max 10bb ICM:

| iters | model | real | ratio | seat gaps |
|---|---|---|---|---|
| 10 | 0.034244 | 0.031931 | 0.9x | +0.0021 -0.0023 -0.0005 |
| 50 | 0.002021 | 0.008285 | 4.1x | +0.0063 -0.0001 +0.0002 |
| 200 | 0.000272 | 0.005714 | 21.0x | +0.0054 +0.0000 +0.0003 |
| 800 | 0.000028 | 0.005440 | 194x | +0.0054 +0.0000 +0.0003 |
| 3200 | 0.000003 | 0.005476 | 1852x | +0.0055 +0.0000 +0.0003 |

This is the IJCAI 2011 Figure 6 shape (Johanson, Waugh, Bowling, Zinkevich, *Accelerating Best
Response Calculation in Large Extensive Games*): the model number keeps falling and the real
number flattens. **The gap has already crossed by 25–50 iterations and is monotone after that**,
so this is not a late-solver artifact — it is what the stop rule is buying it. Early on the gap
is *negative*: the model number is bigger than the real one, and only stops being bigger once
the solver is fitted to the model's errors.

## The multiple, and why it should not be quoted

Bowling caught an inconsistency: I wrote "model exploit 1e-6 ... 3000x". The denominator is the
model exploitability **at the same iteration count**, at full precision, which the table then
printed rounded:

| spot | iters | model exploit (full precision) | real exploit | ratio |
|---|---|---|---|---|
| 3max chip | 400 | 2.118119576501e-05 | 1.868406963290e-03 | 88x |
| 3max chip | 1600 | 1.834873774495e-06 | 1.871863275555e-03 | 1020x |
| 3max chip | 3200 | 6.085879231690e-07 | 1.897118869503e-03 | 3117x |
| 3max chip | 6400 | 2.269635670949e-07 | 1.937879306092e-03 | 8538x |
| 3max ICM | 3200 | 2.957143261792e-06 | 5.475921835829e-03 | 1852x |
| 3max ICM | 6400 | 7.884010479062e-07 | 5.473321574141e-03 | 6942x |

So 1.9e-3/6.086e-7 = 3117 (the table used the unrounded value), while the rounded display
1.9e-3/1e-6 = 1900 is what the reader can reproduce. My mistake; the table was right and the
prose was not.

**But the ratio is the wrong thing to quote regardless.** The denominator is a solver artifact:
the model number decays like a CFR tail while the real one flattens, so the ratio is unbounded in
the iteration count (88x → 8538x on the same spot, same chart family). Any multiple is a
statement about how long someone ran, not about the chart. Quote it only at a named stop rule —
and note that the default rule and a tight one give different answers, because the real number
also still moves early on:

| spot | stop rule | stopped at | model exploit | real exploit | ratio |
|---|---|---|---|---|---|
| 3max chip | **`target=0.01` (the default)** | 50 it | 0.000904 | 0.001811 | **2.0x** |
| 3max ICM | **`target=0.01` (the default)** | 50 it | 0.002021 | 0.008285 | **4.1x** |
| 3max chip | `target=1e-4` | 200 it | 7.317e-05 | 1.848e-03 | 25x |
| 3max ICM | `target=1e-4` | 400 it | 9.126e-05 | 5.398e-03 | 59x |

**An earlier message of mine quoted "25x / 59x" as the stop-rule numbers; that is the
`target=1e-4` row, not the default.** The default stops at 50 iterations, and there the correct
pair is **0.0009 → 0.0018 (chip)** and **0.0020 → 0.0083 (ICM)**. Any chart claiming a number
from the default rule needs the second of each pair.

Recommended for the chart-claim language: quote the **absolute gap** (0.002–0.013 ICM
chips/hand), not a multiple.

## Result 3 — the gap is not one number: depth and stage move it by ~3x each

`n=3` exact joint, so both sides are exact. Max-seat gap, ICM chips/hand. Both stop rules are
given, because the default (`target=0.01`) stops at the first check and is what the grid will
produce; the converged column is `target=1e-4`. The *shape* is the same at both; the level is up
to ~1.3x higher at the default rule.

Stack depth, 3max, stacks (d,d,d), prizes 50/30/20, field (10,)\*3 (6 players left):

| d | 8bb | 10bb | 12bb | 15bb | 20bb | 30bb |
|---|---|---|---|---|---|---|
| gap, default (0.01) | 0.0035 | 0.0068 | 0.0068 | 0.0078 | 0.0096 | 0.0121 |
| gap, converged (1e-4) | 0.0039 | 0.0082 | 0.0084 | 0.0080 | 0.0093 | 0.0106 |

Roughly monotone, ~3.5x from 8bb to 30bb at the default rule. Asymmetric stacks are smaller:
(12,10,8) → 0.0043, (20,10,5) → 0.0007.

Stage, 3max 10bb, prizes 50/30/20, `field` = players at other tables:

| players left | 3 | 4 | 5 | 6 | 9 | 12 |
|---|---|---|---|---|---|---|
| gap, default (0.01) | 0.0024 | 0.0063 | 0.0070 | 0.0068 | 0.0040 | 0.0033 |
| gap, converged (1e-4) | 0.0024 | 0.0053 | 0.0088 | 0.0082 | 0.0041 | 0.0039 |

Non-monotone, peaking at 5–6 players left — the bubble region — and falling both when everyone
left is already paid (3) and when the money is far away (12). Range 0.0024–0.0070, ~2.9x.

**Answer to "does 5.5e-3 generalise": no, and it was the wrong number anyway.** The n=3 ICM
default-rule value is 0.0083 for a 4-player/10bb cell, but the gap runs 0.0024–0.0121 across
depth and stage — a factor of ~5 end to end. A single per-seat-count row is therefore not
enough. A per-cell column is more precision than the measurement supports either: the whole
spread is explained by two things you already know per cell (stack depth and distance from the
money). Suggested language: *"0.002–0.013 ICM chips/hand, largest near the bubble and at deeper
stacks"*, plus the per-cell number only where a cell falls outside that band.

Sanity anchor: the model's own in-model exploitability in these two tables is 0.0003–0.0043, so
at the default rule the gap is 2.8–9.0x the thing the stop rule was minimizing, and the two are
closest (2.8x) exactly where the solver is least converged (30bb). At `target=1e-4` the same
cells give 25–59x, because the denominator has shrunk and the real number has not.

## Result 4 — the per-seat gap saturates at n≈5; the sum keeps growing

Player count held at 9 (table n + 9−n in the field), stacks 15bb, prizes 50/30/20,
`target=1e-4`. n=3 exact joint; n≥4 MC, 400,000 real deals x 4 seeds, se quoted.

| n | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|
| gap (max seat) | 0.0072 | 0.0088 | 0.0127 | 0.0122 | 0.0121 | 0.0115 | 0.0130 |
| gap (sum over seats) | 0.0096 | 0.0215 | 0.0319 | 0.0415 | 0.0491 | 0.0579 | 0.0700 |
| model exploit | 6.0e-5 | 7.2e-5 | 8.0e-5 | 8.6e-5 | 8.0e-5 | 7.7e-5 | 7.4e-5 |

**Answer to "does it grow with n": no, above n≈5 it saturates.** From n=5 to n=9 the max-seat
gap is flat at 0.012±0.001, so the n=9 cells are *not* the weakest thing in the grid — they are
the same size as n=6. The rise is 3→5 (0.0072 → 0.0127), and that is one step, not a trend.

The sum over seats, however, grows almost exactly linearly (0.0096 at n=3 to 0.0700 at n=9,
≈0.0085 per seat). If the claim language uses NashConv instead of max-over-seats, the error
grows with the table and n=9 *is* the weakest cell. That is Morrill's combination rule to
choose, but the two answers differ by 7x at n=9, so it matters which one is quoted.

The same series at the **default stop rule** (`target=0.01`, iteration 50), which is what the
grid actually produces. Same spot, same seeds.

| n | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|
| gap (max seat) | 0.0061 | 0.0088 | 0.0122 | 0.0131 | 0.0115 | 0.0121 | 0.0131 |
| gap (sum over seats) | 0.0079 | 0.0202 | 0.0300 | 0.0404 | 0.0468 | 0.0565 | 0.0690 |
| model exploit | 0.00088 | 0.00105 | 0.00120 | 0.00131 | 0.00140 | 0.00147 | 0.00153 |

Same shape, same conclusion: max-seat flat at 0.012±0.001 from n=5, sum linear at ≈0.0085 per
seat. The default rule changes the level by at most 0.0006 here, so the n-series conclusion
does not depend on which stop rule the grid used.

## Result 5 — model vs real, n≥3, Monte Carlo real deals

`mc_values()` deals real hands (`deal.opponent_sets`, hero's cards first, each opponent from
what is left). 500,000 deals x 6 independent seeds; the `+-` is the SD across batches / sqrt(6).
The chart is solved to `target=1e-4`.

6max 15bb ante 1.0 ICM, model exploit 0.00008:

| seat | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| gain gap | +0.00693 | +0.00425 | +0.00744 | +0.00754 | +0.00536 | +0.00273 |
| se | 0.0006 | 0.0003 | 0.0005 | 0.0002 | 0.0003 | 0.0002 |
| EV gap | +0.04789 | +0.02220 | -0.00323 | -0.01602 | -0.02139 | -0.02388 |

real exploitability 0.00762, model 0.00008 — 90x at this stop rule (see "The multiple":
at the default `target=0.01` the pair would be different, so quote 0.0076, not the 90).

9max 15bb ICM, model exploit 0.00009:

| seat | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| gain gap | +0.01189 | +0.00945 | +0.00903 | +0.00888 | +0.00797 | +0.00398 | +0.00375 | +0.00372 | +0.00132 |
| se | 0.0005 | 0.0003 | 0.0003 | 0.0007 | 0.0003 | 0.0004 | 0.0003 | 0.0002 | 0.0001 |
| EV gap | +0.00727 | +0.00513 | +0.00448 | +0.00182 | +0.00045 | +0.00192 | +0.00097 | -0.00365 | -0.01499 |

real exploitability 0.01197, model 0.00009 — 127x at this stop rule, same caveat.

The 6max EV gaps (up to +0.048) are the same object Davis measured by simulation
(`davis-lifetime-eps.md` §6: up to +0.0257 ICM chips/hand, se 0.002, 2,000,000 hands, airing
that "strictly, what I measured is the EV discrepancy; ... the same order of error should be
assumed in [the gain], but that is an inference, not this measurement"). **The inference is now
a measurement**: the gain gap is 0.0027–0.0119, the same order as the EV gap, not smaller.
Different spots and different stacks, so compare orders, not digits.

## Result 6 — the MC path itself is checked, at n=3, against the exact joint

The n≥4 numbers are MC-only, so the MC path needs its own check where an exact answer exists.
Same solved chart, `2,000,000` deals x 6 seeds, compared against `exact3_values(weight="joint")`
(`check_mc_gain.py`):

| spot | seat | exact3 gain | MC gain | difference | MC's own se |
|---|---|---|---|---|---|
| 3max chip | 0 | 0.001848 | 0.001797 | -5.1e-05 | 3.8e-04 |
| 3max chip | 1 | 0.001051 | 0.001276 | +2.3e-04 | 2.2e-04 |
| 3max chip | 2 | 0.000474 | 0.000501 | +2.8e-05 | 2.7e-04 |
| 3max ICM | 0 | 0.005398 | 0.006678 | +1.3e-03 | 8.4e-04 |
| 3max ICM | 1 | 0.000058 | 0.000091 | +3.2e-05 | 5.5e-05 |
| 3max ICM | 2 | 0.000366 | 0.000403 | +3.7e-05 | 8.3e-05 |

Every difference is within ~1.5 standard errors of the MC's own noise, and the EV differences
are within 1 se, so the MC path is unbiased at the gain level. It also shows the honest cost of
measuring this by sampling: 12M deals buys a gain to about +-0.0003, which is *five times* the
map's own `target=1e-4`. Sampling cannot be the way this number is quoted; the exact n=3 joint
is.

## What is exact, what is bounded, what is estimated

| | status |
|---|---|
| n=3 gain gap | **exact** in the 169-class abstraction and the real deal (`deal.joint2()` enumerated, both opponents on axes, no independence used). Against the full 1326-combo game it is exact too if `deal.py`'s suit-symmetry argument holds. |
| n≥4 gain gap | **estimate with interval**. MC over real deals; se ≤ 0.0007 on the gain gap, quoted above. Validated at n=3 against the exact joint to within 1.5 se (Result 6). |
| direction | **Unproved.** Every converged row measured has real > model, and the only rows with real < model are at 10 solver iterations (both tables in `curve3.py`). Nothing here makes that a bound; it is an observation on these spots and these charts. |
| not measured here | The leaf tables. `eq3`/`pw`/`orders` are Monte Carlo (2000 samples/triple) and the tables are float32; Davis put the table noise floor at ~0.0001 (`davis-lifetime-eps.md` §6). 169-class bucketing, the 3-way showdown cap, and the push/fold restriction are all still in both sides of the comparison. |

## What the stop rule means now

`coach.solve`'s default `target=0.01` with `check_every=50` stops at the first check, so a chart
from the default rule is a 50-iteration chart. At n=3:

| spot | at the default stop (50 it) | at full convergence | lifetime eps | ratio to eps |
|---|---|---|---|---|
| 3max chip | model 0.000904, **real 0.001811** | real 0.001897 | 6.5e-4 | **2.8x** |
| 3max ICM | model 0.002021, **real 0.008285** | real 0.005398 | 6.5e-4 | **12.7x** (8.3x converged) |

Two corrections to what I said earlier. First, the real number here is 0.0083 (ICM), not the
0.0055 I quoted — 0.0055 is the *converged* value. Second, "it does not scale with how long you
run" is only true past ~200 iterations: the real number does fall 0.0083 → 0.0057 → 0.0054
between 50 and 400 iterations and then stops, while the model number keeps falling. So a default-
rule chart is genuinely worse in the real deal than a converged one, by about 1.5x, and that is
the last time more solving buys anything.

The honest quote is not "solved to 0.01" but "**solved to 0.002 in the model** (that is what the
default rule reports at n=3 ICM), whose real-deal value is 0.0083 — 12.7x the 6.5e-4 lifetime
epsilon." Across every spot measured the real number spans 0.0008–0.013, so 1.2x–20x epsilon.
This is the "measure inside which model" question, answered with a number.

## What would change my mind

1. A combo-level (1326 x 1326 x 1326) best response at n=3 disagreeing with `exact3_values`.
   `deal.py` argues it cannot by suit symmetry; nobody has run it.
2. A leaf-table recomputation at higher sample counts moving the gap by more than the gap.
   Cheap to test: rebuild `tmp/pushfold-e3.npz` with `SAMPLES=20000`.
3. A population or a chart whose *in-model* exploitability is not near zero, where the gap
   might be smaller in relative terms. All numbers here are at `target ≤ 1e-4`.
4. Someone showing the real-deal BR is not a valid exploitability for a chip-conserving
   multi-seat spot (that is Morrill's call, and I have not assumed it is a NashConv).
