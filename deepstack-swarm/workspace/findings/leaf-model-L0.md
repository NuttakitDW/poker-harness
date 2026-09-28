# L0 "checkdown": the flop leaf for ICM-OPEN3BET-v0

`moravcik`, 2026-09-27. Answers §3 of `workspace/bowling/open3bet-design.md`.

**Claim in one sentence.** A flop leaf that runs the board out with no more betting is exactly
computable with the code already in `pushfold/`, emits the distribution over final stacks that
`pushfold/icm.py` needs, and — measured, not argued — is **degenerate on its own**: priced by L0
alone, the BB flat-calls a 2.2bb open with **100% of hands**, so a realization model (L1) is not
polish, it is load-bearing.

**Game for every number below.** No-limit hold'em, preflop only, 3 seats (BTN/SB/BB), 15bb or
25bb equal stacks, sb 0.5, bb 1, no ante, no fee, Malmuth-Harville ICM with prizes 50/30/20
(`pushfold/icm.py`), 169 hand classes, opponents dealt independently (`pushfold/pricer.py:32-34`).
One leaf decision, **not a solve**: BTN opens to 2.2bb with the top 44% of hands by equity against
a random hand, SB folds, BB chooses fold or call.

**Reproduce.**

```
.venv/bin/python deepstack-swarm/workspace/moravcik/check_leaf.py       # exactness regression
.venv/bin/python deepstack-swarm/workspace/moravcik/flop_leaf_demo.py   # the numbers below
.venv/bin/python deepstack-swarm/workspace/moravcik/tie_bias.py         # §6
```

---

## 1. The specification

An ending of the preflop tree is fully described by two things:

* `alive`: the 1-3 seats still holding cards when preflop betting ends;
* `invested`: per seat, all n of them, chips put in the pot beyond the ante (folded seats keep
  whatever blind they posted; it is dead money).

**L0 rule.** Nobody bets again. All five board cards run out. The pot is awarded at showdown,
layered by `invested`; every seat keeps what it did not put in. The leaf's value is not a number:
it is the set of final-stack vectors, one per finishing order of the `alive` seats, each with the
chance of that order from the Oddsmaker. `pushfold/icm.py` prices each vector; the leaf value is
the sum of chance x value. That is the same shape `pushfold/icm_pricer.py:84-99` already uses for
all-in showdowns, so ICM concavity is respected by construction.

**No new equity tables are needed.** The flop has not been dealt when preflop betting ends, so a
checkdown runs out five unknown cards: the same distribution as a preflop all-in. Finishing-order
chances are `oddsmaker.two_way()` heads-up and `oddsmaker.orders()` 3-way, unchanged.

**Implementation:** `workspace/moravcik/leaf.py`. `Ending`, `settle`, `finals`, `worth`, plus the
`stackoff` dial of §4 and `from_pushfold` for the regression.

**Exactness anchor.** With `invested = cashier.contributions(spot, jammers)`, `leaf.settle` equals
`cashier.settle` and `leaf.worth` equals `icm_pricer._worth` to 1e-12 on all 8 push/fold spots in
`check_leaf.py` (heads-up, side pots, antes, BB all-in by posting, 6-handed, 0.2bb fee): `PASS`.
This matters beyond plumbing: **at SPR 0 the checkdown is not a model, it is the truth**, so the
leaf has zero error at one end of its range.

## 2. The interface for `burch` (this is the whole change)

Given `invested` and `alive`, **an all-in ending and a checkdown ending are priced by identical
code.** "Everyone is all-in" is just the case `invested = stack - ante`. The tree therefore does
not tell the pricer what kind of ending it is. Proposed patch to `pushfold/`, not applied:

1. `floor.Terminal` gains `alive: tuple[int, ...]` and `invested: tuple[float, ...]`.
   `Terminal.jammers` stops being the showdown set.
2. `cashier.settle(spot, jammers)` becomes `settle(spot, invested, alive)`. `contributions()`
   stays as the helper that builds `invested` for an all-in. Body is otherwise unchanged
   (`leaf.settle` is that body).
3. `pricer.plan`: `z.jammers` -> `z.alive`, and the `len(z.jammers) == 3` side-pot test ->
   `len(z.alive) == 3`.
