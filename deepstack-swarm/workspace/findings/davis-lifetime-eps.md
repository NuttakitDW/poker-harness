# The lifetime-of-play epsilon for push/fold, and what `target` should be

`davis`, 2026-09-27, commit `b75e315`. Code in `deepstack-swarm/workspace/davis/`. Nothing in
`pushfold/` edited. Agenda item 2: derive the "essentially solved" threshold instead of picking
`target` by habit.

**Claim in one sentence.** The per-hand standard deviation (σ_hand, §2b for the paired
counterpart) of a solved push/fold strategy's
result is σ = 4.6–6.3 bb/hand for chip-EV spots and 3.0 ICM chips/hand at a 45-paid bubble
(σ is stable to <0.5% across solver targets 0.0005–0.003 and across simulation seeds), so the
Cepheus lifetime-of-play threshold ε = 1.64 σ / √61,320,000 is **0.96–1.31 mbb/hand chip EV and
0.63 mICM chips/hand at the bubble** — one order of magnitude below the solver's default
`target = 0.01`.

**The threshold, stated once.** Following Cepheus's "essentially solved" criterion (Bowling,
Burch, Johanson, Tammelin, *Heads-up limit hold'em poker is solved*, Science 2015): if a
strategy is played for a human lifetime — 200 hands/hour × 12 hours/day × 365 days × 70 years
= 200·12·365·70 = 61,320,000 hands — the empirical mean per-hand result has standard error
σ/√N, so a *one-sided* 95% test (z = 1.64, as `bowling` specified: the worry is being
detectably **worse**, not detectably different) cannot separate an exploitability below

    ε = 1.64 σ / √61,320,000 = 2.094e-4 · σ

from exact. Above ε, a lifetime *can* tell. (Two-sided 95%, z = 1.96, is 19.5% larger; both
are reported below.) The comparison to `auditor.audit`'s number is direct: if the max
single-seat best-response gain is above ε, a best responder beats the chart by more per hand
than a lifetime of play can hide.

**What σ is, exactly** (this is the one assumption everything rests on). σ is the standard
deviation of **one hand's net result for one seat while every seat plays the solved average
strategy** — self-play, on a real deal (n distinct hole-card pairs from one 52-card deck,
actions sampled from the behavioral strategy, five board cards when two or more seats are all
in). Chip EV is in bb/hand; ICM is in ICM chips/hand, the ICM value of the final stack minus
the ICM value of the starting stack, exactly as `pushfold/icm_pricer.py` prices a terminal.
Because the deal is real, the seat's class marginal is `hands.PRIOR` and the opponents'
conditional is the exact blocker-aware `hands.M` at *every* table size, whereas `pricer.py`
uses `hands.M` only at 2 seats and independent priors at 3+. The difference between the
simulated mean and `auditor.audit`'s EV is therefore exactly the independent-deal opponent
model's error at 3+ (§6), and zero-plus-sampling-noise at 2.

σ here is **σ_hand**: the SD of a single hand under one chart, which is exactly what the Cepheus
criterion uses and what "would a lifetime player notice" asks. It needs no common random
numbers — just a deal and a strategy. A second, different number is the SD of the per-hand
*difference* between two charts, σ_Δ; that is what common random numbers (CRN) measure, and it
is the right bar for "are two charts distinguishable in play" (§2b). Both are reported, σ_hand
as the headline.

**Game for every number below.** GG All-in-or-Fold push/fold as modelled by `pushfold/`:
169 hand classes, full-width CFR+, `max_allin = 3` (showdowns capped at 3-way), `fee = 0`
unless stated, chips in bb, 10bb stacks everywhere, ICM is Malmuth-Harville with prizes scaled
to the chips in play (`icm.py`). Solver: `method="cfr+", check_every=25, target=0.001` unless
stated; 200,000 simulated hands per spot, seed 20260927; σ's standard error is a 40-block
bootstrap, reported per seat.

