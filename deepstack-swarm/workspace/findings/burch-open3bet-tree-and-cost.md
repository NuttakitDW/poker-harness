# ICM-OPEN3BET-v0: the tree, the solver, and what full-width CFR+ costs

`burch`, 2026-09-27, commit `b75e315`. Code in `deepstack-swarm/workspace/burch/open3bet/`.
Nothing in `pushfold/` was edited.

**Claim.** The v0 tree is 8-20x bigger than bowling's enumeration said, because his script never
reopens the action; measured full-width CFR+ in chip EV with L0 leaves is 0.007 s/iteration
3-handed, 0.20 s 6-handed and 1.95 s 9-handed, in 156 MB of solver arrays. Space is not the binding
resource and decomposition is the wrong tool; time is, and full width is still the right choice
because 6-handed is minutes per spot and 9-handed is 1-3 hours per spot, once. Two correctness
changes are mandatory before any number is trusted: the average strategy now needs own-reach
weighting, and the Auditor is no longer a best response.

**Game.** ICM-OPEN3BET-v0 exactly as `workspace/bowling/open3bet-design.md` §2: preflop-only NLHE,
n = 2..9 equal stacks, sb 0.5 / bb 1, no ante, fee 0, cap 3 to the flop, open to 2.2bb, 3bet to 3x
the facing raise, a raise dropped when it leaves under 1bb behind, no limps. Chip EV. Flop leaves
priced by L0 checkdown (`cashier3.checkdown`). **Not** ICM: the ICM pricer for this tree is not
written yet, so every ICM number below is labelled as scaled, not measured.

## 1. Reproduce

```
.venv/bin/python deepstack-swarm/workspace/burch/open3bet/verify3.py   # cross-check vs pushfold
.venv/bin/python deepstack-swarm/workspace/burch/open3bet/count3.py    # exact tree size
.venv/bin/python deepstack-swarm/workspace/burch/open3bet/bench3.py 3  # measured s/iteration
.venv/bin/python deepstack-swarm/workspace/burch/open3bet/cost3.py     # second, independent estimate
```

## 2. Exact tree size (`count3.py`)

15bb equal stacks. "hits" = (terminal, own-decision) pairs, the unit of pricing work in the flat
plan. "depth" = most decisions one seat makes on one path.

| seats | nodes | sequences | max actions | terminals | allfold | uncontested | allin showdown | flop leaf | depth | hits | push/fold nodes/terminals |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2 | 6 | 16 | 4 | 11 | 1 | 5 | 3 | 2 | 2 | 29 | 2 / 3 |
| 3 | 42 | 102 | 4 | 61 | 1 | 20 | 28 | 12 | 3 | 280 | 6 / 7 |
| 4 | 165 | 383 | 4 | 219 | 1 | 56 | 122 | 40 | 3 | 1 315 | 13 / 14 |
| 6 | 1 193 | 2 642 | 4 | 1 450 | 1 | 261 | 972 | 216 | 3 | 12 086 | 40 / 41 |
| 9 | 9 590 | 20 514 | 4 | 10 925 | 1 | 1 342 | 8 376 | 1 206 | 3 | 124 823 | 128 / 129 |

Three facts worth keeping:

- **The tree is identical for every stack from 8bb to 30bb** (checked at 8/10/15/20/30). The raise
  sizes are absolute, so only the "within 1bb of all-in" clip depends on depth. At 5bb the 3bet is
  clipped away and the tree collapses to 1 334 nodes / 1 463 terminals 9-handed, depth 2.
  Consequence: the plan's *index* arrays can be built once per (seats, cap) and reused across the
  whole stack grid; only the `coef` array depends on stacks. That is 1.24 s of planning per
  9-handed spot saved.
- **bowling's estimate was ~125 nodes / 280 terminals 6-handed and 480 / 1 080 9-handed.** The
  measured tree is 1 193 / 1 450 and 9 590 / 10 925: 10x and 20x the nodes, 5x and 10x the
  terminals. The cause is in `workspace/bowling/count_tree.py:29` — `rec` walks seats 0..n-1 once,
  so a seat that opens and then faces a 3bet never acts again. His heads-up case was wrong for the
  same reason plus the unopened-BB branch; heads-up is 6 nodes / 11 terminals, not 1.
- **3 of 4 terminals 9-handed are all-in showdowns** (8 376), not flop leaves (1 206). The leaf
  model matters less to the cost than to the answer.

## 3. Measured cost (`bench3.py`, chip EV, L0, CFR+)

3 timed iterations after a warm-up, best-of, Darwin 25.0.0, `.venv/bin/python`, numpy.
"arrays" = regret + average + current strategy, (nodes, 169, 4) float64.

