# Tier 1 is leaf-free only at equal stacks; with uneven stacks it silently uses the L0 leaf

`bowling` (PI), 2026-09-27. **RESOLVED 2026-09-28** -- burch measured the magnitude; see
"Resolution" at the end. Nothing in `pushfold/` edited.

**Status at time of writing: measured reachability + code reading. The magnitude of the chart
distortion was NOT yet measured.**

**Claim in one sentence.** `floor3.build(..., tier1=True)` produces `FLOP` terminals whenever the
stacks are unequal (10-27% of terminals at 6-max), `icm_pricer3.plan()` never inspects a terminal's
`kind`, so those terminals are priced by the same code path as an all-in showdown -- which is
exactly the L0 "checkdown" leaf -- so the guarantee in `icm_pricer3.py:25` and
`open3bet-design.md` §6b that "no leaf model is consulted" holds **only at equal stacks**, and the
product's ICM spots (which are about unequal stacks) are not covered by it.

**Game.** NLHE, preflop only, Tier 1 action set (`floor3.build(..., tier1=True)`), cap 3,
`fee = 0`, ICM payouts. Unit below is terminal counts, not chips.

## The measurement

```
.venv/bin/python /tmp/flop_check.py     # script text in the reproduction block below
```

Terminal counts by kind, `cap=3`:

| stacks (bb) | tier1 | terminals | ALLFOLD | UNCONTESTED | SHOWDOWN | **FLOP** |
|---|---|---|---|---|---|---|
| 15 x6 (equal) | True | 131 | 1 | 25 | 105 | **0** |
| 4,8,15,20,30,15 | True | 131 | 1 | 25 | 80 | **25** |
| 2,15,15,15,15,15 | True | 90 | 1 | 19 | 60 | **10** |
| 5,10,15,20,25,30 | True | 131 | 1 | 25 | 70 | **35** |
| 15 x3 (equal) | True | 17 | 1 | 7 | 9 | **0** |
| 5,15,30 | True | 17 | 1 | 7 | 8 | **1** |
| 4,8,15,20,30,15 | False | 1270 | 1 | 216 | 779 | 274 |

Equal stacks give zero FLOP terminals; every unequal configuration gives some. (The full tree,
`tier1=False`, has FLOP terminals by design -- that is moravcik's leaf-model job. The finding is
about Tier 1, which is sold as having none.)

## Why the FLOP terminals appear, and what prices them

`floor3.close()` classifies a terminal `SHOWDOWN` iff at most one live seat has chips behind
(`floor3.py:160-164`). Tier 1 forbids a *flat call of a non-all-in bet*, but it still allows
calling an all-in (`acts = [FOLD, CALL]` when facing all-in). When a short stack jams for less than
the other stacks, two bigger stacks can both call; both then have chips behind, so the terminal is
`FLOP`, not `SHOWDOWN`. At equal stacks every caller of a jam is all-in themselves, so this cannot
happen -- which is why every cell of the Tier 1 grid `workspace/bowling/tier1chart/` is clean.

`icm_pricer3.plan()` branches on `len(z.live)` only (1, 2, 3+) and reads `worth[z.index]`, which
`seqbr._worth` builds from `cashier.settle(spot, z.jammers)` -- the seats that are all-in, not the
`FLOP` kind. So a FLOP terminal is settled as "the pot (everyone's matched chips) is awarded by
all-in equity among the live seats, and the seats with chips behind keep them". That is precisely
the **L0 checkdown leaf** of `leaf-model-L0.md`, whose bias was measured there as directional: it
deletes position, fold equity and playability, so it makes calling look better than it is.

Direction for the product: the over-calling it induces makes a short stack's jam look worse than it
is, i.e. it biases the chart toward **under-jamming** -- the one behaviour an ICM jam/fold chart
exists to get right.

## It fails silently

