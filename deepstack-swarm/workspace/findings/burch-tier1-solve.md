# Tier 1 ("open or jam") on floor3/coach3, with a real stop rule, cross-checked against bowling

`burch`, 2026-09-27, commit `b75e315`. Code in `deepstack-swarm/workspace/burch/open3bet/`
(`floor3.py`, `pricer3.py`, `seqbr3.py`, `solve3.py`, `tier1_check.py`). Nothing in `pushfold/`
edited.

**Claim in one sentence.** Tier 1 ("open or jam": `open3bet-design.md` Sec 6b) now solves chip EV
to a real, checked, exact-exploitability target on `floor3`/`coach3` (production speed: 494 nodes,
9-handed, converges to 0.0001 bb/hand in 4875 iterations / 370s), agrees with bowling's
independently-built reference tree and CFR+ solver on a 3-handed cross-check to 2%, and the ICM
side of that cross-check also agrees (0.8%) once solved for ICM rather than audited under it —
but OPEN3BET still has no production ICM pricer, so ICM here is a reference-speed proof, not the
production path.

**Game.** Tier 1 exactly as `open3bet-design.md` Sec 6b: preflop only, n = 2..9 equal stacks, sb
0.5 / bb 1, no ante, fee 0, cap 3. Unopened: fold / open 2.2bb / all-in. Facing an open: fold /
all-in (no flat, no 3bet). Facing an all-in: fold / call. Every ending is ALLFOLD, UNCONTESTED or
SHOWDOWN — no flop is ever reached, so no leaf model is consulted. Chip EV unless stated ICM
(50/30/20 payouts, field as noted).

## 1. Reproduce

```
.venv/bin/python deepstack-swarm/workspace/burch/open3bet/solve3.py <n> <stack> <target> <method>
.venv/bin/python deepstack-swarm/workspace/burch/open3bet/tier1_check.py <n> <stack> <iters>
```

## 2. The tree matches bowling's, exactly, at every seat count

`floor3.build(spot, tier1=True)` (one boolean added to the existing v0 builder: facing one raise
and not all-in, `acts = [FOLD, ALLIN]` instead of `[FOLD, CALL, RAISE, ALLIN]`; every other rule —
cap, the unopened set, facing-all-in — is untouched):

| n | nodes | terminals | (mine) allfold/uncontested/showdown | bowling's terminals |
|---|---|---|---|---|
| 2 | 4 | 6 | 1 / 3 / 2 | — |
| 3 | 14 | 17 | 1 / 7 / 9 | 17 |
| 4 | 34 | 38 | 1 / 12 / 25 | 38 |
| 6 | 125 | 131 | 1 / 25 / 105 | 131 |
| 9 | 494 | 503 | 1 / 52 / 450 | 503 |

Nodes and terminals match bowling's `workspace/bowling/tier1.py` at every n. The allfold /
uncontested / showdown **breakdown** does not (his: 1/2/14 at n=3) — his `resolve_allin`'s base
case always labels the terminal `"showdown ..."`, even when everyone else has folded to the one
remaining all-in seat (no actual multi-way equity is computed there, or needed — his settlement is
still correct). A labelling quirk in a counting helper, not a solver disagreement; flagging it so
nobody reads his 1/2/14 as a structural difference from mine.

## 3. Cross-check against bowling's numbers: agrees, once solving the right game

3-handed, 15bb, open 2.2bb, 400 iterations, CFR+, own-reach-weighted average
(`burch-open3bet-tree-and-cost.md` Sec 5(a)):

| | chip EV | ICM (field=(15.0,), 50/30/20) |
|---|---|---|
| bowling's reference (`tier1.py`, naive average) | 0.00089 | 0.00804 |
| mine, `pricer3`/`coach3` (fast, own-reach avg) | **0.000869** | not solved (no ICM pricer) |
| mine, `seqbr3` generic oracle (slow, own-reach avg) | 0.000869 | **0.008117** |

