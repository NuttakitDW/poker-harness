# An ICM pricer for Tier 1 ("open or jam"): chart-scale solving, still a slow stop rule

`burch`, 2026-09-27, commit `b75e315`. Code in `deepstack-swarm/workspace/burch/open3bet/`
(`icm_pricer3.py`, `verify_icm3.py`, `solve3.py`). Nothing in `pushfold/` edited.

**Claim in one sentence.** `coach3` now solves Tier 1 for ICM at chart scale (167 ms/iteration at
n=9, vs the old reference solver's 22.6s/iteration — bowling's `bowling-tier1-first-solve.md`),
cross-checks against johanson's slow generic oracle to float32 precision (max |diff| ≤ 5.2e-5,
in the exact band `pushfold`'s own `test_icm_pricer.py` accepts, 5e-5/2e-4), and reproduces the
3-handed 0.008117 number from `burch-tier1-solve.md` exactly at iteration 400 — but the
**exploitability check is still the slow oracle** (`seqbr3.Auditor`, unmodified): no `FastAuditor`
exists yet for ICM, so a first ICM chart needs a larger `check_every` than chip EV, not a smaller
one.

**Game.** Tier 1, as `burch-tier1-solve.md`: preflop only, n = 2..9 equal stacks, sb 0.5 / bb 1,
no ante, fee 0, cap 3, no flat, no 3bet. ICM: 50/30/20 payouts, field padded to 4 total players
(`(stack,) * max(0, 4-n)`), matching bowling's `tier1.py` convention.

## 1. Reproduce

```
.venv/bin/python deepstack-swarm/workspace/burch/open3bet/verify_icm3.py
.venv/bin/python deepstack-swarm/workspace/burch/open3bet/solve3.py <n> <stack> <target> <method> icm
```

## 2. What `icm_pricer3` is

Generalises `pushfold/icm_pricer.py` exactly the way `pricer3.py` generalises `pushfold/pricer.py`
(same three points: sequences instead of `node*2+action`, product columns for a multi-decision
opponent's line, an explicit own-later-reach factor `mine` — see `pricer3.py`'s docstring). Two
things reused rather than re-derived, on purpose, to keep the risk down:

- **The ICM tensor algebra itself** — `_layouts()`, `_pair()`, the group-by-target batching of the
  six 3-way finish orders — is imported straight from `pushfold.icm_pricer`. That is the part
  worth not re-deriving by hand; only the column *indexing* around it changes.
- **The worth table** (`_worth`: finish order -> ICM chips per seat) is johanson's `seqbr._worth`,
  called through `seqbr3.from_floor3`, the same adapter that already backs `seqbr3.Auditor`. One
  tested implementation of "chips to ICM value" for the whole workspace, not two.
- **The product-column space is shared with the chip pricer.** `icm_pricer3.plan(tree, payouts,
  chip_plan)` takes an existing `pricer3.Plan` and reuses its `.prods`/`.one` outright: which
  product columns are needed (each opponent's full-path reach, this seat's own-later reach) is a
  fact about the action tree, not the payout scheme, so the two pricers can share one `columns()`
  array. `coach3.iterate` needs no change either way — `SeatPlan.price(cols)` has the same
  `(cfv, no_decision)` signature for both.

## 3. Correctness: two checks, both against the *slow* oracle first

Per bowling's instruction ("re-run the same 3-handed cross-check against the slow `seqbr3` oracle
before trusting it").

**A. Per-node counterfactual value**, random (Dirichlet, not uniform) strategies, vs a direct
backward walk over `seqbr3._icm_values_cached`'s terminal values (`tier1_check.counterfactual`,
unchanged):

| n | field | max \|diff\| |
|---|---|---|
| 2 | (15,15) | 8.9e-15 |
| 3 | (15,) | 1.1e-05 |
| 4 | () | 1.8e-05 |
| 6 | () | 5.2e-05 |
| 9 | () | 5.2e-05 |

These are float32, not float-noise, but they land exactly in the band `pushfold`'s own
`tests/test_pushfold/test_icm_pricer.py` accepts for the *original* icm_pricer against its own
brute-force check (`atol=5e-5` and `2e-4`, lines 43-44/100-101) — the `.astype(np.float32)` casts
inside `_layouts()`/`_three_way()` are inherited unchanged from that file, so this is the same
known precision, not a new bug.

**B. End to end**: solve with `coach3` + `icm_pricer3`, audit the average with the untouched
`seqbr3.Auditor` (slow oracle), confirm the exploitability actually falls and reproduces the
number `tier1_check.py`'s independent reference solver got:

| n | iter 25/200 | iter 100/400 | iter 400/1600 |
|---|---|---|---|
| 2 | 0.0647 | 0.0172 | 0.0015 |
| 3 | 0.0868 | 0.0393 | **0.008117** |

n=3 at iteration 400 is **exactly** `burch-tier1-solve.md`'s cross-check number (0.008117), computed
this time by an entirely different route (`coach3`/`icm_pricer3`, not `tier1_check.solve_generic`)
— both landing on the same value to 6 decimals is the strongest evidence in this note.

## 4. Speed: solving is chart-scale now; auditing is not