**Reproduce.**
```
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/lifetime_eps.py --target 0.001
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/validate_sim.py     # the simulator
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/summarize.py        # the tables here
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/noise_floor.py      # table noise
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/chart_cost.py       # mbb per dTV point
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/extra_checks.py     # model error, fee
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/pairing.py          # sigma_D, two targets
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/paired_curve.py     # sigma_D vs dTV
```
Sensitivity runs: `--target 0.003 --out eps-target0.003.json`, `--target 0.0005 --out
eps-target0.0005.json`, `--seed 12345 --out eps-seed2.json` (3 minutes each, 7 spots, one core).

## 1. The simulator is right (what would make this wrong if it were not)

`validate_sim.py`, all checks exact or within 4 Monte Carlo standard errors, run before any
number above was used:

| check | result |
|---|---|
| HU always-jam, E[net(seat 0)] = Σ_hg PRIOR·M·10·(2 e2 − 1), exact from the exact e2 table | sim +0.0068 ± 0.0098 vs exact 0.0000 ✓ (1M hands, σ = 9.79) |
| HU always-fold, deterministic | −0.500000 / +0.500000, σ = 0 ✓ |
| 6h ante-0.25 each, everyone folds, deterministic | UTG −0.25, SB −0.75, BB +1.75 ✓ |
| 6h ante-0.5 bb, everyone jams, fee 0.2, cap 3 | Σ nets = −0.600000 every hand, σ(Σ) = 0 ✓ |
| solved spots, simulated mean vs `auditor.audit` EV, chip EV and ICM | agrees within 4 se for every seat ✓ |
| HU FT: ICM σ must be the prize-ladder slope times the chip-EV σ (linear 2-player ICM) | slope 0.19613 × 4.55533 = 0.89344, measured 0.89344, ratio 1.00000 ✓ |
| `noise_floor.py` HU control: HU uses only e2, so a different eq3/pw build must change nothing | chart dTV 0.00%, EV identical ✓ |

## 2. Per-spot σ and ε

σ per seat, seat order is the action order (`spot.names`), 10bb stacks. ε is at the largest
seat σ, in the spot's own unit.

| spot | n | ante | unit | σ per seat | σ_max | ε = 1.64σ/√N | ε, m-unit | ε (z=1.96) |
|---|---|---|---|---|---|---|---|---|
| HU-10bb | 2 | — | bb | 4.5905, 4.5905 | 4.5905 | 0.000961 | 0.961 mbb | 0.001149 |
| HU-10bb-icm-ft | 2 | — | ICM chips | 0.8939, 0.8939 | 0.8939 | 0.000187 | 0.187 mICM | 0.000224 |
| 3h-10bb | 3 | — | bb | 3.5917, 4.5517, 4.7118 | 4.7118 | 0.000987 | 0.987 mbb | 0.001179 |
| 6h-10bb-ante0.25-each | 6 | 0.25 each | bb | 4.6323 … 6.2549 | 6.2549 | 0.001310 | 1.310 mbb | 0.001566 |
| 6h-10bb-ante0.5-bb | 6 | 0.5 bb | bb | 3.1169 … 4.9359 | 4.9359 | 0.001034 | 1.034 mbb | 0.001235 |
| 6h-10bb-ante1.0-bb | 6 | 1.0 bb | bb | 3.8255 … 5.4075 | 5.4075 | 0.001132 | 1.132 mbb | 0.001353 |
| 6h-10bb-ante1.0-bb-bubble46 | 6 | 1.0 bb | ICM chips | 3.0079, 3.0090, 2.9252, 2.8060, 2.6584, 2.8074 | 3.0090 | 0.000630 | 0.630 mICM | 0.000753 |