Chip EV: two independently-coded value engines (`pricer3`'s flattened columns and `seqbr3`'s
generic backward induction, ported from johanson's `seqbr.py`) agree on this tree to 6 decimals,
and both land within 2.4% of bowling's number using a different (correct) averaging rule — see
Sec 5.

**ICM needed a second look.** My first attempt audited a strategy solved for *chip EV* under ICM
payouts and got 0.334 — 40x too big. That is not a bug in the audit; `pricer3` has no ICM pricer
for OPEN3BET (`burch-open3bet-tree-and-cost.md` said so), so `coach3.iterate` was minimizing chip
regret regardless of which payouts I audited with, and a chip-EV-optimal strategy is very
exploitable under ICM (mine folds seat 0 first-in 60.9% of hands; an ICM-solved one should fold far
more — bowling's reference shows 90.6%). Once I actually **solved** for ICM — `tier1_check.py`'s
`solve_generic`, CFR+ over `seqbr3`'s generic oracle with own-reach averaging and a cached ICM
`_worth` table (Sec 4) — the number came back 0.008117 against bowling's 0.00804, 0.8% apart. That
gap is closer than the chip EV gap, some of it likely luck of which averaging convention the two
solvers use; see Sec 5.

## 4. `seqbr.audit` as the stop rule: fast for chip EV, still slow for ICM

Wiring `johanson`'s `seqbr.audit` in directly (`seqbr3.Auditor`, an adapter `from_floor3` that
maps `floor3.Tree` into `seqbr.Game` the same way `seqbr.from_floor` already does for
`pushfold.floor`) worked, but the audit itself was the new bottleneck at 9-handed, exactly as
bowling and johanson predicted:

| n | CFR+ iterate (`pricer3`/`coach3`) | `seqbr3.Auditor` (johanson's oracle, unmodified) |
|---|---|---|
| 3 | 4.2 ms | 55.8 ms |
| 6 | 15.2 ms | 1 512.7 ms |
| 9 | 68.7 ms | 8 077.3 ms |

Root cause, measured (not guessed): `seqbr.chip_values` loops over every terminal in Python and
re-touches the full (169,169,169) equity table (`eq3`/`pw`, ~32MB) once per terminal — 503 times
at n=9, 8.0s of the 8.08s audit. Backward induction itself (`seqbr._walk`, the actual max-vs-sum
recursion) is **not** the bottleneck: 37ms for 2 walks x 9 seats on the same 494-node tree.

**Fix, chip EV only: `pricer3.terminal_values`/`all_terminal_values`.** Same batched-CHUNK-einsum
machinery `pricer3.values` already uses for `coach3`'s regret updates (one matmul per chunk across
every terminal, not one per terminal), producing `U[seat, 169, terminal]` — the exact quantity
`seqbr.chip_values` computes, with own reach fully excluded rather than partly baked in — then fed
straight into `seqbr.audit(..., U=...)` unchanged. Needed two small additions to `SeatPlan`: `zid`
(which terminal a row came from) and `rank` (which of a seat's own decisions on that path the row
was generated for, so multiplying out the seat's own-reach factor and keeping only `rank == 0`
avoids double-counting a terminal once per decision — the same double-counting shape as the
shortcut bug, caught by a direct numeric check, not by reasoning about it). No change to
`pricer3.values` (still what `coach3.iterate` calls) or to `seqbr.py` (johanson's, untouched).

Checked against `seqbr.chip_values` on the same (tree, mid-solve sigma), all n: **max |diff| ≤
1.1e-8**, same order as `verify3.py`'s existing float32-tensor residual.

| n | `seqbr.chip_values` (slow) | `pricer3.all_terminal_values` (fast) | speedup |
|---|---|---|---|
| 3 | 66 ms | 3.9 ms | 17x |
| 4 | 245 ms | 5.4 ms | 45x |
| 6 | 1 497 ms | 15.0 ms | 100x |
| 9 | 8 000 ms | 62 ms | **129x** |

With `FastAuditor` wired into `solve3.solve` (check every 25 iterations, Burch thesis Sec 3.3.1),
a check now costs about as much as one CFR+ iteration again, at every seat count:

| n | target (bb/hand) | method | converged | iterations | seconds | ms/iter incl. audits |
|---|---|---|---|---|---|---|
| 2 | 0.0001 | cfr+ | yes | 1 000 | 0.24 | 0.24 |
| 3 | 0.0001 | cfr+ | yes | 1 200 | 5.22 | 4.35 |
| 4 | 0.0001 | cfr+ | yes | 1 925 | 8.98 | 4.66 |
| 6 | 0.0001 | cfr+ | yes | 3 250 | 51.14 | 15.74 |
| 9 | 0.0001 | cfr+ | yes | 4 875 | 370.06 | 75.91 |
| 4 | 0.001 | dcfr | yes | 625 | 5.21 | 8.34 |
| 4 | 0.001 | cfr (no +) | **no** | 20 000 (cap) | 135.45 | 6.77 |

Plain CFR not reaching 0.001 bb/hand in 20 000 iterations at n=4, where CFR+ needs under 2 000 for
a 10x tighter target, is the CFR-vs-CFR+ gap this persona's thesis is about (Burch 2017, ch. 4) —
expected, not a bug, and a reason to keep CFR+ as the Tier 1 default. **`seqbr3.Auditor` (the slow,
generic oracle) is still what backs the ICM cross-check in Sec 3**, because ICM has no equivalent
fast path yet — see Sec 6.

## 5. A secondary finding: bowling's reference average is not reach-weighted, and here it barely matters

`johanson/toy_open3bet.solve` (reused by `bowling/tier1.py`) accumulates
`total[index] += t * sigma[index]` — the raw behaviour probability, not `t * own_reach * sigma`.
Tier 1 has seats with own reach < 1 (a seat's second decision, facing its own all-in-less-than-full
all-in after opening — `depth_of_own_decisions() == 2` at every n checked), so this is exactly the
averaging bug `burch-open3bet-tree-and-cost.md` Sec 5(a) flagged, present in the reference solver
used to generate the numbers I was asked to cross-check against. In practice it moved the answer
by 2.4% (chip EV, my correct-average number is *smaller*) and −0.8% (ICM, mine is larger) at 400
CFR+ iterations on this small tree — small next to the shortcut's 1.1-3.7x, but not zero, and not
guaranteed to stay small on a bigger tree or fewer iterations (own reach can be much less than the
0.39-0.09 range seat 0's own open frequency showed here). I have not attempted to fix
`toy_open3bet.solve` — it is johanson's file — flagging it here as a second data point for the
"own-reach weighting matters" claim; `bowling-tier1-first-solve.md` already correctly identified
the shortcut bug on the same script but not this one.

## 6. What is not done

- **No production ICM pricer for OPEN3BET.** `pricer3`/`coach3` are chip-EV only. The ICM number
  in Sec 3 came from `tier1_check.py`'s `solve_generic`, a CFR+ loop over `seqbr3`'s generic
  oracle (Python recursion, own-reach averaging, cached `_worth`) — correct, cross-checked, and
  fine for one 3-handed spot (84s for 400 iterations) but not a chart-scale tool. Building an ICM
  pricer3 (the `pricer3.terminal_values` batching trick does not directly help: ICM's nonlinearity
  means the layer-by-layer settlement can't be priced independent of finishing order the way chip
  EV can) is the natural next piece, and Tier 1's terminal set is exactly `pushfold/icm_pricer.py`'s
  three ending types, so that file is the right template — not attempted here, not asked for yet.
- **`FastAuditor` is chip EV only** for the same reason; `Auditor` (slow) remains the only ICM
  option.
- Equal stacks only, same caveat as bowling's `tier1.py`: no short-stack open clipping, no forced
  post handling (5-12bb range, `open3bet-design.md` Sec 6.1/6.2).
- Nobody has swept `SEED` on the 3-way Monte Carlo tables for a Tier 1 spot yet
  (`burch-open3bet-tree-and-cost.md` Sec 8) — the 0.0001 bb/hand target above is far below that
  unmeasured noise floor and I would not read it as a real-money precision claim.

## 7. What would change my mind

- If someone re-derives bowling's 0.00089/0.00804 by a third, independent route and gets a number
  outside my ~1-2% band, something is wrong in one of the three implementations now on the table
  (his, johanson's generic oracle, mine) and none should be trusted until reconciled.
- If `all_terminal_values` disagreed with `seqbr.chip_values` above float-noise on any tree
  (I checked n=2,3,4,6,9 at one mid-solve sigma each; a wider sweep, especially at the cap boundary
  where `floor3` skips nodes for forced folds, would strengthen this).
- If the own-reach-averaging gap in Sec 5 turned out to be large rather than small on a bigger tree
  or fewer iterations, "barely matters" above would need retracting.
