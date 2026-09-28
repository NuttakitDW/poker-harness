# A sequential best response for ICM-OPEN3BET-v0, and how wrong the old shortcut is

`johanson`, 2026-09-27, commit `b75e315`. Code in `deepstack-swarm/workspace/johanson/`.
Write-up assembled and every number re-run by `bowling` on the same commit, because of the
swarm's turn budget; the design, code and analysis are johanson's. Nothing in `pushfold/` edited.

**Claim in one sentence.** `pushfold/auditor.py`'s per-node shortcut — valid on push/fold because
each seat acts at most once — is **not** a best response once a seat can act twice (open then
face a 3bet), and on a heads-up open/3bet toy tree it overstates a near-equilibrium's
exploitability by **1.5x to 3.7x** (chip EV) and **1.5x to 1.7x** (ICM), confirming
`open3bet-design.md` §6b and `burch-open3bet-tree-and-cost.md` §5(b).

## 1. What was built

`seqbr.py`: a generic-tree sequential best response by backward induction (`Node.own_prev`-free —
it walks the whole tree per seat, since the toy/production trees are small enough that this is
cheap; `burch`'s `own_prev` DAG is there for when it isn't). `values()` prices every ending —
all-in showdown or flop-leaf checkdown — with the **same** equity tables (`oddsmaker.e2`, `eq3`,
`pw`, `orders`), matching moravcik's finding that an all-in and an L0 checkdown are priced by
identical code. `audit()` returns, per seat: EV, exact best-response gain, and `shortcut_gain` —
literally what `pushfold/auditor.py`'s formula computes on the same tree, for direct comparison.

`toy_open3bet.py`: a 6-node heads-up open/3bet tree (SB: fold/open 2.2/all-in; facing open, BB:
fold/call/3bet/all-in; facing 3bet, SB: fold/call/all-in; etc.), a reference full-width CFR+
solver over it, and a report comparing the exact gain to the shortcut at every checkpoint.

## 2. Validation: agrees with `pushfold/auditor.py` where the shortcut is exact

```
.venv/bin/python deepstack-swarm/workspace/johanson/check_against_auditor.py
```

On 4 push/fold spots (heads-up, 3-max, an asymmetric 4-max, 6-max with an ante) x 2 payout modes
(chip EV, ICM) x 5 strategies (fold, jam, uniform, 2 random), `seqbr.audit` and
`pushfold.auditor.audit` agree: worst |EV diff| 5.4e-6, worst |gain diff| 8.8e-6, `short-exact`
(shortcut minus exact) 0 everywhere but float noise. This is the check that matters before trusting
anything below — it is the same kind of cross-check that caught a 10% error in Cepheus's reported
average-strategy exploitability (Burch 2017 thesis, §4.3.1, cited in burch's finding).

## 3. The result: the shortcut is not a best response once a seat acts twice

```
.venv/bin/python deepstack-swarm/workspace/johanson/toy_open3bet.py
```

Heads-up, 12bb each, sb 0.5/bb 1, no ante, no fee, L0 checkdown leaf for hands that see a flop.
**Not ICM push/fold — this tree has a real open and a real 3bet, and a flop-leaf ending.**

Anchors (fixed strategies, no solving) already show the gap, and it only widens near equilibrium:

| strategy | chipEV: exact max gain | shortcut | ratio | ICM: exact max gain | shortcut | ratio |
|---|---|---|---|---|---|---|
| uniform | 1.0986 | 1.6449 | 1.50x | 0.6408 | 0.9412 | 1.47x |
| random (3 draws) | 1.08-1.17 | 1.64-1.71 | 1.45-1.53x | 0.58-0.65 | 0.84-0.99 | 1.44-1.51x |
| always-fold / always-aggressive | equal | equal | 1.00x | equal | equal | 1.00x |

(The two degenerate anchors agree because a strategy that never mixes has no second decision to
get wrong — the shortcut is exact exactly where a seat's first action already determines whether
it gets a second one.)

CFR+ from uniform, 400 iterations, full-width reference solver (own-reach-weighted average, per
burch's correctness note):

| | chip EV (bb/hand) | ICM chips/hand (3-paid, 2 seats' worth of field elsewhere) |
|---|---|---|
| exact max gain | 0.00028 | 0.00315 |
| shortcut's report | 0.00105 | 0.00471 |
| ratio | **3.69x** | **1.49x** |
| as % of initial 1.5bb pot | 0.019% | 0.210% |
| as % of average final pot | 0.003% | 0.050% |

**Reading this against Cepheus's standard** (Bowling, Burch, Johanson, Tammelin, *Science* 2015):
the exact number, not the shortcut, is what should ever be compared to a "how many mbb/g would a
lifetime of play detect" threshold. Here the shortcut would have called this strategy roughly 1.5x
to 3.7x more exploitable than it is — enough to wrongly fail an "essentially solved" bar set from
the exact number, or wrongly pass one set loosely enough to tolerate the shortcut's inflation.

## 4. Why the ratio moves the way it does

The ratio is largest in chip EV far from equilibrium is *not* the pattern — it's largest **near**
equilibrium in chip EV (1.5x at 50 iters, 3.7x at 400) and roughly flat in ICM (1.5-1.7x throughout).
That is because the shortcut sums each seat's node-local regrets independently, double-counting a
seat's second decision on top of its first whenever both are away from best-response; as CFR drives
regret at the *first* decision toward zero, the *second* decision's leftover regret becomes a
larger share of a shrinking total, so the ratio grows. This is a property of the shortcut formula,
not of this particular tree, and will recur in any tree where a seat acts more than once — i.e.
`burch`'s full v0 tree at every seat count above 2.

## 5. What this changes

- **`coach3`'s missing stop rule is now unblocked.** `seqbr.audit` is ready to be `burch`'s stop
  condition; it needs `Node.own_prev` wiring for speed on the full tree (this toy uses full
  backward induction, fine at 6 nodes, not at burch's 9 590).
- **Any exploitability number already floating around for an open/3bet-shaped tree that used
  `pushfold/auditor.py` directly is wrong** and should be re-checked against `seqbr`.
- Not yet measured: the ratio on burch's actual 9 590-node 9-handed tree, or under DCFR. This toy
  is heads-up and 6 nodes; the direction (shortcut over-reports) should hold generally because it
  follows from double-counting, but the magnitude here (1.5-3.7x) is this tree's number, not a
  universal constant.

## 6. What would change my mind

- If a production run showed the ratio shrinking rather than growing near equilibrium on the full
  tree, the double-counting explanation in §4 would be wrong and needs redoing.
- The ICM ratio here used one field composition (`field=(12.0, 12.0)`); `bard`'s finding on
  scenario-grid sensitivity suggests the field/stack configuration matters a lot, so this ratio
  should be swept before quoting a single number in product copy.
- This is chip EV / ICM on a **model game already including the L0 leaf**; moravcik's finding says
  L0 is degenerate for the BB's call decision at small opens, so the *strategy* being audited here
  is not one anyone should ship — only the shortcut-vs-exact comparison in §3-4 is the point.
