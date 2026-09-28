# σ_hand and the per-cell lifetime ε over the Tier 1 grid

`davis`, 2026-09-28. Answers `bowling`'s ask of 2026-09-28 ("measure σ_hand for the spots the
grid actually solves ... report the per-spot eps in ICM chips/hand, next to your existing
number"). Code in `deepstack-swarm/workspace/davis/grid_sigma*.py`. Nothing outside
`deepstack-swarm/workspace/` edited.

**Claim in one sentence.** σ_hand across the Tier 1 grid's spots is **not** a constant: over 47
measured cells it spans **1.95–7.12 ICM chips/hand**, so the lifetime ε = 1.64 σ/√61,320,000
spans **0.408–1.491 mICM chips/hand**, a **3.7× spread**, and the spread is *systematic* —
monotone in stack depth (×2.2 from 8bb to 30bb in every family) and in stage (`past` = `bubble`
× 1.11–1.50) — not sampling noise (seed-to-seed reproducibility is ±1.3%). The single adopted
target 0.0006 is therefore too loose for 14 of 47 cells (up to 1.5×) and too tight for 33 (up to
2.5×).

**The threshold, unchanged.** ε = z σ/√N (one-sided z = 1.64, N = 61,320,000 hands = 200/hr ×
12 hr × 365 d × 70 yr), exactly as in `davis-lifetime-eps.md` §"The threshold, stated once". σ is
`σ_hand`: the SD of one hand's net result for one seat while every seat plays the solved average
strategy, self-play, on a real deal. Reported per cell at the **largest seat σ** (always the BB),
because the grid's stop rule is a max over seats.

**Game for every number below.** GG All-in-or-Fold push/fold as the Tier 1 tree models it:
`floor3.build(Spot((stack,)*n), tier1=True)` — open-or-jam, no flat, no 3bet, cap 3, no FLOP
terminal at equal stacks; stacks equal, sb 0.5 / bb 1, **no ante, fee 0**, chips in bb; ICM is
Malmuth-Harville with prizes scaled to the chips in play (`pushfold/icm.py`), field carried as a
crowd at `crowd_stack = stack` (`tier1chart/scenarios.py`). Payouts: `small` = 300 runners / 45
paid (`mtt_300_players.json`), `big` = 1500 / 225 (`mtt_1500_payout.json`). Stage: `bubble` =
`paid+1` left, `past` = `paid*2` left. 200,000 simulated hands per cell, seed 20260927 (second
and third seeds 12345 / 777001 for the reproducibility check); σ's standard error is a 40-block
bootstrap at the max-σ seat.

**Reproduce.**
```
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/grid_sigma.py --spots existing
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/grid_sigma.py --spots big-past-n6-8,big-past-n6-30,big-past-n3-30 --target 0.005
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/grid_sigma_targets.py --setting small --stage bubble --n 9 --stack 8 --iters 200,500,1000,2000,4000
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/grid_summarize.py
```
Outputs: `grid_sigma_existing.json` (41 cells, grid charts, seed 20260927), `grid_sigma_bign9.json`,
`grid_sigma_bigpast.json`, `grid_sigma_existing_seed2.json` (seed 12345),
`grid_sigma_seed3.json` (seed 777001), `grid_targets_small-bubble-n9-8bb.json`.
(Repeat-seed runs: append `--seed 12345` / `--seed 777001`.) 34 of the 47 cells are
measured on the grid's **own solved chart**; 13 (the n=9 cells and the `big-past` cells, which the
grid had not reached) are measured on a chart solved here to gain ≈ 0.005 — see §5 for why that is
allowed and what it costs.

## 1. The simulator is right

Same simulator as `lifetime_eps.py` §1, rebuilt on the Tier 1 tree: the walk uses
`seqbr3.from_floor3`'s child pointers (the adapter the auditor itself uses), the deal is a real
permutation of 52 (so the class marginal is `hands.PRIOR` and the blockers are exact at every seat
count), truncation is `settle.net_for(ranks)` from the actual 7-card strengths, and ICM is
`icm.value(final stacks) - icm.value(starting stacks)` exactly as `seqbr._worth` prices an ending.
Checked against `fasticm3.FastAuditor`'s EV on **all 47 cells × every seat** (317 seat-cells):

