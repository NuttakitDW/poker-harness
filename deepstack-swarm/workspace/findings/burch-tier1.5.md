# Tier 1.5: the 3bet is worth 0.0002 bb/hand at 15bb and 0.041 at 30bb

`burch`, 2026-09-28. Implements `open3bet-design.md` Sec 15. All numbers `.venv/bin/python` from
the repo root; nothing in `pushfold/` edited.

**Claim in one sentence.** Tier 1.5 (`floor3.build(..., tier15=True)`) is built, solves, and is
leaf-free at equal stacks, and the action it adds is worth what `bowling` said it was worth: at
30bb the Tier 1 chart loses **0.041 bb/hand** (41x the 0.001 lifetime bar) inside the Tier 1.5 game,
against **0.0002** at 15bb -- a 200x growth with depth, tracking a 3bet that goes from 13-22% of
hands at 15bb to 22-37% at 30bb.

## Game

NLHE, preflop only, cap 3, `fee = 0`, sb 0.5 / bb 1, no ante, 169 classes, chip EV, `method=cfr+`,
`check_every=25`, target 0.001 bb/hand unless stated. Equal stacks (Tier 1.5 is leaf-free only
there; see below).

## The change

One branch in `floor3.build`, behind a new opt-in flag `tier15` (default `False`):

| situation | Tier 1 (`tier1=True`) | **Tier 1.5 (`tier15=True`)** |
|---|---|---|
| unopened | fold, open 2.2bb, all-in | unchanged |
| facing one raise, not all-in | fold, all-in | **fold, 3bet to 3x, all-in** |
| facing a 3bet (`raises >= 2`), not all-in | (unreachable) | **fold, all-in** |
| facing an all-in | fold, call | unchanged |

The `raises >= 2` branch lost its `CALL` -- the trap in Sec 15 -- so `CALL` now appears *only* in
the facing-all-in branch at every seat and every depth, and a flat cannot reappear. Verified by
dumping the action set of all 24/286 nodes at 3max/6max: the only `(FOLD, CALL)` sets are
`facing_allin`, and `max_depth_of_own_decisions() == 2` (a seat still acts at most twice).

**Tier 1 is untouched.** `tier1=True, tier15=False` produces byte-identical nodes and terminals to
the pre-change build at n=2, 3, 6, 9, equal and uneven stacks (7 configurations checked) -- which
matters, because it is a frozen fingerprint.

## What the 3bet is used for, and what it is worth

`ab15.py`. All three numbers are exact `seqbr.audit`; the "Tier 1 in Tier 1.5" row embeds the
Tier 1 chart in the Tier 1.5 game (exact: Tier 1's action set is a subset at every shared decision,
so the 3bet column is simply zero).

| spot | P(3bet), seats 1/2 | zero the 3bet, max seat | **Tier 1 chart in Tier 1.5 game, max seat** |
|---|---|---|---|
| 3max 15bb | 0.132 / 0.220 | +0.00036 | **+0.00020** |
| 3max 30bb | 0.225 / 0.369 | +0.01186 | **+0.04106** |

The zeroing row is a *lower* bound on the action's value -- the seat keeps its fold/all-in
frequencies and is not allowed to re-optimise. The embedding row is the counterfactual `bowling`
asked about: a whole table that cannot 3bet, against opponents who can.

**At 15bb the 3bet is played often and is worth almost nothing** (0.0002, below the bar): a 15bb
3bet is close to a commitment, so fold/shove already spans the decision. **At 30bb it is worth
0.041**, an order of magnitude above the bar. That is the quantified form of "the single largest
way the current chart is not a 30bb chart", and it holds at the depth where `bowling-tier1-what-it-
computes.md` says the chart is otherwise most interesting.

**Caveat on the 30bb row.** The Tier 1.5 chart there is *not* converged: 20000 iterations reach
gain 0.00197 against a 0.001 target. Since a chart at gain g has EV at most g below the game value,
the cost is at least 0.041 - 0.002 = 0.039, so the 40x conclusion survives; but the exact figure
should be re-read from a converged chart.

## Tier 1.5 is much harder to solve than Tier 1 -- budget it

This is the first game in the project where a seat acts **twice** on a path (open, then face a
3bet), and the stop rule feels it. 3max 30bb, exact max gain:

| iters | 200 | 600 | 2000 | 6000 | 12000 |
|---|---|---|---|---|---|
| **Tier 1** | 0.00168 | 0.00020 | 0.00003 | -- | -- |
| **Tier 1.5** | 0.02186 | 0.00867 | 0.00522 | 0.00351 | 0.00267 |

Tier 1 collapses by 2000 iterations; Tier 1.5 follows roughly `T^-0.4` and is non-monotone
(0.00537 at 1600, 0.00522 at 2000). Reaching 0.001 at 30bb would take on the order of 1.4e5
iterations, about 50 min at n=3. At 15bb it is cheap and converges (425 iters at n=3, 1225 at n=6,
191 s; ICM n=6 0.0006 in 1750 iters, 565 s).

**Not an auditor artifact.** `seqbr3.FastAuditor` and the reference `seqbr3.Auditor` agree to
**1e-12** on the Tier 1.5 trees at 15bb and 30bb (they agree to 1e-12 on Tier 1 too), so the
exploitability being reported is the real one. It is also not the averaging: `coach3` weights the
average by this seat's own reach (`coach3.py:118-119`), which is the correct sequence-form average
and is exactly what a depth-2 seat needs.

## Leaf-freeness

Same as Tier 1, and for the same reason (`burch-tier1-flop-gap.md`):

| stacks | Tier 1.5 FLOP terminals, as-is | with `behind_cap=1` |
|---|---|---|
| 15 x3, 15 x6 (equal) | **0** | 0, byte-identical build |
| 3max (5,15,30) | 1 | 0 |
| 6max (4,8,15,20,30,15) | 27 | 0 |
| 6max (5,10,15,20,25,30) | 41 | 0 |

At equal stacks the guarantee is structural; at uneven stacks it is not, and `behind_cap=1` buys
it back at the cost of deleting a legal action -- use it as an A/B arm, not as the shipped rule.

## What would change my mind

A converged Tier 1.5 chart at 30bb giving a Tier 1 cost below 0.001 bb/hand would make the 30bb
row a 15bb-style null result. A game where a seat acts twice that converges as fast as Tier 1 would
make the budget section wrong rather than a property of depth-2 trees -- I have one instance, not a
law, and I have not shown the slow rate is about depth rather than about this particular
near-degenerate 30bb equilibrium.

## Reproduction

```
.venv/bin/python deepstack-swarm/workspace/burch/flopgap/ab15.py 3max
.venv/bin/python deepstack-swarm/workspace/burch/flopgap/ab15.py 3max30
.venv/bin/python deepstack-swarm/workspace/burch/open3bet/t15audit.py   # fast vs reference auditor
```

`ab15-3max.json`, `ab15-3max30.json` sit beside `ab15.py`. Tier 1.5 solves: `t15smoke.py`
(n=3 425 iters/9.5 s, n=6 1225/191 s, ICM n=6 1750/565 s). Convergence detail: `t15conv2.py`,
`t15loc.py`.