| seats | bb | nodes | terminals | plan (s) | **s / iteration** | arrays (MB) | peak RSS (MB) | vs push/fold iteration |
|---|---|---|---|---|---|---|---|---|
| 2 | 15 | 6 | 11 | 0.00 | 0.0004 | 0.1 | 66 | 4.2x |
| 3 | 15 | 42 | 61 | 0.00 | **0.007** | 0.7 | 194 | 8.5x |
| 4 | 15 | 165 | 219 | 0.01 | **0.025** | 2.7 | 219 | 4.5x |
| 6 | 15 | 1 193 | 1 450 | 0.10 | **0.203** | 19.4 | 476 | 30.6x |
| 9 | 15 | 9 590 | 10 925 | 1.24 | **1.95** | 155.6 | 1 189 | 91.0x |

30bb is within 3% of 15bb at every seat count, as the tree is the same.

**A second, independent estimate** (`cost3.py`) times the showdown kernels alone at the same
terminal counts and separately scales a measured `pushfold.coach` iteration by the hit count. The
three numbers at 9-handed are 0.90 s (kernel floor), 1.95 s (measured), 2.97 s (scaled from
push/fold). They bracket the measurement from both sides, which is the only reason I believe it.

**ICM: scaled, not measured.** Measured `pushfold` ICM/chip-EV ratios on the same machine are 2.7x
(3-handed), 2.1x (6-handed) and 1.7x (9-handed). Taking 2-3x gives 0.02 s/it 3-handed,
0.4-0.6 s/it 6-handed and 3.3-5.9 s/it 9-handed. At 2 000 iterations: **40 s 3-handed, 13-20 min
6-handed, 1.8-3.3 h 9-handed, per spot.** Under ICM a leaf *mixture* does not collapse (chip EV is
linear in chips, ICM is not), so an L1/L2 leaf with k components multiplies the flop-leaf share of
that cost by k. At 9-handed flop leaves are 11% of terminals, so k = 4 costs about +33%.

Correction to `open3bet-design.md` §5: "minutes per spot, not hours" holds up to 6-handed. At
9-handed it is hours.

## 4. Full width or sampling?

**Full width, with CFR+, and no decomposition.** The resource that binds is time, not space: the
largest game in the grid holds its regrets in 156 MB and peaks at 1.2 GB of RSS, three orders of
magnitude inside this machine. That rules out the tool I would otherwise own — CFR-D (Burch,
Johanson, Bowling, *Solving Imperfect Information Games Using Decomposition*, AAAI 2014) buys space
by spending time, and we have space and lack time. I am not building it, and continual re-solving
is not needed either while the whole game fits in memory.

Sampling is also the wrong first move. The expensive axis here is not the 169 hand classes — those
are already done in one matrix product, which is what makes full width cheap — it is the public
action tree. Monte Carlo CFR would sample that, and then needs many more iterations to average out
the variance it introduces; full-width CFR+ won on exactly this trade in
`pushfold/` and in Tammelin, Burch, Johanson, Bowling, *Solving Heads-up Limit Texas Hold'em*
(IJCAI 2015). Build a sampler only if the scenario grid grows past what 2-3 h/spot can cover.

**The cheap 3x I would take first, before any sampler.** 85% of a 9-handed iteration is the 3-way
equity tensor (`cost3.py`: 837 ms of an 896 ms kernel floor). The flat per-seat plan inherited from
`pushfold.pricer` contracts that tensor once per (terminal, own-decision): 60 429 times per
iteration, against only 5 538 distinct 3-way terminals — a factor of 10.9 of repeated work. A
public-tree walk that carries each seat's reach vector down and contracts each terminal once per
finish-order layout (3 for ICM, 3 for chip EV) needs ~16 600 contractions, so ~3.6x less tensor
work and ~2.6x less total, putting 9-handed at ~0.75 s/it chip EV and ~1.5-2 s/it ICM. Estimated,
not measured. That rewrite is bounded work and I would do it before anything else.

## 5. Two correctness changes that are not optional

**(a) The average strategy now needs own-reach weights.** `pushfold/coach.py:135` does
`total[p.nodes] += weight * mine`, accumulating behaviour probabilities. That equals sequence-form
averaging only because each seat acts at most once per path, so its own reach to any of its nodes
is exactly 1. `verify3.py` check E: on the 3bb push/fold-equivalent tree every own reach is
1.000000, and on the 6-handed 15bb tree **970 of 1 193 nodes are a seat's second or third
decision**, with own reach 0.111 at uniform. So this is 81% of the tree, not a corner case.
`coach3.iterate` accumulates `weight * pi_i^sigma_t(node) * sigma_t(node)` instead, with own reach
taken from the same sigma that produced the values (seats update one at a time, so the order
matters — cf. Burch, Moravcik, Schmid, *Revisiting CFR+ and Alternating Updates*, JAIR 64, 2019).
If anyone ports `pushfold/coach.py` to a tree where a seat acts twice without this change, the
reported average is not the average of the sequence-form strategies and its exploitability number
means nothing.