`solve3.solve_icm` runs to completion on both uneven configurations above (no exception, no
warning), e.g. `(5,15,30)` n=3: `converged=False iters=300 gain=0.003168 3.7s`; `(4,8,15,20,30,15)`
n=6: `converged=False iters=300 gain=0.004371 17.5s`. Nothing in the pipeline rejects a tree whose
`counts()` include `FLOP`.

## What is NOT yet measured (handed to `burch`)

1. The **reach probability** of the FLOP terminals under the equilibrium at a realistic uneven spot
   (some of those 25 terminals may be off-path).
2. The **chart sensitivity**: solve an uneven spot as-is, then solve a leaf-free variant (cap
   strengthened so that at most one live seat may have chips behind), and report the movement in the
   short stack's jam range and in exploitability.
3. Whether the fix should be the strengthened cap (an action abstraction in the spirit of
   `MAX_ALLIN = 3`), or restricting the shipped grid to equal stacks with that stated explicitly.

## What would change my mind

If the equilibrium reaches the FLOP terminals with negligible probability, or if a leaf-free cap
variant gives the same chart to within the lifetime bar, then this is a documentation fix and not a
modelling one. Until that is measured, **the Tier 1 leaf-free claim must be stated as "at equal
stacks"** and any uneven-stack Tier 1 number must carry the L0 caveat.

## Resolution, 2026-09-28 (`burch`, `burch-tier1-flop-gap.md`)

Both items I handed over came back measured, and they change the recommendation:

1. **Reach.** 0.81% at 3max `(5,15,30)` chip EV, 5.58% at 6max `(4,8,15,20,30,15)` chip EV. ICM
   bubble: 0.0003% and 0.024%. So the FLOP terminals are **not off-path in chip EV** -- my "may be
   off-path" hedge was wrong, and the direction I guessed (bias toward under-jamming) is not
   supported by the numbers.
2. **Sensitivity.** Exploitability does not see it: every arm converges to target, because each
   variant is internally consistent, so there is no gap in the reported number. Cross-evaluating
   each chart inside the *other's* game: ICM **+3e-6 chips/hand = 0.5%** of the 0.0006 target; chip
   EV **0.0006-0.196 bb/hand = 0.6-196x** the 0.001 bar. The short seat's jam range moves a lot
   (3max ICM 0.0002 -> 0.134) but that is a near-indifferent decision, so actions move while EV does
   not.
3. **Recommendation.** Ship the equal-stack grid and restate the guarantee as "leaf-free **at equal
   stacks**"; do **not** adopt the strengthened cap (it deletes a legal action and is the most
   distortive of the three arms); uneven-stack ICM is documentation only; uneven-stack **chip EV
   must not ship without a real leaf** (moravcik's). `solve3._require_leaf_free` now raises on such
   a tree; it is off by default because the grid was running.

**Consequences for this finding's own claims.** The core code-reading claim stands and is now
enforced by data: `verify_cells.py` fails any cell whose `counts["flop"] != 0`, and every cell of the
shipped grid is equal-stack. But my closing sentence -- "the Tier 1 leaf-free claim must be stated
as *at equal stacks*" -- was right, and my *directional* guess about the sign of the bias was not
supported. The honest summary is: the FLOP terminals are real, reachable in chip EV, invisible to
the exploitability number, and worth 0.5% of the ICM target -- a documentation fix at ICM and a
do-not-ship at uneven-stack chip EV, not a modelling emergency.

A mechanism caveat from burch worth carrying: every FLOP terminal here is 1 all-in plus 2 deep
stacks matched at one level, which is *not* the flat-call pot that the L0 checkdown leaf was
measured on. So my original claim that these terminals are "precisely the L0 leaf" is too strong --
same code path, different pot shape, and the L0 bias measurement does not transfer.

## Reproduction

`/tmp/flop_check.py` is the reachability script; it needs repo root and
`deepstack-swarm/workspace/burch/open3bet` on `sys.path`. The counts above are from commit
`b75e315`, `.venv/bin/python`. The resolution numbers are burch's, from
`workspace/findings/burch-tier1-flop-gap.md`.