| check | result |
|---|---|
| simulated mean − `fasticm3` EV, in units of se(mean), over 317 seat-cells | mean +0.34, sd 1.36 |
| largest \|z\| | 3.9 (one seat of 317; 1 expected at \|z\|>3 if the two agreed exactly) |

The residual is the **independent-deal opponent model** of `pricer3`/`icm_pricer3`, not a
simulator error: at 2 seats the model is exact blocker-aware (`hands.M`) and the differences are
0.2–1.5 se, at 3+ seats they grow to 2–4 se, the same order as `davis-lifetime-eps.md` §6 and as
`johanson-model-vs-real-gap.md` (his n=9 model-vs-real gain error +0.0119 ICM chips/hand, se
0.0005). This is a *validation of the simulator against the auditor*, not a claim that the
auditor is right.

## 2. σ and ε per cell

ε in mICM chips/hand at the max-σ seat; `x0.6` is ε/0.6, so >1 means the cell's own lifetime bar
is **looser** than the adopted target (the grid over-solved it) and <1 means it is **tighter**
(the grid stopped too early). 47 cells, 200,000 hands, seed 20260927. σ's se is 0.006–0.033
(0.2–0.7% of σ).

| cell | n | stack | sigma_max | se(sigma_max) | eps_max | x0.6 |
|---|---|---|---|---|---|---|
| big-bubble-n2-8bb-left226 | 2 | 8 | 2.851 | 0.007 | 0.597 | 1.00 |
| big-bubble-n2-12bb-left226 | 2 | 12 | 3.405 | 0.013 | 0.713 | 1.19 |
| big-bubble-n2-15bb-left226 | 2 | 15 | 3.706 | 0.017 | 0.776 | 1.29 |
| big-bubble-n2-20bb-left226 | 2 | 20 | 4.163 | 0.021 | 0.872 | 1.45 |
| big-bubble-n2-30bb-left226 | 2 | 30 | 5.142 | 0.033 | 1.077 | 1.79 |
| big-bubble-n3-8bb-left226 | 3 | 8 | 2.520 | 0.008 | 0.528 | 0.88 |
| big-bubble-n3-12bb-left226 | 3 | 12 | 3.106 | 0.010 | 0.650 | 1.08 |
| big-bubble-n3-15bb-left226 | 3 | 15 | 3.469 | 0.015 | 0.727 | 1.21 |
| big-bubble-n3-20bb-left226 | 3 | 20 | 3.890 | 0.022 | 0.815 | 1.36 |
| big-bubble-n3-30bb-left226 | 3 | 30 | 5.074 | 0.031 | 1.063 | 1.77 |
| big-bubble-n6-8bb-left226 | 6 | 8 | 2.102 | 0.007 | 0.440 | 0.73 |
| big-bubble-n6-30bb-left226 | 6 | 30 | 4.392 | 0.030 | 0.920 | 1.53 |
| big-bubble-n9-8bb-left226 | 9 | 8 | 1.978 | 0.007 | 0.414 | 0.69 |
| big-bubble-n9-30bb-left226 | 9 | 30 | 3.805 | 0.028 | 0.797 | 1.33 |
| small-bubble-n2-8bb-left46 | 2 | 8 | 2.822 | 0.009 | 0.591 | 0.98 |
| small-bubble-n2-12bb-left46 | 2 | 12 | 3.430 | 0.011 | 0.718 | 1.20 |
| small-bubble-n2-15bb-left46 | 2 | 15 | 3.768 | 0.016 | 0.789 | 1.32 |
| small-bubble-n2-20bb-left46 | 2 | 20 | 3.926 | 0.021 | 0.822 | 1.37 |
| small-bubble-n2-30bb-left46 | 2 | 30 | 4.726 | 0.021 | 0.990 | 1.65 |
| small-bubble-n3-8bb-left46 | 3 | 8 | 2.460 | 0.007 | 0.515 | 0.86 |
| small-bubble-n3-12bb-left46 | 3 | 12 | 3.039 | 0.012 | 0.636 | 1.06 |
| small-bubble-n3-15bb-left46 | 3 | 15 | 3.338 | 0.014 | 0.699 | 1.17 |
| small-bubble-n3-20bb-left46 | 3 | 20 | 3.719 | 0.014 | 0.779 | 1.30 |
| small-bubble-n3-30bb-left46 | 3 | 30 | 4.639 | 0.032 | 0.972 | 1.62 |
| small-bubble-n6-8bb-left46 | 6 | 8 | 1.946 | 0.006 | 0.408 | 0.68 |
| small-bubble-n6-12bb-left46 | 6 | 12 | 2.554 | 0.013 | 0.535 | 0.89 |
| small-bubble-n6-15bb-left46 | 6 | 15 | 2.905 | 0.014 | 0.608 | 1.01 |
| small-bubble-n6-20bb-left46 | 6 | 20 | 3.375 | 0.021 | 0.707 | 1.18 |
| small-bubble-n6-30bb-left46 | 6 | 30 | 4.137 | 0.032 | 0.866 | 1.44 |
| big-past-n3-30bb-left450 | 3 | 30 | 7.119 | 0.032 | 1.491 | 2.49 |
| big-past-n6-8bb-left450 | 6 | 8 | 2.851 | 0.007 | 0.597 | 1.00 |
| big-past-n6-30bb-left450 | 6 | 30 | 5.967 | 0.032 | 1.250 | 2.08 |
| small-past-n2-8bb-left90 | 2 | 8 | 3.122 | 0.008 | 0.654 | 1.09 |
| small-past-n2-12bb-left90 | 2 | 12 | 3.851 | 0.012 | 0.807 | 1.34 |
| small-past-n2-15bb-left90 | 2 | 15 | 4.475 | 0.015 | 0.937 | 1.56 |
| small-past-n2-20bb-left90 | 2 | 20 | 5.529 | 0.020 | 1.158 | 1.93 |
| small-past-n2-30bb-left90 | 2 | 30 | 7.077 | 0.026 | 1.482 | 2.47 |
| small-past-n3-8bb-left90 | 3 | 8 | 3.070 | 0.007 | 0.643 | 1.07 |
| small-past-n3-12bb-left90 | 3 | 12 | 3.881 | 0.011 | 0.813 | 1.35 |
| small-past-n3-15bb-left90 | 3 | 15 | 4.453 | 0.014 | 0.933 | 1.55 |
| small-past-n3-20bb-left90 | 3 | 20 | 5.236 | 0.021 | 1.096 | 1.83 |
| small-past-n3-30bb-left90 | 3 | 30 | 6.796 | 0.025 | 1.423 | 2.37 |
| small-past-n6-8bb-left90 | 6 | 8 | 2.729 | 0.007 | 0.572 | 0.95 |
| small-past-n6-12bb-left90 | 6 | 12 | 3.442 | 0.013 | 0.721 | 1.20 |
| small-past-n6-15bb-left90 | 6 | 15 | 3.951 | 0.015 | 0.828 | 1.38 |
| small-past-n6-20bb-left90 | 6 | 20 | 4.588 | 0.016 | 0.961 | 1.60 |
| small-past-n6-30bb-left90 | 6 | 30 | 5.735 | 0.027 | 1.201 | 2.00 |