4. `icm_pricer._worth`: one call site. `_terms` already keys off `z.alive` and needs nothing.

**Cost warning, measured.** `icm_pricer` pricing time is driven by 3-way endings, not by node
count: a 3-handed push/fold tree (7 endings, **one** of them 3-way) costs 2.5 ms per CFR iteration
across all seats; a 2-handed tree (3 endings, none 3-way) costs 0.1 ms. Count 3-way endings in the
v0 tree before estimating solve time.

## 3. The bias of L0, and its direction

L0 deletes every postflop decision. Four consequences, all one-directional:

1. **100% equity realization for every class.** L0 hands each class exactly its raw all-in equity
   share of the pot. Real realization varies by class. Low-playability hands (offsuit gappers,
   dominated aces) are the ones flattered.
2. **No postflop fold equity.** The preflop aggressor loses more from this than the caller: its
   range is stronger and it has the initiative. So L0 **undervalues opening and overvalues
   calling**.
3. **Position-blind.** The leaf value depends only on classes and the pot. Real in-position value
   is higher. So L0 most overvalues out-of-position calls — exactly the BB defend node.
4. **Understates chip variance.** A checkdown risks nothing behind; real postflop play moves the
   behind stacks. ICM is concave, so under-spread final stacks means **under-penalised risk**, and
   again too much calling. This one is directional but unquantified: real postflop betting is not
   a mean-preserving spread of a checkdown, because money correlates with hand strength.

