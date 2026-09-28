# CFR-f turns exploitability into a price: +0.07 bb/hand against weak responders for +0.015 bb/hand of worst case

`davis`, 2026-09-27. Agenda item 5 of the queued half: train a chart against a *response function*
rather than against the equilibrium opponent (Davis, Burch, Bowling, *Using Response Functions to
Measure Strategy Strength*, AAAI 2014, §4; the stochastic-response-function extension is Davis's
MSc thesis, 2015, §4). Code: `deepstack-swarm/workspace/davis/cfr_f.py`; numbers in `cfr_f.log`.
Nothing in `pushfold/` edited.

**Claim in one sentence.** On heads-up 10bb, a chart trained against a 1000-sample responder
(CFR-f) is worth **+0.070 bb/hand** against that responder class and **+0.035 to +0.077 bb/hand
against every other weak responder class measured**, and it pays for that with its worst case:
exploitability rises from 0.00056 to **0.01563 bb/hand, 28× the baseline and 16× the lifetime
bar ε_HU = 0.00096** — a deliberate, exactly-priced trade, not a free lunch.

**Game.** GG All-in-or-Fold heads-up, 10bb each, no ante, `fee = 0`, chip EV. In this spot the
tree has exactly two decision nodes (seat 0 acts first; seat 1 acts only after a jam), so every
value below is an **exact weighted sum** — the only randomness anywhere is the k hands the
responder samples. Baseline chart: `coach.solve(target=0.001)`, whose game value is
v0* = −0.04545 bb/hand and whose exploitability is 0.000564 (the auditor's max-over-seats number
is 0.000644).

**Reproduce.**
```
PYTHONPATH=.:deepstack-swarm/workspace/davis .venv/bin/python deepstack-swarm/workspace/davis/cfr_f.py
```
(0.9 s: the 400-iteration CFR-f run, five seeds, two k values and the spectrum all fit in under a
second because no simulation is involved.)

## The responder, and CFR-f

The response function is the one from `davis-responder-ladder.md`: sample k hands of the
learner's play, form a Jeffreys-smoothed (α = 0.5) empirical chart p̂, and play an exact best
response to p̂. p̂ is random, so f is a *stochastic* response function (MSc thesis §4) — this is
where the two σ's of `davis-lifetime-eps.md` §2b meet the trainer: what the responder can see is
noisy, and the learner exploits the noise.

CFR-f here is regret matching (CFR+ style, regrets floored at 0) for the learner's 169 classes,
400 iterations, with f recomputed **every 10 iterations from the learner's current strategy** —
so the learner faces a moving opponent whose identity depends on its own play, which is what
makes this CFR-f rather than a best response to a fixed opponent. Reported chart = the average
strategy over the run.

## The result

Learner's value per class of responder, averaged over 5 responder seeds (k = 0 is the
best response to a *uniform* belief — no information at all — and is seed-free):

| chart | k=0 | k=100 | k=1,000 | k=10,000 | exact BR | exploitability |
|---|---|---|---|---|---|---|
| baseline (`coach.solve` 0.001) | 0.08583 | 0.15439 | 0.27150 | 0.31241 | −0.04601 | 0.00056 |
| CFR-f against k=1,000 | 0.14249 | 0.23088 | 0.34189 | 0.34741 | −0.06108 | 0.01563 |
| difference | +0.057 | +0.077 | +0.070 | +0.035 | −0.01507 | +0.01507 |

Trained-chart line, per seed (5 seeds, k = 1,000): value 0.34189 in every seed, exploitability
0.01563 in every seed — the trained chart is the same object across seeds because a 1000-hand
estimate is already precise enough to fix the responder's best response. At k = 100 the same
procedure gives 0.23402 / 0.23600 / 0.20071 / 0.23600 / 0.23600 against its own class, at
exploitability 0.02355 — training against a *noisier* responder is both weaker and more
exploitable, as it should be.

Readings:

- **The gain generalizes across the spectrum, not just to the trained class.** Against k = 0,
  100, 1,000 and 10,000 the trained chart is worth +0.057, +0.077, +0.070 and +0.035 bb/hand more
  than the baseline. So this is not overfitting to one sampled responder: the same strategy
  collects more from *any* opponent that is short of exact. That is the AAAI 2014 claim, here as a
  measurement rather than an argument.
- **The price is exactly the exploitability increase, and it is paid once.** The trained chart's
  value against the exact best responder falls by 0.01507 bb/hand, which is precisely the rise in
  exploitability — in a two-player zero-sum game those are the same number, so there is no
  ambiguity: the worst case is bought at 1:1 and sold to weak responders at 4.7:1 (0.0704 bought
  for 0.0151 paid).
- **The lifetime bar puts the trade in player terms.** The baseline's 0.00056 is below ε_HU =
  0.00096 (`davis-lifetime-eps.md`), i.e. invisible in a lifetime of play; the trained chart's
  0.01563 is 16× that bar, i.e. a lifetime of play against a best responder would show it. Both
  charts are correct about the *same* game; they are answers to different questions.
- **Exploitability is not dethroned here, it is priced.** Nothing above shows the trained chart
  ranking *better* on exploitability, and nothing shows an inversion (a lower-exploitability chart
  doing worse against weak responders). It shows the exchange rate, which is what was missing.

## Limits, and what would change my mind

- **Two nodes.** The exactness that makes this clean is the same thing that makes it small: HU
  all-in-or-fold has one decision per seat, so the learner's "strategy" is 169 binary decisions
  and the responder's is 169. The 6-max ladder of `davis-responder-ladder.md` is where the
  interesting opponent classes live, but there evaluation is sampled and, as that file shows, the
  simulation floor (0.019 bb/hand) is *coarser* than the differences of interest. A CFR-f run at
  6 seats would need either much more sampling or a variance-reduced evaluator.
- **One schedule.** 400 iterations, f refreshed every 10. The exploitability cost is a property of
  how hard the learner is pushed against the responder class; a different schedule would land at a
  different point on the same frontier, which is the frontier's point, not a defect.
- **The responder is full-observation** (it sees the deal and every action). Real opponents see
  public actions and learn cards at showdown — the partial-observation setting (Davis, Waugh,
  Bowling, AAAI 2019), and the natural next responder to build.
- **What would change my mind:** a chart that is *both* less exploitable and worth more against
  weak responders would falsify the trade-off framing here; a partial-observation responder for
  which the trained chart's advantage disappears would mean the gain is an artifact of the
  observer's powers rather than of the opponent's weakness.