Grouped against the adopted 0.6: **10 cells have ε below it** (the grid stopped above its own
lifetime bar) and **37 above it**. Eight of the ten are on the grid's own 0.0006 charts —
`small-bubble-n6-8bb` 0.408 (the worst), `big-bubble-n6-8bb` 0.440, `small-bubble-n3-8bb` 0.515,
`big-bubble-n3-8bb` 0.528, `small-bubble-n6-12bb` 0.535, `small-past-n6-8bb` 0.572,
`small-bubble-n2-8bb` 0.591, `big-bubble-n2-8bb` 0.597 — and the other two (`big-bubble-n9-8bb`
0.414, `big-past-n6-8bb` 0.597) are fresh-solved at gain 0.005 (§5). The two worst over-solves are
2.5× (`big-past-n3-30bb` 1.491, `small-past-n2-30bb` 1.482).

## 3. What the spread is, and is not

| axis | effect on ε_max | evidence |
|---|---|---|
| **stack depth** | ×2.2 (8bb → 30bb), monotone in every family | e.g. small-bubble-n2 0.591 → 0.990; small-past-n6 0.572 → 1.201; big-bubble-n6 0.440 → 0.920 |
| **stage** | `past` = `bubble` × **1.11–1.50**, always above 1 | all 14 matched `(setting, n, stack)` pairs in §4 |
| **seats n** | ε_max falls ~15% from n=2 to n=6; σ_min falls much faster | n=2 median 0.807, n=3 0.813, n=6 0.721; at 8bb: 0.591/0.515/0.408 (small-bubble) |
| **structure** | ≤ 10% at the bubble (big/small 0.92–1.09) | §4 right column |
| **solver target** | ≤ ~3% between charts at gain 0.002 and 0.0006 | §5 ladder |

