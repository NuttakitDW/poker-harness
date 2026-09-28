# Exploitability ranks this chart but understates what it collects from weaker responders by 35–500×

`davis`, 2026-09-27. The second half of agenda item 2: strategy strength *beyond* worst-case
exploitability (Davis, Burch, Bowling, *Using Response Functions to Measure Strategy Strength*,
AAAI 2014). Code: `deepstack-swarm/workspace/davis/responder_ladder.py`. Nothing in `pushfold/`
edited.

**Claim in one sentence.** Measured at one 6-max chip-EV spot, the chart's exploitability is
0.70 mbb/hand — invisible to a lifetime of play — while responders that are merely *worse than
best* lose it 24 to 351 mbb/hand, i.e. **35×, 398× and 503× the exploitability** (21×, 246× and
310× the lifetime bar ε), so the worst-case number is not a bound on what the chart actually
collects, only a rank.

**Game.** GG All-in-or-Fold, 6 seats, 10bb, `ante=1.0` in `bb` mode, `fee=0`, chip EV, plain
`coach.solve` (CFR+, `target=0.001`, 75 iterations, 0.00075 reached). Seat 2 is the responder;
the other five seats play the chart. 400,000 hands, seed 20260927, **common random numbers
across every rung** (same deals, same action draws), so rungs are compared paired. Lifetime
ε for this spot is 0.001132 bb/hand (`davis-lifetime-eps.md` §2).

**Reproduce.**
```
PYTHONPATH=.:deepstack-swarm/workspace/davis .venv/bin/python deepstack-swarm/workspace/davis/responder_ladder.py
```

## The ladder

| rung | what it is | responder bb/hand | se | vs self-play | se | × ε | × exploitability |
|---|---|---|---|---|---|---|---|
| self | chart vs itself | 0.33388 | 0.00721 | — | — | — | — |
| static | stale chart (solved for no ante) in that seat | 0.30961 | 0.00594 | −0.02427 | 0.00895 | 21× | 35× |
| k=0 | BR to a uniform belief (no samples at all) | −0.01749 | 0.01203 | −0.35137 | 0.01402 | 310× | 503× |
| k=100 | BR to an empirical chart from 100 hands | 0.05578 | 0.01157 | −0.27810 | 0.01363 | 246× | 398× |
| k=1,000 | … from 1,000 hands | 0.23549 | 0.01003 | −0.09839 | 0.01229 | 87× | 141× |
| k=10,000 | … from 10,000 hands | 0.33050 | 0.00815 | −0.00339 | 0.01044 | not resolved | — |
| k=100,000 | … from 100,000 hands | 0.33521 | 0.00734 | +0.00133 | 0.00998 | not resolved | — |
| BR | auditor's exact best response | 0.33352 | 0.00717 | −0.00036 | 0.00989 | not resolved | — |

(× ε uses ε = 0.001132 bb/hand; × exploitability uses the exact 0.000698 bb/hand.)

The k-sample responder is the frequentist analogue of CFR-UCT(k) (AAAI 2014, §5): it samples k
hands of the chart's play, forms a smoothed empirical chart p̂(node, class) — Jeffreys prior
α = 0.5 on each action, so an unseen cell falls back to uniform play — and plays an exact
best response *to the estimate*. k→∞ recovers the exact best response. With 100,000 hands the
sample covers 6,756 of 6,760 (node, class) cells; with 100 it covers a few dozen, which is the
whole point of the weak rungs.

**Resolution limit, stated because it bounds the table.** The CRN paired sd of the gain is
6.25 bb/hand — larger than σ_hand, the same effect measured in `davis-lifetime-eps.md` §2b — so
at 400,000 hands anything below 0.0194 bb/hand is unresolved. The k ≥ 10,000 rungs and the BR
rung are therefore *indistinguishable from self-play in simulation*; only the weak rungs are
resolvable. The exact BR number is not taken from the table but from `auditor.audit`, which is
exact: the chart's gain at seat 2 is **0.000698 bb/hand**.