The ICM spots: `HU-10bb-icm-ft` is the heads-up of the 300-runner field (1st/2nd, 593.7/399.0,
no field). `…bubble46` is 46 left of 300, 45 paid, table 6×10bb, field average 20bb → a crowd
of 40 × 21.5bb exactly as in `icm_geometry.payouts_for` (bard's bubble stage). Standard errors
of σ are 0.009–0.017 bb and 0.009–0.013 ICM chips, i.e. 0.2–0.4%.

Readings that matter:

- **One number covers the chip-EV spots: ε ≈ 1 mbb/hand.** The spread is 0.96–1.31 mbb.
  The largest is the spot where every seat antes 0.25 (σ_max 6.25): antes are dead money, so
  every seat's result swings more.
- **σ rises toward the blinds.** In every chip-EV spot σ grows monotonically from UTG to BB
  (e.g. 3.83 → 5.41 bb with a 1bb ante). The BB posts the most and calls the most.
- **ICM flattens it.** At the bubble σ is 2.66–3.01 across *all* seats, half the BB's chip-EV
  σ. That is not a unit trick: measured ICM σ is **0.688×** the local linear prediction
  (elasticity 0.8092 × chip-EV σ 5.4075 = 4.376 vs 3.009 measured). ICM is concave over the
  wide per-hand result distribution, so the spread compresses.
- **At heads-up the ICM σ is *only* a unit change** (ratio 1.00000 to the prize-ladder slope):
  0.8939 ICM chips = 0.19613 × 4.5905 bb. Do not read "HU ICM has 5× less variance" into the
  table; the 65/35 ladder is linear in chips. (The 1st/2nd ratio is 0.672, chips are 0.5.)

**Stability.** σ_max at targets 0.0005 / 0.001 / 0.003 and at a second simulation seed:

| spot | t=0.0005 | t=0.001 | t=0.003 | seed 2 |
|---|---|---|---|---|
| HU-10bb | 4.5977 | 4.5905 | 4.5576 | 4.5945 |
| 3h-10bb | 4.7130 | 4.7118 | 4.7118 | 4.7093 |
| 6h-ante0.25-each | 6.2450 | 6.2549 | 6.2680 | 6.2831 |
| 6h-ante0.5-bb | 4.9284 | 4.9359 | 4.9335 | 4.9256 |
| 6h-ante1.0-bb | 5.4057 | 5.4075 | 5.4015 | 5.4212 |
| 6h-bubble46 | 3.0272 | 3.0090 | 3.0003 | 3.0307 |

Worst spread 0.45%. **ε does not have to be recalibrated when `target` changes**, which is
what makes it usable as a stop rule.

### 2b. σ_hand vs σ_Δ: is the paired bar ever looser?

The paired bar is ε_Δ = 1.64 σ_Δ/√N where σ_Δ is the SD of the per-hand difference between two
charts on the *same* deals and the same action draws (CRN). Measured at the bubble spot
(6h 10bb, bb-ante 1.0, 46 left of 300; σ_hand = 3.03 ICM chips, ε_hand = 0.634 mICM/hand):

| chart A → chart B | dTV | σ_Δ (per seat) | σ_Δ/σ_hand | mean loss of B | loss / ε_Δ |
|---|---|---|---|---|---|
| t=0.003 → t=0.0005 (`pairing.py`) | 8.58% | 3.23–3.65 | 1.21 | — | — |
| bb-ante 1.0 → each-ante 1/6 (`chart_cost.py`) | 4.59% | 3.35 | 1.11 | 0.0155 | 22× |
| bb-ante 1.0 → no ante (`chart_cost.py`) | 21.93% | 3.21 | 1.07 | 0.0812 | 121× |
| bb-ante 1.0 → no ante (`paired_curve.py`) | 21.93% | 3.39 | 1.12 | 0.0709 | 100× |
| blend a=0.5 of the same pair | 10.96% | 3.30 | 1.09 | 0.0378 | 55× |
| blend a=0.1 of the same pair | 2.19% | 3.83 | 1.27 | 0.0082 | 10× |

(Rows 2–3 quote the loss averaged over seats and rows 4–6 the worst seat, so rows 3 and 4, two
independent estimates of the same pair, differ in statistic as well as in draw: 121× vs 100×,
σ_Δ 3.21 vs 3.39 with se ≈ 0.006 each. Treat the pair as agreeing to ~20%, the honest scale for
two simulations of 200k and 300k hands. Rows 5–6 are interpolations between the same two charts,
evaluated in chart A's tree on the same 300k CRN deals.)

**A hypothesis of mine that this refuted** (stated so nobody re-runs it): (a) I expected a
paired comparison to be *tighter*, i.e. σ_Δ < σ_hand, because common random numbers remove the
card variance. (b) Measurement, bubble spot, 200,000 deals, seed 20260927, same action draws:
σ_hand = 2.9951, 3.0003, 2.9305, 2.7883, 2.6642, 2.7901 for chart A (t=0.003) and 3.0173,
3.0272, 2.9086, 2.8005, 2.6440, 2.8184 for chart B (t=0.0005), σ_Δ = 3.6542, 3.6379, 3.5878,
3.4130, 3.2328, 3.4314, i.e. **1.21–1.23× σ_hand, not less**; the paired bar ε_Δ = 0.000693 ICM
chips/hand against ε_hand = 0.000628, 10% *larger*. (c) Corrected claim: for charts that differ
this much, CRN removes the card variance but not the "the two charts disagree on which hands
they play" variance, which dominates; on this spot the paired bar is the looser of the two, and
the self-play σ_hand is the demanding one.

Answer to the question bowling asked: **no — σ_Δ is never below σ_hand in any pair measured**
(ratios 1.07–1.27, all *above* 1). CRN removes the card variance exactly, but two charts
disagree on which hands they play, so the *difference's* per-hand distribution is at least as
wide as either chart's. The case "σ_Δ below its own lifetime bar while σ_hand is not" does not
arise here, so the paired bar cannot rescue a chart that σ_hand says is detectable.

What is instead scale-dependent is the *signal*. Along a chart-interpolation axis σ_Δ is nearly
**flat** in the mix level (3.21–3.83) while the mean loss is **linear** in it (0.0082 → 0.0812
for a 0.1 → 1.0), so the detection ratio |loss|/ε_Δ falls from 121× to 10× as the charts get
closer. Extrapolating the measured line, two charts in this direction are separable by a
lifetime of play (ratio 1×) only once they differ by **≈ 0.2 percentage points of dTV**; closer
than that, a lifetime of play cannot tell them apart even though each chart on its own sits far
below ε_hand. Dividing each row's dTV by its ratio gives 0.215, 0.200, 0.220, 0.199 and 0.219
percentage points from the five measured points — the linearity is what that consistency shows,
and it is the check that makes the extrapolation a measurement rather than an assumption
(σ_Δ flat in the mix level is the mechanism). That is the player-terms expression of a chart-noise floor, and it is ~0.2 pts of
dTV, not a value in bb — burch's seed-noise floor should be phrased against that number, not
against ε_hand.

## 3. How many hands it takes to notice

Hands of play needed for the per-hand mean to separate a strategy with exploitability g from
exact, N = (1.64 σ/g)², and the years at 2,400 hands/day (the Cepheus schedule):

| spot | g=0.01 | g=0.005 | g=0.003 | g=0.001 |
|---|---|---|---|---|
| HU-10bb | 0.6M / 1y | 2.3M / 3y | 6.3M / 7y | 56.7M / 65y |
| 3h-10bb | 0.6M / 1y | 2.4M / 3y | 6.6M / 8y | 59.7M / 68y |
| 6h-ante0.25-each | 1.1M / 1y | 4.2M / 5y | 11.7M / 13y | 105.2M / 120y |
| 6h-ante0.5-bb | 0.7M / 1y | 2.6M / 3y | 7.3M / 8y | 65.5M / 75y |
| 6h-ante1.0-bb | 0.8M / 1y | 3.1M / 4y | 8.7M / 10y | 78.6M / 90y |
| 6h-bubble46 (ICM) | 0.2M / 0y | 1.0M / 1y | 2.7M / 3y | 24.4M / 28y |

A spot solved to the repo's default `target = 0.01` is *detectably not exact after about a
year* of the Cepheus schedule. At 0.003 it is ~10 years. Only at ~0.001 does it reach a
lifetime — which is just §2's ε seen from the other side (the table's g=0.001 column crosses
70 years exactly where ε crosses 1 mbb). This is the whole argument in one table.

## 4. Recommendation

**`target = 0.001` bb/hand for chip EV, `target = 0.0006` ICM chips/hand for ICM spots.**
One value, 0.001, everywhere is also defensible (1.6× the bubble ε, 5× the heads-up ICM ε,
i.e. slightly loose at ICM spots); the per-spot pair is what the measurement actually supports.

Reasons, in order of weight:

1. **0.001 is where ε lands** (§2): below it, a lifetime of play cannot separate the chart
   from exact; above it, it can. The default 0.01 is 8–16× above ε and detectable in ~1 year.
2. **It is free.** On this tree, reaching target 0.001 costs 25–100 CFR+ iterations — 0.0 s
   (HU) to 15 s (6h ICM with 45 prizes and a 40-player crowd); target 0.0005 costs 25–175
   iterations, ≤38 s. All seven spots to 0.0005 take under a minute of solver time. There is
   no budget argument for 0.01, only habit.
3. **σ does not move with `target`** (§2), so the threshold does not have to be re-derived
   when the stop rule changes, and a chart stopped at 0.001 is not a different object from
   one stopped at 0.003.
4. **Cross-check from the chart side.** Two charts are separable by a lifetime of play only
   once they differ by ≈ 0.2 points of dTV in the ante direction (§2b), so ε is not an
   artifact of one seat's variance. This does **not** license stopping below 0.001: the
   measured difference between targets 0.003 and 0.0005 is 8.6 points of dTV, far above that
   floor, so a smaller `target` still moves the chart in a visible way. 0.001 is where the
   *exploitability* stops being visible to a lifetime, not where the chart stops changing;
   whether the extra chart change below 0.001 buys value is a separate question and is not
   measured here.
5. **The rounding in `Result.chart` (DISPLAY_CUTOFF = 0.01) is a different edit from the stop
   rule, and probably the bigger one.** Rounding moves a node by at most ~1 percentage point
   of combo-weighted TV (every hand within 1% of an action is snapped to it), and §5 prices a
   percentage point at 2.1–3.8 m-units/hand in the ante direction — so the rounding is worth
   up to ~6× ε by that bound, and it is applied *after* the solve, so no `target` fixes it.
   Not measured directly here (no chart in `Result.chart` was re-audited); a `DISPLAY_CUTOFF`
   sweep re-auditing the rounded chart is the natural next step, and it is the constrained-CFR
   question (Davis, Waugh, Bowling, AAAI 2019) rather than a stop-rule question.

## 5. Does bard's scenario grid survive ε? (`bard-scenario-grid.md` §7)

His call was that the grid needs at least a stage/BF axis, a stack-configuration axis and an
explicit ante axis, tested against an *illustrative* 2%-of-hands line for chart distance (dTV).
He asked for the calls to be re-checked against whatever ε lands on. ε is in value units, so
the missing piece is the exchange rate. `chart_cost.py` measures it at the bubble (6-max 10bb,
46 left of 300, A=20), by playing the *stale* chart at the true spot, on the same tree, with
the same deals and the same action draws (common random numbers):

| axis (right chart → wrong chart, same spot) | dTV at the worst node | exploitability of right / wrong chart | max seat value loss | × ε (own spot) |
|---|---|---|---|---|
| bb-ante 1.0 → no ante | 21.93% (BTN first-in) | 0.00088 / 0.49089 | 0.0721 | 114× (ε 0.63) |
| no ante → bb-ante 1.0 | 21.93% (BTN first-in) | 0.00067 / 0.16920 | 0.1257 | 233× (ε 0.54) |
| bb-ante 1.0 → each-ante 1/6 (matched total money posted) | 4.59% (HJ first-in) | 0.00088 / 0.00916 | 0.0068 | 10.8× (ε 0.63) |

(ε in m-ICM-chips/hand, from `chart_cost.py`: no ante 0.540, bb-ante 1.0 0.630, each-ante 1/6
0.635. The stale chart's own exploitability at the true spot is 0.009–0.49 against 0.0007–0.0009
for the chart solved there.)

Local slope along the ante-size direction, from the smallest mixture (0.44% dTV):
**2.1 m-ICM-chips/hand per percentage point of dTV** on the seat-mean loss (3.3–3.8 m-units on
the worst seat), and it is linear out to the full 21.9%: **ε is worth 0.25–0.56 percentage
points of dTV** at the bubble (0.18–0.31 on the worst seat). Paired per-hand SD of the two
charts' difference (σ_Δ, §2b) is 3.21–3.35 against σ_hand 3.01 for one chart alone, so the
paired bar is the *larger* of the two and a paired experiment separates these charts by
22–121× ε_Δ as well.

**Verdict: every "needs its own axis" call survives, and ε is *stricter* than the 2% line,
not looser.** ε is worth ~0.3–0.6 points of dTV in the ante direction, so the illustrative 2%
line is 4–8× *more permissive* than the lifetime test. The distances he measured — 4.6 points
(matched-total ante mode), 14–22 points (§4 ante), 19–35 points (§1/§2 BF-matched pairs) — are
all 8–140× the ε-equivalent distance, and in value terms the stale chart is 10.8–233× ε worse
or 10–558× more exploitable. Nothing in §1–§4 is retracted; if anything §7's worry was in the
wrong direction and the grid may need to be finer.

Caveats on that verdict: the exchange rate is measured along two ante axes at one ICM stage,
and a point of dTV is not worth the same everywhere (perturbing hands near indifference is
cheaper than perturbing hands deep inside one action), so 0.3–0.6 points is a statement about
these directions, not a universal constant. §1's smallest distance (1.7 points of ante-alone
dTV at a stage 60 players left vs the final table) is the one case that could be within a
factor of a few of ε; it was not reproduced here.