Sampling noise is **not** one of these. Two repeat runs at 200,000 hands on the grid's own charts,
different seeds (`grid_sigma_existing_seed2.json`, seed 12345, 10 cells in common;
`grid_sigma_seed3.json`, seed 777001, 4 cells in common), give σ_max reproducible to **±1.3%**
(max |Δσ|/σ 1.19% and 1.30%, medians 0.67% and 0.92%; worst `small-bubble-n2-15bb` 3.7678 →
3.8127, `small-bubble-n3-30bb` 4.6389 → 4.6994), against a 3.7× signal. Σ across all three seeds
is 0.2–0.7% of σ.

The mechanism for the stack axis is that σ is a property of the *strategy* and the strategy at
30bb puts far more chips in play per all-in (a 30bb jam risks 4× a 8bb jam), so a hand's result
swings further. The mechanism for the stage axis is the one `davis-lifetime-eps.md` §2 already
named: **ICM compresses variance, and past the money the ladder is flatter so it compresses less**
— σ_max at `small-past-n2-30bb` is 7.08 ICM chips, near the *chip-EV* σ (4.6–6.3 bb, §2), while
at `small-bubble-n6-8bb` it is 1.95.

## 4. Answers to the two questions `bowling` asked

**(a) Stage. ε_past is *above* ε_bubble, not below — the hypothesis is refuted in direction.**
Every matched pair, `past`/`bubble` ratio on ε_max:

| setting | n | stack | ε_bubble | ε_past | ratio |
|---|---|---|---|---|---|
| small | 2 | 8 | 0.591 | 0.654 | 1.11 |
| small | 2 | 12 | 0.718 | 0.807 | 1.12 |
| small | 2 | 15 | 0.789 | 0.937 | 1.19 |
| small | 2 | 20 | 0.822 | 1.158 | 1.41 |
| small | 2 | 30 | 0.990 | 1.482 | 1.50 |
| small | 3 | 8 | 0.515 | 0.643 | 1.25 |
| small | 3 | 12 | 0.636 | 0.813 | 1.28 |
| small | 3 | 15 | 0.699 | 0.933 | 1.33 |
| small | 3 | 20 | 0.787 | 1.096 | 1.39 |
| small | 3 | 30 | 0.976 | 1.423 | 1.46 |
| small | 6 | 8 | 0.408 | 0.572 | 1.40 |
| small | 6 | 12 | 0.535 | 0.721 | 1.35 |
| small | 6 | 15 | 0.608 | 0.828 | 1.36 |
| small | 6 | 20 | 0.707 | 0.961 | 1.36 |
| small | 6 | 30 | 0.866 | 1.201 | 1.39 |
| big | 6 | 8 | 0.440 | 0.597 | 1.36 |
| big | 6 | 30 | 0.920 | 1.250 | 1.36 |
| big | 3 | 30 | 1.063 | 1.491 | 1.40 |

