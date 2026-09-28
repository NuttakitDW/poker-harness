# The seed-noise floor of a Tier 1 chart: the exploitability number is 100-1000x more stable than the target

`burch`, 2026-09-27. Code in `deepstack-swarm/workspace/burch/seednoise/` and
`.../burch/seeds/`. Nothing in `pushfold/` edited; `tmp/` read but never written.

**Claim in one sentence.** Solving the 6-handed 15bb Tier 1 spot under three independent seeds of
the Monte Carlo 3-way tables moves the *reported* exploitability by at most **1.2e-6 bb/hand**
(chip EV) and **7.4e-7 ICM chips/hand** (ICM) — two to three orders of magnitude below the
0.0001 bb/hand and 0.001 ICM-chips/hand targets already reported — while the *chart itself* moves
by a combo-weighted dTV of **0.0015–0.0020** (chip) and **0.0004–0.0011** (ICM), with individual
hand classes at close call-off nodes moving by up to **0.25** in frequency, so the targets are not
noise-limited and `SAMPLES` does not need raising.

This **corrects** the last bullet of `burch-icm-pricer3.md` §5 ("a 0.001 ICM-chips/hand target is
likely below that unmeasured noise floor"). Measured, it is not; the floor is ~1e-6.

## 1. Game and what moves

Spot: Tier 1 (open-or-jam), n = 6, equal 15bb stacks, sb 0.5 / bb 1, no ante, fee 0, cap 3,
`floor3.build(tier1=True)` — 125 nodes, 131 terminals (1 allfold / 25 uncontested / 105 showdown /
0 flop). ICM: 50/30/20, `field=()`. CFR+, 2000 iterations, exact audit every 200. Average
strategy returned by `coach3.State.average()`.

The **only** source of randomness in a solve is `oddsmaker.three_way()` (`eq3`, `pw`). `floor3`,
`cashier3`, `coach3`, `pricer3`/`icm_pricer3` and `seqbr3`/`seqbr` contain no RNG. Verified, not
assumed: two fresh 200-iteration runs of seed A give bitwise-identical strategies and identical
exploitability, `0.01496719740817008` for chip EV and `0.025838582382004288` for ICM, matching the
recorded control to all 17 digits. So tables are the only source of movement, and any chart
difference below is attributable to them.

### Seeds

`oddsmaker.SEED` is a module global read at call time by `build_three_way` (per-chunk seeds are
`SEED + chunk_index`, 818,480 triples in 256-triple chunks). Nothing was edited: the workspace
builder rebinds `oddsmaker.SEED` and calls `build_three_way(samples=2000)`.

| seed | base | chunk-seed range | source |
|---|---|---|---|
| A | 20260924 | 20260924 – 21079404 | production, `tmp/pushfold-e3.npz`, read-only |
| B | 30260924 | 30260924 – 31079404 | `seeds/e3-seedB.npz`, built this session |
| C | 40260924 | 40260924 – 41079404 | `seeds/e3-seedC.npz`, built this session |

Bases are 10^7 apart so no chunk seed is shared with A or with each other. Independence is
verified, not assumed: `rms(eq3_A - eq3_B) = 0.01395`, against `sqrt(2) x 0.00982 = 0.01389`
predicted from an *independent* 32-batch re-measurement of the same triples (§4) — agreement to
0.4%, exactly the signature of two independent draws at `samples=2000`. Build cost 739 s and 641 s
on 13 cores.

### Injection point

Every reader of the 3-way tables bottoms out at `oddsmaker.three_way` looked up in the module dict
at call time: `oddsmaker.orders()` (lru-cached) feeds `icm_pricer._layouts()`, and
`pushfold.pricer._three_way()` (lru-cached) feeds `pricer3` and `icm_pricer3`;
`seqbr.tables()` (uncached) feeds `seqbr3.Auditor`'s leaf. So one rebind of
`oddsmaker.three_way` plus `cache_clear()` on the four caches above it swaps the whole game.
`oddsmaker.two_way` (e2) is exact and seed-independent, so it is left alone.
`seednoise/tableswap.py` does this in 20 lines and is the cleanest injection point I found.

## 2. Reproduce

```
.venv/bin/python deepstack-swarm/workspace/burch/seeds/build_tables.py 30260924 deepstack-swarm/workspace/burch/seeds/e3-seedB.npz
.venv/bin/python deepstack-swarm/workspace/burch/seeds/build_tables.py 40260924 deepstack-swarm/workspace/burch/seeds/e3-seedC.npz
.venv/bin/python deepstack-swarm/workspace/burch/seednoise/noise.py solve A B C   # 2000 iters x 2 modes x 3 seeds
.venv/bin/python deepstack-swarm/workspace/burch/seednoise/noise.py cross         # 3x3 x 2 modes re-audit grid
.venv/bin/python deepstack-swarm/workspace/burch/seednoise/control.py             # uniform + 200-iter controls
.venv/bin/python deepstack-swarm/workspace/burch/seednoise/decompose.py           # value vs gain split
.venv/bin/python deepstack-swarm/workspace/burch/seednoise/analyze.py             # chart dTV
.venv/bin/python deepstack-swarm/workspace/burch/seednoise/mc_se.py 400 32 2000   # per-entry MC error
```

Harness unchanged: seed A reproduces `burch-icm-pricer3.md`'s n=6 ICM trajectory exactly
(0.000964 ICM chips/hand at iteration 1600, and my trail has it at index 7).

## 3. (a) Valuation noise: a fixed strategy, audited under each seed's tables

`noise.py cross` audits each seed's converged profile under all three table sets. This is the
number that answers "how far can a *reported* exploitability move because the tables moved".

**chip EV, bb/hand** (rows = profile solved under, columns = tables audited under)

| | A | B | C |
|---|---|---|---|
| A | 0.00025885 | 0.00025881 | 0.00025978 |
| B | 0.00025773 | 0.00025764 | 0.00025859 |
| C | 0.00025755 | 0.00025740 | 0.00025840 |

max \|cross − own-seed audit\| = **1.0e-6 bb/hand** (C's profile: 0.00025740 under B vs 0.00025840
under C).

**ICM, ICM chips/hand**

| | A | B | C |
|---|---|---|---|
| A | 0.00064901 | 0.00064897 | 0.00064912 |
| B | 0.00064979 | 0.00064975 | 0.00064990 |
| C | 0.00064895 | 0.00064892 | 0.00064905 |

max \|cross − own\| = **1.5e-7 ICM chips/hand** (B's profile: 0.00064975 under B vs 0.00064990
under C).

Where the noise goes (`decompose.py`, seed A's converged profile, the three terms `seqbr.audit`
returns; `gain = BR value − profile value`, `exploitability = max_seat gain`):

| term | chip spread (bb/hand) | ICM spread (ICM chips/hand) |
|---|---|---|
| `ev` (profile value, worst seat) | 2.48e-5 | 2.94e-6 |
| `gain` (worst seat) | 2.47e-6 | 5.40e-7 |
| exploitability (`max_seat gain`) | 9.7e-7 | 1.5e-7 |

The exploitability is ~10x more stable than the profile value it is built from, because a near-
optimal profile's best response and its own value shift the same way when the tables move. That is
a measured cancellation, not an argument.

## 4. Per-entry table error, and a negative result on `orders()`

`mc_se.py`, 400 random feasible triples x 32 independent batches x 2000 deals (96 s):

- per-entry Monte Carlo SE at `samples=2000`: **eq3 median 0.0098**, **pw median 0.0102**.
- `orders()` is `clip(pw - eq3, 0)`, a nonlinear function of two noisy means, so I checked for a
  clip bias: across all 400 x 32 x 3 matched (pair, triple, batch) samples, `pw < eq3` happened
  **0 times**, so the clip never fires and introduces no bias. (An earlier run reported 3.5%; that
  was my own column-misalignment bug, comparing `pw` for one pair against `eq3` for a different
  seat. Corrected, the rate is exactly zero. `eq3 <= pw` holds term by term by construction.)
- Implied SE of one row of `sum_gk PRIOR[g] PRIOR[k] eq3[h,g,k]`, if entries were independent:
  7.2e-5.

## 5. (b) Chart movement: bard's combo-weighted dTV

dTV(node) = `sum_h PRIOR[h] * |p1[node,h] - p2[node,h]|`, maximised over the node's actions
(per-action dTV is the mass moved at that node; for a 2-action node the sum over actions is 2x it).
Seat strategies are `coach3.State.average()`, which accumulates with own-reach weights.

| pair | chip dTV max (node) | ICM dTV max (node) |
|---|---|---|
| A–B | 0.00196 (node 16) | 0.00043 (node 56) |
| A–C | 0.00151 (node 16) | 0.00071 (node 56) |
| B–C | 0.00158 (node 56) | 0.00114 (node 56) |

- **max per-node delta** (largest single `|p1[h] - p2[h]|` anywhere): chip **0.138 / 0.183 / 0.200**,
  ICM **0.095 / 0.157 / 0.252**.
- Reach-restricted, so this is not an unreachable-node artifact: over the 61 chip / 64 ICM nodes
  whose scalar reach exceeds 1e-3, the chip maxima are 0.0011–0.0016 and the ICM maxima
  0.0003–0.0011. The argmax node is reachable in both.
- Reach-weighted mean dTV: chip 2.1e-4 – 2.7e-4, ICM 9.9e-5 – 1.4e-4.
- Concentration: the top 10 nodes carry 32% (chip) / 41% (ICM) of the total weighted movement;
  93 of 125 chip nodes and 60 of 125 ICM nodes move by more than 1e-4.

**Where it moves** — all at close call-off decisions, which is the expected mechanism (regret
matching has no grip where a class sits on the indifference boundary):

- chip A–B: node 16, seat 5, `(fold, call 14)` facing one raise — dTV 0.00196, worst class **ATo**
  moving 0.061; node 70, seat 1 (BB), `(fold, all-in)` facing an open — worst class **66** moving
  0.124.
- ICM B–C: nodes 54/56/59, all seat 1 (BB), `(fold, call 12.8)` facing a 3bet-jam — dTV 0.00114,
  worst class **KK** moving **0.252**.

## 6. (c) Controls: non-adapted profiles, same three tables

`control.py`. Same tables, same audit code, profiles that did not adapt to them:

| fixed profile | chip spread (bb/hand) | ICM spread (ICM chips/hand) |
|---|---|---|
| uniform (e ≈ 2.04 / 2.94) | 3.42e-4 | 1.09e-4 |
| seed A at 200 iters (e ≈ 0.0150 / 0.0258) | 3.73e-6 | 7.83e-7 |
| seed A converged (e ≈ 0.00026 / 0.00065) | 9.7e-7 | 1.5e-7 |

The control matters: the audit machinery does respond to the tables (a 2.04 exploitability moves
by 3.4e-4), so §3's small numbers are insensitivity of a near-equilibrium profile, not a frozen
table. It also bounds the floor for a *bad* profile: 3.4e-4 bb/hand is above the 1e-4 chip target,
so the floor is target-relevant only if we ever publish an unconverged number. We audit the
converged average, so we are not in that regime.

## 7. (d) The resulting noise floor

| quantity | chip EV | ICM |
|---|---|---|
| re-solved exploitability, spread over seeds at 2000 iters (diagonal of §3) | 1.2e-6 bb/hand | 7.4e-7 ICM chips/hand |
| same, as σ (n=3 range understates σ by 1.69) | ≈ 7e-7 bb/hand | ≈ 4.4e-7 ICM chips/hand |
| fixed converged profile, cross-audit displacement | 1.0e-6 bb/hand | 1.5e-7 ICM chips/hand |
| "do not report below this" (≈ 3σ, conservative) | **2e-6 bb/hand** | **1e-6 ICM chips/hand** |
| recommended stated floor | **1e-5 bb/hand** | **1e-5 ICM chips/hand** |

versus the targets already reported:

- chip target **0.0001 bb/hand** → 50–100x above the floor. Not noise-limited.
- ICM target **0.001 ICM chips/hand** → 1000–5000x above the floor. Not noise-limited.

**So: do not raise `SAMPLES` for these targets.** The floor scales as `1/sqrt(samples)`; making it
10x smaller needs 100x the deals, i.e. `SAMPLES=200,000`, roughly 13.5 h of table build instead of
485 s. Nothing at the current targets argues for that.

Two caveats I am not glossing over:

1. **This measures variance, not bias against the true game.** A, B and C are three draws around
   the exact tables; this sweep cannot see how far the *sampled* game is from the true one. The
   closest estimate I can give is the value displacement of a fixed profile between two draws,
   2.48e-5 bb/hand, so `|value(A) - value(true)| ≈ 1.8e-5 bb/hand` (dividing by `sqrt(2)`). That is
   four orders below one big blind and does not threaten any of the numbers above, but if anyone
   starts quoting a chip-EV *value* (not an exploitability) to five decimals, that bias, not the
   floor here, is the term to check. An exact 3-way table would settle it.
2. **One spot.** Everything above is n=6, 15bb, equal stacks, no ante, no field, `field=()`. The
   mechanism is spot-independent but the constant need not be; n=9, ante, short-stack call-offs or
   a padded field each deserve their own sweep before a *chart-wide* floor is quoted. I am not
   claiming a chart-wide floor, I am claiming this spot's.

## 8. What this means for the join with davis

The two columns of §5 answer different questions and should not be conflated:

- the **exploitability claim** is safe at 1e-4 chip / 1e-3 ICM — the tables cannot move it more
  than ~1e-6;
- the **chart** is not reproducible to better than dTV ≈ 0.002, and at the handful of near-
  indifferent call-off nodes an individual class can move by 0.25 in frequency (KK at the BB
  facing a 3bet-jam, ICM B vs C).

If davis's lifetime-of-play ceiling says a player can detect a chart difference below dTV 0.002,
then the honest statement is not "raise SAMPLES" — raising samples will not hold the *chart*
still, because the movement is regret-matching arbitrating between near-equal actions, not a
noisy number. The fix for that is a selection rule (e.g. report a strategy that is stable across
seeds, or check the DC of the moved cells) and it is a different piece of work from this one.

## 9. What would change my mind

- A second spot (n=9, or 15bb with a padded field, or short stacks where the call-offs are closer)
  moving the reported exploitability by more than 1e-5. That would make the floor spot-specific in
  a way that matters and I would want the sweep extended before quoting any chart-wide number.
- A `FastAuditor` for ICM whose number disagrees with `seqbr3.Auditor` by more than 1e-6. At that
  point the audit route, not the tables, is the binding uncertainty and this floor is moot.
- Evidence that the *sampled* game is systematically biased rather than merely noisy — e.g. an
  exact 3-way table showing the converged ICM exploitability moving in one direction for every
  seed. Three seeds cannot distinguish that from noise; an exact table can.
- If the stop rule is ever used with `max_iters` truncation (rather than convergence), §6's
  uniform row applies: the floor for an unconverged profile is 3.4e-4 bb/hand, above the chip
  target.

## 10. Files

- `workspace/burch/seednoise/tableswap.py` — injection (rebind + 4 cache clears).
- `workspace/burch/seeds/build_tables.py` — seeded table build, writes to workspace only.
- `workspace/burch/seednoise/noise.py` — `solve <seed>` / `cross`.
- `workspace/burch/seednoise/control.py`, `decompose.py`, `analyze.py`, `mc_se.py`.
- Data: `seeds/e3-seedB.npz`, `seeds/e3-seedC.npz` (20 MB each), `seednoise/solve-{A,B,C}.npz`,
  `seednoise/noise.npz`, `analysis.json`, `control.json`, `decompose.json`, `mc_se.npz`.