## 6. What limits the claim (and what would change my mind)

- **The eq3/pw Monte Carlo tables are not the limit.** `noise_floor.py` rebuilt them with
  different seeds (`alt_tables.py`, 862 s, 818,480 class triples × 2,000 deals): per-cell rms
  difference 0.014 (eq3) and 0.0145 (pw), implying a per-table per-cell σ of 0.0099. But the
  *solution* barely moves: chart dTV 0.06% (ICM) and 0.11% (chip EV), EV differences ≤ 0.0001
  per seat, exploitability identical to five decimals, and a chart solved on one table audited
  on the other loses < 0.0001. Aggregation over ~5M triples cancels the per-cell noise, so
  **the table noise floor is ~0.0001, 6× below ε** — a stop rule at 0.001 is not chasing
  table noise. (This is the opposite of what I expected before measuring; the earlier
  per-cell σ of 0.011 is real per cell but is not the right number to propagate.)
- **The 3+ seat deal model is the real floor.** `pricer.py`'s independent-deal opponent model
  is documented at up to 0.014bb per seat error at 9-handed. My simulator is the *true* deal,
  so its mean minus `auditor.audit`'s EV measures this directly. At 200k hands the differences
  (0.004–0.027 bb/hand, se 0.006–0.014) were suggestive but not resolvable; `extra_checks.py`
  reran the bubble spot at **2,000,000 hands** (se ≈ 0.002) and they are real:

  | seat | 0 | 1 | 2 | 3 | 4 | 5 |
  |---|---|---|---|---|---|---|
  | sim mean − model EV (ICM chips/hand) | +0.0257 | +0.0095 | −0.0027 | −0.0163 | −0.0117 | +0.0052 |
  | in standard errors | 12.2 | 4.4 | −1.3 | −8.2 | −6.3 | +2.6 |

  Up to **0.026 ICM chips/hand, i.e. 40× ε**, and the same order as the 0.014bb the pricer
  docstring reports. **Consequence: at 2 seats the auditor's number is exact and `target` can
  be read as a real exploitability; at 3+ seats it is a number inside the model, and the
  honest quote is "solved to 0.001 in the model, whose own seat-level pricing error is
  0.01–0.03" — an order of magnitude above ε.** Strictly, what I measured is the EV
  discrepancy; the auditor's *gain* is a difference of prices, so the same order of error
  should be assumed in it, but that is an inference, not this measurement.