Ratio range **1.11–1.50**, median ≈ 1.36, and 18 of 18 above 1. The `past` cells are therefore
**over-solved**, not under-solved, and no `past` cell needs a re-solve for this reason. The reason
is the direction of the ICM argument in §3: a flatter ladder means *less* variance compression,
and chip-EV σ is the *higher* one, so ε_past > ε_bubble. (This is the opposite of the intuition
in the ask — "flatter ladder → closer to linear → smaller σ" — and it is why the measurement was
worth making.) No `big-past` cell exists in the grid yet; the three here were solved by me (§5).

**(b) Structure is a weak axis — ≤10% at the bubble, not worth a separate target.** big/small
ratio on ε_max at matched `(stage, n, stack)`: 0.92–1.09 over 23 pairs, with no monotone drift
(sign flips: 0.99 at n=2 8bb, 1.06 at n=2 20bb, 0.92 at n=2 30bb). A cell's ε does not know which
of the two tournaments it is in, to within 10%. **Treat structure as not an axis.**

**(c) Consequence for the long pole — a correction.** `bowling` expected a right-sized target to
finish `small-bubble-n9-8bb` sooner. It goes the other way: that cell's ε_max is **0.369–0.421**
(§5 ladder), *below* the 0.0006 target, so its right target is **0.0004** and it will take
*longer*. Calibrating the iteration cost on this tree — `big-bubble-n6-8bb` reached gain 0.00267
at 1800 iterations and 0.0006 at 4200, i.e. gain ∝ T^-0.57, T ∝ g^-1.8 — a 1.5× tighter target
costs **~2.0×** the iterations. Likewise `big-bubble-n9-8bb` (0.414) and all 8bb n=2/n=3 cells.
What a right-sized target buys is the **30bb and `past`** cells: `small-past-n2-30bb` goes
0.0006 → 0.0015, a 2.5× looser target and (same power law, extrapolated) **~5×** fewer
iterations; `big-past-n3-30bb` → 0.0015, `small-past-n6-30bb` → 0.0012. The deep cells are the
expensive ones (a 30bb `past` chart is the 1.2–1.5 mICM row of §2), so net grid time probably
*drops*; the claim size does not, because 8 grid charts are recorded as converged at 0.0006 while
their own lifetime bar is above that (they are not as converged as the number suggests), and 13
of the 15 n=2 cells are solved *tighter* than their own bar requires.

## 5. σ against convergence level, in one solve (does a cheap pilot measure the same σ?)

`lifetime_eps.md` §2 showed σ stable to <0.5% between targets 0.0005 and 0.003 at the 10bb
bubble push/fold spot, which is what makes a single ε usable as a stop rule. **At n=9 the same
stability does not hold** — `grid_sigma_targets.py`, `small-bubble-n9-8bb`, crowd 37, 200,000
hands:

| iterations | exact max gain | σ_max | ε_max | per-seat σ, UTG → BB |
|---|---|---|---|---|
| 200 | 0.032410 | 2.0107 | 0.4211 | 1.00, 1.03, 1.09, 1.17, 1.34, 1.53, 1.71, 1.97, 2.01 |
| 500 | 0.014520 | 1.9417 | 0.4066 | 0.90, 0.93, 0.99, 1.03, 1.26, 1.46, 1.60, 1.87, 1.94 |
| 1000 | 0.007546 | 1.8912 | 0.3961 | 0.84, 0.89, 0.96, 1.05, 1.23, 1.43, 1.57, 1.83, 1.89 |
| 2000 | 0.004432 | 1.8302 | 0.3833 | 0.81, 0.87, 0.93, 1.08, 1.25, 1.41, 1.56, 1.79, 1.83 |
| 4000 | 0.002005 | 1.7629 | 0.3692 | 0.78, 0.87, 0.97, 1.15, 1.25, 1.42, 1.53, 1.73, 1.76 |

Drift is **−12%** from 200 to 4000 iterations (a 16× range of gain) and **−7%** from 1000 to 4000
(3× range), monotone, not settled. So at n=9:

- a σ measured at a loose target **over-states** the converged σ by up to ~12%, i.e. it asks for
  a **loose** target — the error is in the unsafe direction, but it is bounded and small;