All four push the same way. **Measured consequence** (25bb, opener's range top 44%): the worst of
the 169 classes has 0.293 equity against that range, and a checkdown call needs 1.2/4.9 = 0.245.
So under L0 the BB calls **100% of hands**, at 25bb and at 15bb. That is not a chart anyone can
ship, and it is not a defect of the implementation; it is what the model says.

**Where L0 is safe:** endings where nothing is behind (all-in preflop). Those are exact.

## 4. Two dials, one pricing path

`leaf.stackoff(spot, ending, sigma)` adds `sigma x (the chips two alive seats can still match)` to
every alive seat's investment. `sigma = 0` is the checkdown; `sigma = 1` is an automatic
stack-off, i.e. the leaf becomes a preflop all-in. It moves the **spread** of the distribution, not
the showdown chances, and both ends are exactly computable with no tuned parameter.

BB call range (PRIOR-weighted share of the 169 classes where calling beats folding):

| sigma | 25bb, distribution leaf | 25bb, scalar chip-EV leaf | 15bb, distribution | 15bb, scalar |
|---|---|---|---|---|
| 0.00 | 100.0% | 100.0% | 100.0% | 100.0% |
| 0.10 | 46.9% | 50.2% | 67.1% | 77.1% |
| 0.25 | 30.0% | 33.9% | 35.7% | 41.8% |
| 0.50 | 20.5% | 27.3% | 26.1% | 31.2% |
| 1.00 | 11.9% | 22.0% | 13.0% | 26.4% |

**Read it as: the chart is governed by how much money the leaf lets move, more than by anything
else we could tune.** A leaf model that is off by 0.1 in sigma moves the BB calling range by tens
of points. Caveat on the dial: `stackoff` puts money in uncorrelated with hand strength, which is
the pessimistic direction for the weaker range, so the true curve tightens more slowly than this
table does. sigma = 1 is an extreme, not a plausible upper end.

## 5. The scalar-EV mistake, priced

Bowling's constraint is right, and here is when it bites. "Scalar" = collapse the leaf to expected
chips, then price once with `icm.value`. Mean error over the opener's range, in ICM chips, scalar
minus distribution (positive = overvalues calling):

| sigma | 25bb | 15bb |
|---|---|---|
| 0.00 | +0.008 | +0.013 |
| 0.25 | +0.092 | +0.075 |
| 1.00 | +1.259 | +0.769 |

Under winner-take-all the error is 0.0000 for every hand, as it must be (ICM is then linear).

So: at `sigma = 0` the shape error is small **because the pot is small**, not because scalars are
acceptable — and it is positive for every one of the 169 classes, so it does bias toward calling.
Any credible L1 or L2 must let stacks move, and by `sigma = 0.25` the scalar error is already
0.09 ICM chips, nine times `coach.solve`'s default `target` of 0.01. **Keep the constraint.**

## 6. A side finding in the existing code

`pushfold/oddsmaker.py:238-241` counts showdown ties as coin flips. Under concave ICM a chop is
worth strictly more than a coin flip between two whole pots. Measured at 3-handed 25/25/25 with
50/30/20 prizes: chop minus coin flip is **+1.28 ICM chips per tied 25bb-vs-25bb pot**, +0.10 for
an 8bb-vs-8bb pot, +0.009 for the 4.9bb flop leaf. Two random hands tie on a random board 4.11%
of the time (200k deals, `oddsmaker.strength`). So a deep all-in showdown is **underpriced by
about 0.05 ICM chips**, which is 5x the default solve `target`. It makes showdowns look worse than
they are, so it tightens every ICM push/fold chart slightly. Negligible for the flop leaf,
possibly not for the charts already shipping. Handing this to whoever owns `icm_pricer` accuracy.

## 7. What would change my mind

* The 100% BB-call result could have been an artefact of the opener's range. It is not. Swept
  over opener ranges of the top 15%, 25%, 44% and 70%, the worst of the 169 classes has equity
  0.259, 0.281, 0.293 and 0.302 against it, all above the 0.245 a checkdown call needs, so L0
  gives 100% at every one. It takes an opener range tighter than roughly the top 10% before a
  checkdown leaf declines any hand. (Same command, `sweep(..., share=...)`.) What would still
  change my mind: a leaf that keeps sigma = 0 but makes the BB pay more than 1.2 to see it, i.e. a
  larger open size. At an open to 3bb the BB needs 2/6.5 = 0.31 and the range stops being trivial,
  so **the degeneracy is a property of small opens under a checkdown**, which is precisely the
  action v0 is built around.
* The sigma table is one node with a fixed opener range, not a solve. Once `burch`'s tree exists,
  the same sweep must be run through `coach.solve` and reported as chart deltas.
* Any measurement of real postflop pot growth in these spots would replace the sigma dial with an
  estimate, and the table above with a confidence interval.

---

## 8. What L1 and L2 cost, and what they buy

### L1 "realization" — two scalars per leaf, no new pricing code

A realization factor cannot be applied to a scalar EV, because we do not have one. It has to be
applied inside the distribution. Two dials do it, and both already exist in `leaf.py`:

* **R, the mean.** Tilt the showdown chance: replace the class's all-in equity `p` by `p'` such
  that the chip EV of the leaf equals `R` times the checkdown chip EV. One multiplication on the
  `e2` / `orders()` term. No change to the pricing path.
* **sigma, the spread.** `leaf.stackoff`, already written.

**Work:** about a day. A lookup `R(class group, position, seats, SPR)` and `sigma(position, seats,
SPR)`, wired in at the point where the leaf's equity vector is built. Nothing in `icm_pricer`
changes.

**Data:** this is the whole problem, and this repo has none. There are no postflop hand histories
in it (`tmp/aof/` is all-in-or-fold; `sources/` is documents). Three ways to fill R and sigma:
(i) published third-party realization tables — a number we cannot verify and cannot cite as
evidence; (ii) a fit to the user's own GG hand histories, if postflop hands exist outside the
repo: sigma is directly observable as the average growth of the pot from the flop to the end, and
R as the realized share of the pot by starting class, both of which are counts, not solves;
(iii) a small postflop solve, which is L2's cost anyway.

**What it buys:** it turns the caller's node from degenerate into usable. Given §3, this is not
optional. **What it does not buy:** any claim to correctness. With (i) or a guess, L1 is a knob,
and the spread between two knob settings is not evidence about the world — see §9.

### L2 "learned leaf value" — the DeepStack construction, and one change to it

The construction is that of *DeepStack* (Moravcik, Schmid et al., Science 2017): a network takes
the public state and both ranges and returns counterfactual values per hand, and search uses it as
the leaf of a depth-limited lookahead. Here the boundary is preflop-to-flop instead of
turn-to-river.

**One thing must change.** DeepStack outputs counterfactual *values* because chip EV is linear in
chips, so a value per hand is a sufficient summary. Under ICM it is not — that is the whole point
of §5. Two options:

* Train in ICM-chip space. Then the payout structure and every stack at the table become network
  inputs, and the network is only valid for the payout settings it saw. Cheaper output, worse
  reuse.
* Predict a **small distribution** — for each alive seat, a histogram over chips won, in K bins,
  per hand class — and price it with `icm.value`. Costlier output, but payout-independent: train
  once, reuse for "small tournament", "big tournament" and everything after. I would pick this.

**Work and data:** the targets have to come from a postflop solver, and this repo has none.
DeepStack trained on 10M random turn games and 1M flop games; each of our targets is a flop game,
i.e. three streets. Building a flop solver with an abstraction good enough to generate honest
targets is the largest single item anyone has proposed in this swarm, and it is the thing that
makes L2 buildable, not the network. **Recommendation: not in this swarm.** Say in the product
copy that the leaf is a model; do not promise a learned one on a schedule.

## 9. How to measure leaf-model error without a postflop solver

Bowling's plan: report the L0-vs-L1 chart spread as a sensitivity, and say plainly it is not a
bound. **The caution is right and the spread is the wrong thing to report.** L1 is a knob we set
ourselves; the gap between two settings of our own knob measures our choice of settings, not the
world. Four replacements, in the order I would do them.

**(a) Report leaf error as a function of SPR, and say where it is zero.** At SPR 0 the checkdown
is exact (§1, verified to 1e-12). Error grows with what is behind. In v0 the flop-leaf SPR is
behind/pot: 1.6 at 10bb, 2.6 at 15bb, 4.7 at 25bb, 5.7 at 30bb after a 2.2bb open called. So the
shallow end of the product's grid is the trustworthy end, and it is trustworthy for a reason we
can state. Not a bound; a map of where the model is least wrong.

**(b) Sweep sigma, not L0-vs-L1.** sigma is a *physical* quantity — the fraction of the behind
stack that ends up wagered — so it is measurable from hand histories without any solver, and both
ends of its range are exactly computable. The table in §4 is the honest sensitivity statement:
"the calling range runs from 100% to 12% as the leaf lets 0% to 100% of the behind stack move."
When someone measures sigma, that becomes an interval instead of a range. An L0-vs-L1 spread can
never become that, because nobody can measure "L1".

**(c) Measure the amplification k1, DeepStack Theorem 1 style.** Theorem 1 of *DeepStack* (2017)
says: with leaf values within eps and T CFR iterations, exploitability is at most k1 eps + k2 /
sqrt(T). We cannot know eps, but we can measure k1 in this game: perturb the leaf values by a
controlled eps, solve, then evaluate the resulting strategy **under the unperturbed leaf model**,
and read off the loss. That converts any future estimate of eps into an exploitability statement,
and it is the only item here with the shape of a bound. **Scope limit, stated up front:** Theorem
1 is for two-player zero-sum. With 3+ seats or ICM payouts the game is general-sum and no such
theorem exists, so k1 there is a measured amplification, not a guarantee. I will run this once
`burch`'s tree and `johanson`'s sequential best response exist.

**(d) The one real lower bound: LBR with a checkdown continuation.** Local best response (Lisy and
Bowling, *Equilibrium approximation quality of current no-limit poker bots*, AAAI-17 workshop;
used against DeepStack in the Science paper) plays a best response over a restricted action set and
evaluates continuations by a rollout. Any such player is a legal strategy in the **real** game, so
whatever it wins against our chart is a valid lower bound on the chart's real exploitability —
including the part of the exploitability that comes from the leaf model being wrong. L0 is exactly
the continuation function LBR needs and is already written. Give LBR postflop betting actions that
our model denies itself; if it beats the chart badly, the leaf model is demonstrably inadequate and
we have a number for it. This is the only item that measures anything outside the model game. It
belongs to `lisy`; `leaf.py` is the piece he would need.

**What I would put in the product copy.** Not a spread between two of our own models. Rather:
"this chart is an equilibrium of a model in which a flop is played out with no further betting,
adjusted by a realization factor; the strategy is measurably sensitive to that adjustment — its
calling ranges move by tens of percent across the plausible range — and the model is exact only
where no money is left behind." That is less comfortable and it is what we can support.
