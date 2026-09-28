# Tier 1 FLOP terminals: immaterial at ICM, real in chip EV, and invisible to exploitability

`burch`, 2026-09-28. Answers `bowling-tier1-flop-gap.md`, in that file's order. All numbers run
with `.venv/bin/python` from the repo root; nothing in `pushfold/` edited.

**Claim in one sentence.** Under the equilibrium of `floor3.build(..., tier1=True)`, FLOP terminals
— which are priced by the L0 checkdown leaf — are reached on 0.8%–33% of hands in chip EV but only
0.0003%–0.024% under ICM bubble payouts, and the choice of leaf moves the chart's *actions* far
more than it moves *EV*; the as-is chart costs at most 3e-6 ICM chips/hand inside a leaf-free game
(0.5% of the 0.0006 target) but 0.0006–0.196 bb/hand in chip EV, so the shipped equal-stack ICM grid
is unaffected and the guarantee needs restating as **"leaf-free at equal stacks"**, not replaced.

## Game

NLHE, preflop only, Tier 1 action set (`floor3.build(..., tier1=True)`), cap 3, `fee = 0`,
sb 0.5 / bb 1, no ante, 169 hand classes. Chip EV, or ICM with `scenarios.prizes("small")`
(300 runners, 45 paid) at the bubble, 46 left, off-table crowd at the table mean. `method=cfr+`,
`check_every=25`, target 0.001 bb/hand chip EV / 0.0006 ICM chips/hand. Every arm below converged
to its target. Unit: bb/hand (chip EV) or ICM chips/hand (ICM), max over seats.

Spots: `3max (5,15,30)`, `6max (4,8,15,20,30,15)`, `ladder (5,10,15,20,25,30)`,
`2short (2,15,15,15,15,15)`.

## 1. Reach of the FLOP terminals under the equilibrium

Total probability that the hand ends in a FLOP terminal, `reach.terminal_reach` (sums to 1 over all
terminals; independently verified against `johanson/seqbr.reach_probability` to **1e-17** on all 15
arms — the Cepheus reporting-bug discipline):

| spot | chip EV | ICM bubble |
|---|---|---|
| 3max (5,15,30) | **0.81%** | 0.0003% |
| 6max (4,8,15,20,30,15) | **5.58%** | 0.024% |
| ladder (5..30) | **2.56%** | 0.011% |
| 2short (2,15,15,15,15,15) | **33.4%** | -- |

The direct answer to ask 1: **at 3max (5,15,30) chip EV, 0.81%; at the 6-max spot, 5.58%.** They
are not off-path. ICM reduces them by roughly 200x, because the bubble prices the deep call out of
the equilibrium before the cap ever binds.

## 2. Chart sensitivity

**Exploitability does not detect this.** Every arm below solves its own game to the target
(converged, gain 0.00086–0.00099 chip EV, 0.00059–0.00060 ICM). There is no exploitability gap to
report, in either direction, because each variant is internally consistent. Only cross-evaluation
finds it — the same reason the Cepheus exploitability report needed a second codebase.

**Actions move; EV mostly does not.** Short seat's first-in node, P(jam) and the PRIOR-weighted
share of classes with jam as argmax:

| spot | mode | as-is | leaf-free cap | stack-off pricing |
|---|---|---|---|---|
| 3max | chip | 0.119 / 0.085 | 0.367 / 0.376 | 0.202 / 0.127 |
| 6max | chip | 0.250 / 0.249 | 0.259 / 0.261 | 0.305 / 0.306 |
| ladder | chip | 0.225 / 0.228 | 0.205 / 0.211 | 0.260 / 0.264 |
| 2short | chip | 0.373 / 0.373 | 0.822 / 0.822 | 0.418 / 0.418 |
| 3max | ICM | 0.0002 / 0.000 | 0.134 / 0.136 | 0.050 / 0.041 |

As-is jams least of the three in every spot, i.e. **the sign matches the under-jamming direction**
`bowling-tier1-flop-gap.md` inferred.

**The number that decides it** is a profile's EV inside a fixed game (`seqbr.audit(...).ev`),
cross-evaluating each arm's chart in each other arm's game. Two arms are exactly clean (0% of
destination nodes unmatched, so no filler strategy is used):

- **Pricing only** — `asis <-> stackoff`, identical trees and action sets, 100% matched:
  | spot | as-is in stack-off | stack-off in as-is |
  |---|---|---|
  | 3max chip | +0.0006 | +0.0095 |
  | 6max chip | +0.0466 | +0.0132 |
  | ladder chip | +0.0086 | +0.0121 |
  | 2short chip | +0.1959 | +0.0377 |
  | 3max ICM | +0.0000002 | +0.00019 |
  | 6max ICM | +0.00021 | +0.00007 |

  Both ICM rows are under the 0.0006 target, so the L0-vs-stack-off pricing choice is immaterial
  at the bubble at either table size -- which is what a 1e-4-scale reach predicts, and is the
  cross-check that the effect is about the FLOP terminals and not about the tree shapes.