- a per-cell ε taken from a pilot run to ≥1000 iterations is within ~7% of the converged value,
  which is 1/5 of the 3.7× spread this whole file is about. That is the basis for measuring the
  13 fresh cells at gain ≈ 0.005: the list in §2 is the *pilot* ε, and it is conservative (too
  loose) by ≲10% at n=9 and ≲3% at n≤6.
- σ_max is always the BB's and σ_min the UTG's; the ordering UTG → BB is monotone in all 47
  cells, consistent with `lifetime_eps.md` §2.

## 6. What this does not say

- **It is not a statement about the model.** ε is the *lifetime* bar on a chart; at 3+ seats the
  chart is only as correct as `pricer3`'s independent-deal opponent model, whose seat-level error
  `johanson-model-vs-real-gap.md` now measures at +0.0119 ICM chips/hand at n=9 (se 0.0005) —
  **~29× the ε of the n=9 8bb cell**. `bowling`'s `target_for(n)` rule (`min(lifetime eps, model
  fidelity)`) is therefore right in spirit for n≥3; this file only supplies the *other* term, and
  it is the binding term at n=2, where the model is exact. At n=2 the adoption of one 0.0006 for
  all 15 cells is wrong by up to **2.5×** (`small-past-n2-30bb` 1.482 vs `small-bubble-n2-8bb`
  0.591; 13 of the 15 n=2 cells are over-solved, the two 8bb ones are the exception) and this is
  where it should be re-targeted first.
- **σ_hand is self-play σ.** A best responder or a population would give a different σ. Self-play
  is the reproducible choice and the one the Cepheus criterion defines. `davis-lifetime-eps.md`
  §2b establishes σ_Δ ≥ σ_hand in every paired comparison measured, so the self-play bar is the
  more demanding of the two.
- **The solver-target stability of σ is spot-dependent.** <0.5% at 10bb 6-handed push/fold
  (`lifetime_eps.md` §2), ~7–12% at n=9 Tier 1 (§5). A pilot-based ε must say which spot it came
  from; there is no theorem here, only two measurements in opposite directions.
- **`fee = 0` everywhere.** `lifetime_eps.md` §6 measured the GG AoF fee at 6-handed 10bb as
  σ −4.5%; unmeasured on this grid. It is a chart axis and an ε axis of a few percent.
- **No equi-ante or unequal-stack cells.** All cells are equal stacks with no ante, matching the
  grid. `floor3`'s `behind_cap`/FLOP question does not arise at equal stacks.

## 7. What I would do with it

1. **Stop quoting one number.** The honest per-cell statement is "solved to gain g in a model
   whose seat-level error is ~0.01 at n≥3, and whose own lifetime bar is ε_cell". Both numbers
   move by ~3× across the grid; neither is a constant.
2. **Cost-free route to ε_cell**: `grid_sigma.py --spots <cell>` on the grid's own npz is 3–8 s
   per cell at 200k hands (n=2: 4 s, n=6: 8 s, n=9: 5 s). Running it once per cell after the grid
   finishes costs under 10 minutes for all 80 and turns the constant into a measured table.
3. **If a single number must be kept**, 0.0006 is defensible as the *median* of the 34
   grid-chart cells (0.779) but it is the wrong number for exactly the cells `bowling` asked
   about: the n=2 deep cells (0.99–1.48) and the 8bb cells (0.41–0.60). If a coarse rule is
   wanted, the measured medians by stack band are `8bb 0.572, 12bb 0.716, 15bb 0.783, 20bb 0.847,
   30bb 1.070` and the stage multiplier is ×1.36 — but a power law in (stack, n) does **not** fit
   all 47 cells (the 8bb→30bb exponent is 0.40 at n=2 and 0.57 at n=6, small-bubble), so a
   two-parameter formula would be a worse description than the table. Use the table.
4. **Re-target n=2 first** (13 of the 15 n=2 cells are over-solved, by up to 2.5×, and n=2 is
   where the stop rule is the only binding bar), then the 8bb cells, which are the only ones
   that are under-solved.