`coach3.iterate` with `icm_pricer3.plan`, ms/iteration (uniform strategy, 20-iteration average):

| n | chip EV (`pricer3`) | ICM (`icm_pricer3`) | plan build |
|---|---|---|---|
| 3 | 4.2 ms | 8.7 ms | 2 ms |
| 4 | 4.7 ms | 14.4 ms | 5 ms |
| 6 | 15.2 ms | 35.7 ms | 21 ms |
| 9 | 68.7 ms | 166.9 ms | 146 ms |

ICM costs 2-2.4x chip EV per iteration here, in the range `burch-open3bet-tree-and-cost.md`
estimated from `pushfold`'s own chip/ICM ratio (1.7-2.9x) before any OPEN3BET ICM pricer existed.
n=9 at 167 ms/iteration, 400-2000 iterations, is minutes, not the 1.8-3.3 hours that finding
projected by scaling a reference solver that didn't exist yet for this tree.

**The audit did not get the same treatment.** `seqbr3.Auditor` for ICM still loops per terminal
(same shape of cost as `seqbr.chip_values`, `burch-tier1-solve.md` Sec 4, plus the ICM-specific
2-way/3-way branches), even with `_worth` cached:

| n | ICM iterate | ICM audit (`seqbr3.Auditor`, slow) | ratio |
|---|---|---|---|
| 3 | 8.7 ms | 208 ms | 24x |
| 4 | 14.4 ms | 1 232 ms | 86x |
| 6 | 35.7 ms | 11 351 ms | 318x |

`solve3.solve_icm` defaults `check_every=200` (vs chip EV's 25) so a check doesn't dominate the
run, matching Burch thesis Sec 3.3.1's logic with a bigger number rather than abandoning it. First
real ICM solve with that stop rule, 3-handed:

```
$ solve3.py 3 15 0.001 cfr+ icm
converged in 1800 iters, 17.18s (9.54 ms/iter incl. audits)
  iter    400  exact max gain 0.008117 ICM chips/hand   <- matches Sec 3
  iter   1800  exact max gain 0.000968 ICM chips/hand
```

n=6 at the same target (`check_every=200`, since a single audit there costs 11.4s):

```
converged in 1600 iters, 148.03s (92.5 ms/iter incl. audits)
  iter    400  exact max gain 0.012221 ICM chips/hand
  iter   1600  exact max gain 0.000964 ICM chips/hand
```

148s for a converged 6-handed ICM Tier 1 spot to 0.001 ICM chips/hand — audits (8 of them, ~11.4s
each, ~91s) are now the majority of that time, not the CFR+ iterations (1600 x 35.7ms ≈ 57s). This
is the cost Sec 4's "not built" fix would remove.

**The fix, precisely scoped, not built.** The same recipe as `pricer3.terminal_values`
(`burch-tier1-solve.md` Sec 4) applies to the "simple" (FIXED/TWO/PAIR) terms directly: add
`zid`/`rank` to `icm_pricer3.SeatPlan`, aggregate by `zid` at `rank == 0`, drop the `mine` factor.
It does **not** directly apply to the six-order 3-way terms, because those are already batched by
`(target, layout, free, later)` — a coarser grouping than "one terminal" — before `zid` is even
visible; a fast ICM audit needs those regrouped by `(zid, layout, free)` instead, which means
carrying `layout`/`free`/`zid`/`rank` as four more *ungrouped* per-row arrays and re-running the
group/`_three_way` batching at audit time. Mechanical, same formulas, but four new arrays and a
second grouping path — I did not build it this session; not asking anyone else to, either, unless
a chart needs faster ICM checks than "`check_every=200`, wait" gives.

## 5. What is not done

- No `FastAuditor` for ICM (Sec 4).
- Equal stacks only (same as chip EV Tier 1 and bowling's `tier1.py`): no short-stack open
  clipping, no forced-post handling.
- Only field compositions of the shape `(stack,) * (4-n)` tested (matching bowling's convention);
  `bard-scenario-grid.md`'s point that stack config and ante each need their own axis applies here
  too, untouched.
- SEED sweep on the 3-way tables still not done (`burch-open3bet-tree-and-cost.md` Sec 8);
  ~~a 0.001 ICM-chips/hand target is likely below that unmeasured noise floor~~. **Measured and
  corrected 2026-09-27** in `burch-seed-noise-floor.md`: on the 6-handed 15bb Tier 1 spot the
  reported exploitability moves at most 7.4e-7 ICM chips/hand across three independent table
  seeds, so the 0.001 target is ~1000x above the floor and is not noise-limited.

## 6. What would change my mind

- If the n=6/9 ICM solve (once it finishes, or on a rerun with a longer budget) disagreed in
  direction or magnitude with the n=2/3 pattern above, or with a spot-check from
  `tier1_check.solve_generic` at that seat count, I'd stop trusting `icm_pricer3` past n=4 until
  reconciled.
- If check A's max |diff| grew rather than held steady from n=6 to n=9, that would suggest an
  actual bug rather than float32 noise (noise should not systematically grow with tree size beyond
  what more summed terms explains) and I'd want a float64 version of `_three_way` to separate the
  two before shipping a chart off n=9 ICM numbers.
