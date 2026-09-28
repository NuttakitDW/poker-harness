# Current vs average at exit: it depends on the game, so measure both

`burch`, 2026-09-28. Standing question 1 off my own list, prompted by `bowling-tier1-*.md` and by
the Tier 1.5 convergence result (`burch-tier1.5.md`). Nothing in `pushfold/` edited.

**Claim in one sentence.** At the stop rule's exit, the *current* strategy described by the final
regrets beats the *average* strategy the solver returns in the games that converge slowly (6max
15bb, Tier 1.5 15bb -- by 2.1-2.3x) and loses to it badly in the small games that converge fast
(3max 15bb and 30bb -- by 3.1-3.6x), so Cepheus's "current beat average" (`Burch 2017` thesis 4.3)
does not transfer as a rule and both must be measured per game.

## Game

NLHE, preflop only, cap 3, `fee = 0`, chip EV, 169 classes, `method=cfr+`, `check_every=25`,
target 0.001 bb/hand. Tier 1 = `tier1=True`, Tier 1.5 = `tier15=True`. Exact max gain from
`seqbr3.FastAuditor`, which agrees with the reference `seqbr3.Auditor` to 1e-12 on these trees.

## The measurement

| game | iters at exit | gain, average | gain, current | ratio (avg/cur) |
|---|---|---|---|---|
| Tier 1, 3max 15bb | 375 | 0.000994 | 0.003580 | 0.28 |
| Tier 1, 6max 15bb | 1025 | 0.000954 | **0.000409** | **2.33** |
| Tier 1, 3max 30bb | 275 | 0.000906 | 0.002787 | 0.33 |
| Tier 1.5, 3max 15bb | 425 | 0.000951 | **0.000455** | **2.09** |

Run: `.venv/bin/python deepstack-swarm/workspace/burch/open3bet/curvavg.py`;
`seqbr3.FastAuditor(g, plan).audit(st.average())` vs `.audit(st.sigma)`.

## Reading

- **The average wins where the game is small.** 3max converges in 275-425 iterations; the early
  iterations are a small fraction of the linear-weight average, and CFR+'s `weight = t` has already
  washed them out, so the average is the better object.
- **The current wins where convergence is slow.** 6max (1025 iters) and Tier 1.5 (a seat acting
  twice) are the two hardest cases here, and there the current is more than twice as good. The
  average is a lagging estimator; when the tail is long, the lag is what is being measured.
- **The pattern is a lag, not a property of the method.** Both rows where the current wins are the
  rows with the most iterations to exit, which is the same `T^-0.4`-versus-fast split as
  `burch-tier1.5.md`. It is evidence for "the average lags", not for "the current is better".
- **What it costs the stop rule.** At 6max 15bb the rule stopped when the *average* hit 0.000954,
  but the *current* was already at 0.000409 -- it ran ~2.3x longer than it needed to. That is wasted
  time, not a safety problem, and it is the mirror of the failure I would have worried about.

**Do not read this as licence to ship the current strategy.** The average is the object the regret
bound covers; the current has no convergence guarantee and its advantage here is an observation at
one exit point, not a trajectory. Cepheus could ship the current because at cluster scale the
current had stabilised; these games have 275-3000 iterations, not days. Anyone wanting to ship the
current in this repo should show the current's gain is stable over a window, not just lower at exit.

## What would change my mind

A game where the current wins at *few* iterations (would make this a method property rather than a
lag). A current strategy whose advantage disappears when the average is recomputed from a warm start
at the exit point. And a per-game trajectory of both curves rather than a single exit point -- I have
one number per game, which is the weakest part of this.

## Reproduction

`.venv/bin/python deepstack-swarm/workspace/burch/open3bet/curvavg.py` (writes `curvavg.log`).
