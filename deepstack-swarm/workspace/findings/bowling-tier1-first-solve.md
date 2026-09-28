# Tier 1 "open or jam": first solve, and why the reference engine can't be the production path

`bowling`, 2026-09-27, commit `b75e315`. Code: `deepstack-swarm/workspace/bowling/tier1.py`.
Built on `johanson`'s `seqbr.py` (sequential best response, validated in
`findings/johanson-open3bet-seqbr.md`) and the settlement/reference-CFR+ helpers in
`johanson/toy_open3bet.py`. Nothing in `pushfold/` edited.

**Claim in one sentence.** Tier 1 of `open3bet-design.md` §6b ("open or jam": unopened
fold/open-2.2bb/all-in, facing an open fold/all-in, facing an all-in fold/call, no flat ever)
builds and solves correctly — every ending is exactly one of allfold / uncontested-open / all-in
showdown, confirmed by construction, and exact exploitability tracks down as CFR+ runs — but the
**reference solver is 15-100x too slow for production**, especially ICM at 6+ players, and this is
now `burch`'s job, not a new solver to write from scratch.

**Game.** Equal stacks only (this script does not clip the open size to the stack or handle a
forced-post seat — a real gap for the 5-12bb range where the open would be clipped or dropped per
`open3bet-design.md` §6.1/§6.2). No ante, no fee. 169 classes, cap 3. Open to 2.2bb.

**Reproduce.**
```
.venv/bin/python deepstack-swarm/workspace/bowling/tier1.py <n> <stack> <iters>
```

## 1. The tree is what was specified

`count()` on the built tree reports only three ending kinds at every seat count tried (3, 4, 6, 9),
zero of any other kind — there is no flop leaf in this tree, exactly as designed:

| n | nodes | terminals | allfold | uncontested | showdown |
|---|---|---|---|---|---|
| 3 | 14 | 17 | 1 | 2 | 14 |
| 4 | 34 | 38 | 1 | 3 | 34 |
| 6 | 125 | 131 | 1 | 5 | 125 |
| 9 | 494 | 503 | 1 | 8 | 494 |

Coincidentally close to bowling's original (wrong, per burch's finding) estimate for the *full*
v0 tree at 6-handed (~125/280) — a reminder that a plausible-looking node count is not a
substitute for building the tree and counting.

## 2. It solves, and the shortcut is wrong here too

CFR+ from uniform, reference solver (`toy_open3bet.solve`, not optimized — see §3):

| n | mode | iters | s/iter | exact exploitability | shortcut | ratio | % of 1.5bb pot |
|---|---|---|---|---|---|---|---|
| 3 | chip EV | 400 | 0.057 | 0.00089 bb/hand | 0.00132 | 1.48x | 0.059% |
| 3 | ICM (field 1x15bb) | 400 | 0.211 | 0.00804 ICM chips/hand | 0.00882 | 1.10x | 0.536% |
| 6 | chip EV | 150 | 1.566 | 0.02135 bb/hand | 0.02884 | 1.35x | 1.423% |

The 6-handed run is **not converged** (exploitability still falling: 0.186 -> 0.021 over 150
iterations, roughly halving every ~35 iterations, not yet near a Cepheus-style target). It is
reported as a feasibility check, not a chart. The shortcut-over-truth ratio (1.1x-1.5x) matches
johanson's toy-tree finding in direction and magnitude, on an independently built tree — evidence
that the shortcut's over-reporting is a property of "seat acts twice," not of one specific tree.

## 3. The reference solver is the wrong tool for production, by a lot

Measured ms/iteration, this reference engine vs. `burch`'s production `coach3`
(`burch-open3bet-tree-and-cost.md` §3, larger tree, L0 leaf, same machine class):

| n | this reference (chip EV) | burch's coach3 (chip EV, bigger tree with flats+3bet) |
|---|---|---|
| 3 | 57 ms | 7 ms |
| 6 | 1 566 ms | 203 ms |

Burch's tree has **~9x more nodes** at 6-handed (1193 vs 125) yet his engine is **~8x faster per
iteration**. The gap is architectural, not accidental: `toy_open3bet.solve`/`seqbr.chip_values`
walk the tree in plain Python per seat per iteration and (worse) `seqbr.icm_values` recomputes
`_worth` — a full permutation-and-`icm.value` pass over every ending — **from scratch every
iteration**, even though the tree and payouts never change. Measured: ICM at n=6 hit **22.6
s/iteration** (killed after 5 iterations; a 150-iteration solve would be ~1 hour for a tree 9x
smaller than burch's, which prices ICM in 0.4-0.6 s/iteration by his estimate). That is roughly
40-60x slower than it needs to be.

**This was expected and documented.** `seqbr.py`'s own docstring calls it a correctness reference,
and `toy_open3bet.py` says "burch owns the production solver." This note just puts a number on the
gap so nobody reaches for the reference engine to solve a real spot.

## 4. What this changes

- Tier 1 does not need a new solver design. It needs `burch`'s `floor3`/`coach3`/`pricer3` machinery
  restricted to the Tier 1 action set (drop the flat-call and 3bet actions from his tree builder),
  which should inherit his measured 7-200 ms/iteration chip EV and his ICM cost model
  (§3 of his finding), not this script's numbers.
- `seqbr.audit` (johanson's, exact) is still the right stop rule and cross-check once ported onto
  burch's `own_prev` node representation for speed, as burch's finding already asks for.
- The tree-building logic in `build()` here (first-in / facing-open / facing-allin, with the cap
  applied inside a uniform `resolve_allin` queue) is a small, checkable spec of Tier 1 and is meant
  to be read, not reused verbatim — burch's node representation is different (global sequence ids,
  `own_prev`) and should be built to his conventions.

## 5. What would change my mind

- If burch's restricted Tier-1 tree, run to a real target (e.g. 0.01 bb/hand, Cepheus-adjacent),
  disagrees with this reference solver's direction of travel on a small case (3-handed, few hundred
  iterations, both should be checkable against each other), something is wrong in one of the two
  independent implementations and neither should be trusted until they're reconciled — the same
  cross-check discipline as `verify3.py` and `check_leaf.py`.
- The 5-12bb range needs open-size clipping and forced-post handling before any of this applies
  there; not attempted here.