**Validation.** (i) Auditing the strategy extracted as the best response finds a remaining gain
of exactly 0.0000000 at that seat — the extraction is a true best response, not an
approximation. (ii) The simulated BR value 0.33352 (se 0.00717) against the auditor's
`ev + gain` = 0.33995 differs by −0.0064, i.e. 0.9 se of the simulation; the audit number is
exact and the simulator's mean is what carries error. Nothing here needs the simulator to
resolve anything smaller than the weak-rung effects.

## What this says, and what it does not

- **Exploitability ranks, it does not bound.** 0.70 mbb/hand is the worst case, and it is real:
  against the exact best responder the chart loses 0.70 mbb/hand, below the lifetime bar and
  invisible in play. But against a responder that merely *guesses wrong* about the chart, the
  chart collects 24–351 mbb/hand. Which of the two describes a real opponent is an empirical
  question about opponents (bard's), not about the solver.
- **The curve is monotone in responder strength**, as the response-function framing requires:
  value rises with k and plateaus near the self-play value. Nobody needs to trust one rung;
  the ladder is the object.
- **A best response to a wrong belief is a bad strategy, and that is the measurement.** k=0
  (jamming the "best" hands against a uniform field) loses more than the static chart does.
  Weak responders are not "best responses with less compute", they are a different, and worse,
  class of opponent — worth separating from a *time-limited* best responder, which is a rung
  this ladder does not have.
- **Limits.** One spot, one seat, one chart, chip EV only (an ICM ladder at the bubble would
  need the `payouts` path and is not run here); the k-sample responder is *full-observation*
  (it sees the deal and every action), which is optimistic — a real opponent sees only public
  actions and learns hole cards at showdown, the partial-observation setting (Davis, Waugh,
  Bowling, AAAI 2019). The ranking question — does a lower-exploitability chart do *worse*
  against weak responders, the AAAI 2014 inversion? — needs a second chart put through this
  same ladder and is **not** measured here.

## The inversion test: attempted, not detectable at this design

Two charts of the same spot, targets 0.003 (exploitability 0.00163, seat-2 gain 0.001465) and
0.0005 (0.00043 / 0.000421), i.e. a 3.8× gap in the worst case, put through the identical ladder
at seat 2 with the same deals and draws (`inversion.py`):

| rung | t=0.003 | t=0.0005 | diff | se(diff) |
|---|---|---|---|---|
| self | 0.33531 | 0.33274 | −0.00257 | 0.00987 |
| static | 0.31032 | 0.30996 | −0.00036 | 0.00799 |
| k=100 | 0.05517 | 0.05357 | −0.00160 | 0.01603 |
| k=1,000 | 0.23566 | 0.23492 | −0.00074 | 0.01388 |
| k=10,000 | 0.32248 | 0.32562 | +0.00314 | 0.01128 |

**No inversion — and the test has no power at this chart separation.** Every difference is inside
1.96 se; four of the five rungs nominally favour the *lower*-exploitability chart, so the two
criteria agree in sign everywhere they say anything. But with a CRN paired sd of ~6 bb/hand and
400,000 hands, the resolution is 0.019 bb/hand while the differences to be detected are ≤ 0.003,
so resolving them needs ~1.6e7 hands *per rung per chart* — 40× more simulation than this run,
for a test whose answer is already "the charts are too similar" (8.6% dTV, §2b of
`davis-lifetime-eps.md`).

What this rules out and what it does not: it rules out a *gross* inversion between two charts this
close (a difference of ≥ 0.02 bb/hand in the weak-rung value would have shown); it does not rule
out an inversion at the 0.001–0.003 bb/hand level, which is where the interesting region is and
which this estimator cannot reach. The way to get power is not more hands but a bigger contrast —
a chart trained *against* a weak responder (CFR-f, AAAI 2014 §5) rather than two charts that
differ only by a stop target — or the variance-reduced evaluation of the baselines paper (ICML
2020). Both are builds, not runs.

**What would change my mind.** A second chart whose exploitability is lower but whose weak-rung
values are worse than this chart's would demonstrate the 2014 inversion in this repo; a
partial-observation responder (showdown-only card information) producing a materially different
ladder would change the read on which rung resembles a real population.