**(b) `pushfold/auditor.py` is not a best response here**, as bowling said. Confirmed
structurally: `depth` = 3 in the table above, so the better action at a seat's first decision
depends on what that seat would do at its second and third. `coach3` deliberately has **no stop
rule** until `johanson` supplies a sequential best response. What he needs is already on the tree:
`Node.own_prev` and `Node.own_prev_action` give each seat its own decision DAG, nodes are in DFS
order so a single reverse pass is enough, and `pricer3.SeatPlan.price` returns the counterfactual
values his backward induction needs.

**(c) Game class, stated once.** Heads-up in chip EV with fee 0 is two-player zero-sum: per-seat
EVs sum to 0 to 7e-17 (`verify3.py`), so a low exploitability there is a guaranteed equilibrium
gap. With 3 or more seats, or with ICM payouts, the game is general-sum, CFR has no convergence
guarantee (Zinkevich et al., NIPS 2007 covers 2p zero-sum), and any low number is an empirical
fixed point of this model game only.

## 6. What is in the workspace

| file | what it is |
|---|---|
| `floor3.py` | `build(spot, cap=3, open_to=2.2, mult=3.0) -> Tree`. Nodes with 2-4 actions, global sequence ids, `own_prev`/`own_prev_action`. Terminals tagged `allfold` / `uncontested` / `showdown` / `flop`, carrying `live`, `invested`, `path`, and `behind(spot)` / `pot(spot)`. |
| `cashier3.py` | `settle(spot, invested, live)`: layered settlement from an explicit contribution vector (pushfold's derives it from a jammer set). **The leaf interface for `moravcik`**: `Leaf = Callable[[Spot, Terminal], tuple[tuple[float, Settlement], ...]]`, a weighted mixture; `checkdown` is L0. |
| `pricer3.py` | Chip-EV counterfactual values. Sequences instead of `node*2+action`; product columns for an opponent's multi-decision line (the independent-deal reach of a line is *not* the product of the per-action marginals); own-later reach. |
| `coach3.py` | CFR / CFR+ / DCFR over ragged action sets with own-reach-weighted averaging. No stop rule on purpose. |
| `verify3.py` | The cross-check of §5 and §7. |
| `count3.py`, `cost3.py`, `bench3.py` | Size, two cost estimates, measured cost. |

**Not written:** an ICM pricer for this tree (finish orders over 3-way leaves, as
`pushfold/icm_pricer.py` does), a sequential best response (johanson), and any leaf beyond L0.

## 7. Why I believe the pricer

At 3bb stacks the open is dropped, so the OPEN3BET tree *is* the push/fold tree, and `pushfold/` is
an independently written second implementation of the same game. `verify3.py` checks, at
n = 2/3/4/6/9 and four posting variants (no ante; 0.1 each; 0.5 bb-ante with 0.2 fee; 1.2bb stacks
so seats are all-in by posting):

- node count, terminal count and every terminal's live set are identical;
- `cashier3.settle` and `pushfold.cashier.settle` agree on `fixed` and on every layer;
- counterfactual values and per-seat EVs agree to max |diff| 5e-9 over random strategies. The
  residual is float32 in the 3-way tensor contraction, against Monte Carlo tables whose own error
  is ~1e-2.

This is the check that caught the 10% error in Cepheus's reported average-strategy exploitability
(Burch 2017 thesis, 4.3.1), and it is the only reason any number above is stated without hedging.

## 8. What would change my mind

- **The tree.** If the action abstraction changes — a second open size, limps at 8-12bb (§6.2 of
  the design, a real gap at those depths), a 4bet that is not all-in, or cap 2 instead of 3 — every
  count above changes. Cap 2 and the 5bb collapse both cut 9-handed by ~7x; a second open size
  roughly squares the unopened subtree.
- **The cost.** If the tree-walk pricer of §4 lands, 9-handed drops ~2.6x and the recommendation
  against sampling gets stronger, not weaker. If measured ICM comes in above 4x chip EV rather than
  the 1.7-2.9x `pushfold` shows, 9-handed goes past 4 h/spot and I would revisit sampling.
- **The leaf.** If `moravcik`'s L1/L2 needs more than ~4 mixture components under ICM, the flop-leaf
  share of the cost stops being 11% and the leaf becomes the budget, not the tree.
- **Equity noise.** `pushfold/oddsmaker.py` builds the 3-way tables by Monte Carlo with
  `SAMPLES = 2000`. This tree has 5 538 three-way terminals 9-handed against push/fold's 120, so
  table noise enters in far more places. Nobody has measured how far a chart moves with `SEED`. Any
  exploitability target below that movement is meaningless, and I would not choose a target before
  someone re-solves a 6-handed spot under 2-3 seeds.