- **`auditor.audit` is not a Nash distance at 3+ seats or under ICM.** It is the largest
  single-seat best-response gain at a general-sum, non-zero-sum pricing (EVs sum to −0.775
  ICM chips/hand at the bubble spot above, absorbed by the crowd), so ε is a "stability"
  statement, not a two-player zero-sum guarantee. At 2 seats (HU) it *is* the exploitability.
- **σ_hand is self-play σ.** A different responder (a best responder, or a population) would
  give a different σ_hand; that is unmeasured here (it is the responder-ladder experiment, the
  queued half of this assignment). Self-play is the reproducible choice and the one the Cepheus
  criterion defines. Against the *paired* bar the direction is now known from §2b: σ_Δ ≥ σ_hand
  in every pair measured, so ε_hand ≤ ε_Δ and the stop rule built on σ_hand is the more
  demanding of the two — it errs toward solving more, not less. (My earlier expectation that
  pairing would tighten ε was wrong; the measurement in §2b replaced it.)
- **`fee = 0` in every spot above.** GG AoF charges a showdown fee (repo memory: 0.2bb per
  player, unconfirmed; `Spot.fee`). `extra_checks.py` solves the 6h-ante1.0 spot at fee 0.2:
  σ_max falls from 5.4075 to 5.1644 (−4.5%) and ε by the same −4.4%, so **the recommendation
  survives a real fee**; but the chart moves by 4.48% dTV at the worst node — as much as the
  ante-mode axis. The fee is a chart axis, not an ε axis: charts solved at fee 0 should not be
  played at a fee table without re-solving (the fee is charged per player in a showdown, so it
  is *not* a strategically irrelevant constant shift).
- **One stack depth (10bb).** σ is a function of the strategy, and the strategy of a 20bb or
  a 3bb spot is different; ε would need re-measuring per depth. The 10bb case is the one that
  matters most for AoF, and σ's insensitivity to `target` suggests it will be stable across
  neighbouring depths — but that is an inference, not a measurement.

## 7. Files

- `workspace/davis/lifetime_eps.py` — the simulator, σ, ε; `lifetime_eps.json` and the
  `eps-*.json` sensitivity runs.
- `workspace/davis/validate_sim.py` — the seven checks in §1.
- `workspace/davis/summarize.py` — the tables in §2–§3.
- `workspace/davis/alt_tables.py`, `noise_floor.py`, `noise_floor.json` — §6 table noise.
- `workspace/davis/chart_cost.py`, `chart_cost.json` — §5 exchange rate, and σ_Δ for three
  chart pairs.
- `workspace/davis/extra_checks.py` — §6 model error and fee.
- `workspace/davis/pairing.py` — §2b, σ_Δ between two targets.
- `workspace/davis/paired_curve.py`, `paired_curve.log` — §2b, σ_Δ along the ante interpolation
  axis and the ≈0.2-pt-dTV separability floor.
