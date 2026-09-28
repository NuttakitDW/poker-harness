# What Tier 1 actually computes: the raising action is chosen by depth and position, and the deep game is jam-or-fold

`bowling` (PI), 2026-09-27. Companion to `bowling-tier1-flop-gap.md`. All numbers run on commit
`b75e315`, `.venv/bin/python`, 6 seats, equal stacks, sb 0.5 / bb 1, no ante, `fee = 0`, cap 3.
Nothing in `pushfold/` edited.

**Claim in one sentence.** In Tier 1 ("open or jam", `floor3.build(..., tier1=True)`) chip EV, the
raise a seat actually uses depends on depth *and* position -- the earliest seat jams below ~15bb and
opens above it, never mixing (open share exactly 0.000 at 8 and 12bb, jam share exactly 0.000 at 20
and 30bb), while later seats open at 8bb as well (mean open share 0.29 / 0.33 / 0.42 for seats 2 / 3
/ 4) -- and since Tier 1 has no flat and no 3bet, the only answer to an open is jam-or-fold, which
the seats behind use heavily at 8bb (per-seat mean 0.55-0.70) and much less at 30bb (0.09-0.32).

**Correction to an earlier version of this file.** I first reported "the BB re-jams 50-56%" from a
single node and "at 8-12bb the open is never used" from seat 0 alone. Both were wrong: the first
node of a seat is not that seat's range, and seat 0 is not the table. The aggregates below replace
them.

## The depth switch, seat 0 (first to act), unopened, chip EV

Mean share over the 169 classes; target 0.001 bb/hand:

| stack (bb) | fold | open 2.2bb | all-in |
|---|---|---|---|
| 8 | 0.760 | **0.000** | 0.240 |
| 12 | 0.822 | **0.000** | 0.178 |
| 20 | 0.783 | 0.217 | **0.000** |
| 30 | 0.728 | 0.272 | **0.000** |

The solver never mixes the two raise sizes at one depth for this seat: below ~15bb the jam carries
the range, above it the open does. n=6 converges cheaply (350 iters / 12 s at 8bb, 525 / 17 s at
30bb), so this is not a compute artifact.

## The open is used at 8bb, but only from later position

Mean `open 2.2` share at each seat's unopened node:

| stack | s0 | s1 | s2 | s3 | s4 | s5 |
|---|---|---|---|---|---|---|
| 8bb | 0.000 | 0.000 | 0.290 | 0.332 | 0.423 | (BB, no unopened node) |
| 12bb | 0.000 | 0.230 | 0.287 | 0.365 | 0.672 | -- |
| 20bb | 0.217 | 0.252 | 0.306 | 0.401 | 0.795 | -- |
| 30bb | 0.272 | 0.308 | 0.378 | 0.494 | 0.967 | -- |

So the chart is **not** the push/fold chart at 8bb -- the open is live from seat 2 onward even there,
which is the one thing push/fold cannot express. It is also not a chart with a settled raise size:
one fixed 2.2bb open has to serve both a min-raise-fold at 8bb and a 30bb open.

## The answer to an open is jam-or-fold, and the jam is wide at 8bb

P(jam | facing exactly one non-all-in raise), per seat: `n` = number of such nodes, mean over them
and over the 169 classes, with the min-max spread across nodes.

| spot | s1 | s2 | s3 | s4 | s5 (BB) |
|---|---|---|---|---|---|
| 8bb chip | 0.698 | 0.704 | 0.552 [0.15,0.75] | 0.575 [0.20,0.93] | 0.617 [0.26,1.00] |
| 30bb chip | 0.094 | 0.122 | 0.147 | 0.205 | 0.324 [0.20,0.56] |
| 8bb ICM bubble | 0.077 | 0.092 | 0.107 | 0.166 | 0.354 [0.22,0.55] |
| 30bb ICM bubble | 0.114 | 0.129 | 0.147 | 0.194 | 0.335 [0.20,0.61] |

(`small` structure: 300 runners, 45 paid, 46 players left, everyone 30bb or 8bb via the crowd.)

Two readings:

- **Depth dominates chip EV.** At 8bb a seat facing an open jams 55-70% of its classes; at 30bb,
  9-32%. At 8bb jam-or-fold over an open is nearly the whole game; at 30bb it is not.
- **ICM bites at 8bb and much less at 30bb, in this structure.** At the bubble the 8bb re-jam roughly
  halves (BB 0.617 -> 0.354, s1 0.698 -> 0.077), while the 30bb re-jam barely moves (BB 0.324 ->
  0.335). The chart as a whole also moves several times further between chip EV and ICM at 8bb than
  at 30bb. **Open question, not a finding:** I have not shown whether that is a real property of the
  payout structure (a bubble factor that flattens with depth) or an artifact of the crowd model in
  `scenarios.payouts`. It is the kind of thing `bard-scenario-grid.md` says needs its own axis, and I
  am flagging it rather than claiming it.

## Why this matters for the product claim

"0.0006 ICM chips/hand" is an exact, verified statement about *this* game -- the fast and slow
auditors agree to 5.7e-11 on the converged strategy
(`cells/small-bubble-n6-15bb-left46.json`). It is not a statement about poker, and the gap is largest
exactly where the chart is most interesting: above ~15bb, where the game becomes
"open-or-fold, answered by jam-or-fold". A real 30bb opponent flattens or 3bets an open; in Tier 1
those actions do not exist, and the leaf model that would price a flat is the one
`leaf-model-L0.md` measured as degenerate. Below ~15bb the jam-or-fold structure is much closer to
the real short-stack game and the number carries further.

## What would change my mind

An ICM structure in which 30bb re-jam frequencies move as much as the 8bb ones (would make the
depth-insensitivity above a payout-model artifact); or a Tier 1 chart that keeps a wide re-jam once
the flat call is priced by any calibrated leaf (would make the wide jam a leaf artifact rather than
an action-set one).

## Reproduction

`/tmp/tier1_table.py` (seat-0 depth table), `/tmp/allseats.py` (open share per seat),
`/tmp/jamagg.py` (re-jam aggregates), `/tmp/chipvsicm.py` (chip vs ICM). All need repo root and
`deepstack-swarm/workspace/burch/open3bet` on `sys.path`; all were run from the repo root.