- **Action deletion** — `asis -> leafree` (0% unmatched at 3max and 2short, so clean there;
  8.0% / 11.1% at 6max / ladder, so those two are *upper bounds*):
  3max chip **+0.0079**, 2short chip **+0.0706**, 6max chip +0.0281, ladder chip +0.0180,
  3max ICM **+0.000003**, 6max ICM +0.00396 (8% uniform, upper bound).
  The 6max ICM row is the one to read carefully: it is 6.6x the target, but it is the *deletion*
  arm -- deleting the deep-call action changes the game, and 8% of the destination nodes then carry
  a uniform filler strategy. It is not evidence that the FLOP terminals cost 0.004; the clean
  pricing row above is the one about the leaf, and it is 0.0002.

So: **chip EV, 0.0006–0.196 bb/hand (0.6x–196x the 0.001 lifetime bar); ICM, 7e-5 to 2e-4
(0.1x–0.4x the 0.0006 bar).** The gap is real in chip EV and immaterial at ICM -- and note the
3max ICM case where P(jam) moves 0.0002 -> 0.134 while EV moves 3e-6: a near-indifferent decision,
so action movement alone is not evidence of harm. Report both currencies or neither.

## 3. Recommendation

1. **The shipped grid is unaffected — ship it, restate the claim.** Every cell is equal-stack, and
   at equal stacks every caller of a jam is all-in itself, so `close()` can never tag FLOP and
   `counts.flop` is 0. State the guarantee as "no leaf model is consulted **at equal stacks**".
2. **Do not adopt the strengthened cap as the fix.** `behind_cap=1` is an *abstraction* change, not
   a model fix: it deletes a legal action (a deep seat calling a short jam) and swaps one
   unmodelled leaf for a different unmodelled assumption. It is the most distortive of the three
   exactly-computable variants (P(jam) 0.0002 -> 0.134 at 3max ICM; 0.0037–0.176 bb/hand to play in
   the as-is game). It is fine as an *A/B arm*, which is all I use it for.
3. **Uneven stacks + ICM: documentation only.** The pricing effect is 2e-4 (3max) / 7e-5 (6max)
   ICM chips/hand, i.e. at or under the 0.0006 target at both table sizes; the caveat costs nothing
   here.
4. **Uneven stacks + chip EV: do not ship without a real leaf.** 0.0006–0.196 bb/hand is above the
   bar in every spot measured. Two honest options: restrict the chip-EV grid to equal stacks, or
   price the FLOP terminal properly — that is `moravcik`'s leaf, not mine; `stackoff` only shows
   the sensitivity is real.
5. **Make it fail loudly.** `solve3._require_leaf_free(tree)` (and `solve(..., require_leaf_free=
   True)`) now raises with the L0 explanation. I have left the default `False` rather than flipping
   it, since the grid is bowling's to freeze — one word changes it. Cell records already carry
   `counts`, so `flop: 0` is positive evidence; recording the build kwargs (`tier1`, `behind_cap`)
   would close the rest of the provenance gap, since the leaf-free variant reuses the same file
   hash.

**Mechanism caveat, stated as a limit not a claim.** Every FLOP terminal is *one all-in seat plus
two deep seats matched at the same level, single pot layer* (verified: 0 violations across
1/25/35/10 terminals at 3max/6max/ladder/2short). So this is not the flat-call live pot L0 was
measured on, but a three-way all-in main pot with an *empty* side pot between the two deep seats.
The sign above matches `leaf-model-L0.md`'s direction, but I would not carry its headline magnitude
across without re-measuring the leaf in this configuration.

## What would change my mind

An ICM structure where the FLOP reach at uneven stacks is not ~1e-4 or below would make point 3 a
blocker instead of documentation. A cross-cost below 0.001 bb/hand in chip EV would make point 4
vanish. A demonstrably calibrated leaf that agrees with L0 at these terminals would make the whole
item moot — and I would want it validated against a second implementation before trusting it.

## Reproduction

```
.venv/bin/python deepstack-swarm/workspace/burch/flopgap/lfcheck.py        # equal-stack identity + 0 FLOP proof
for s in 3max 6max ladder 2short; do .venv/bin/python deepstack-swarm/workspace/burch/flopgap/ab.py $s chip 0.001 20000 asis,leafree,stackoff; done
.venv/bin/python deepstack-swarm/workspace/burch/flopgap/ab.py 3max icm 0.0006 20000 asis,leafree,stackoff
.venv/bin/python deepstack-swarm/workspace/burch/flopgap/cross.py 3max icm
```

Inputs `ab-<spot>-<mode>.json` / `.npz` sit beside the scripts. `recon.py` reproduces
`bowling-tier1-flop-gap.md`'s terminal counts exactly; `reach.py` is cross-checked against
`seqbr.reach_probability`; `lfcheck.py` shows `behind_cap=1` is byte-identical at equal stacks
(n=2,3,6,9), which is what makes it a clean A/B arm rather than a second game.
