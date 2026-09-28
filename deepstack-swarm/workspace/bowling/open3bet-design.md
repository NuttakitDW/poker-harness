# ICM-OPEN3BET-v0 — the game we are proposing to solve, and who builds what

Written by `bowling` (PI), 2026-09-27. This is a **specification and a plan**, not a finding.
The only numbers in it that were run are in §5; everything else is a design decision or an
open question.

User request (verbatim intent): ICM charts with **open and 3bet** actions, several stack depths
**under 30bb**, for **two payout settings** ("small tournament" and "big tournament") from
`deepstack-swarm/assets/`, servable by ตามควาย the way the push/fold ICM chart is today.

## 1. What we have today, stated precisely

`pushfold/` solves a one-decision-per-seat game: every action is all-in or fold, so every ending
is either a fold or an all-in showdown, and every payoff is a preflop all-in equity
(`pushfold/pricer.py`, `pushfold/oddsmaker.py`). That is why the Auditor can compute an exact best
response by just taking the better action at each node (`pushfold/auditor.py:1-10`).

Adding open/3bet breaks **both** of those properties:

1. Seats act more than once and later actions depend on earlier ones, so the Auditor's
   one-action shortcut is no longer a best response. A proper sequential best response is needed.
2. Some endings do **not** go all-in preflop. Those hands see a flop. Their value is not a preflop
   equity, and it is not in our code anywhere. **This, not CFR, is the hard part of the request.**

## 2. The game, ICM-OPEN3BET-v0

No-limit hold'em, **preflop only**, n = 2..9 seats, stacks 5-30bb, sb 0.5, bb 1, ante as in
`Spot` (`each` or `bb`), fee 0 unless the format charges one.

Hand abstraction: the same 169 classes, with the same independent-prior opponent model for 3+
players (`pushfold/pricer.py:20-28`). Unchanged from today, and still an abstraction.

Action abstraction v0 (deliberately small; sizes are a v1 question, see §6):

| situation | actions |
|---|---|
| unopened, not BB | fold, open 2.2bb, all-in |
| unopened BB | (action closed: walk) |
| facing one raise | fold, call, 3bet to 3x the facing raise, all-in |
| facing a 3bet or more | fold, call, all-in (a 4bet is all-in only) |
| facing an all-in | fold, call |

A raise size is clipped to the stack, and dropped as an action when it is within 1bb of all-in.
No limps in v0. **Known gap:** at 8-12bb the SB limp is a real part of ICM solutions; v0 will be
wrong about SB-vs-BB at those depths and must say so.

Cap: at most **3 players** may still hold cards when preflop ends. Beyond the cap the tree forces
a fold, exactly as `pushfold/floor.py:18` does with `MAX_ALLIN = 3`. GTO Wizard ships the same cap
("Preflop trees currently allow up to 3 players to reach the flop"; see
`workspace/bowling/gtowizard-preflop-icm-read.md`). Neither they nor we have published what it
costs.

Ending types, and how each is priced:

| ending | pricing | status |
|---|---|---|
| everyone folds | blinds/antes move | exists |
| one raiser uncontested | pot to the raiser | exists |
| 2-3 players all-in preflop | `e2` exact / `eq3`,`pw` Monte Carlo | exists |
| **2-3 players see a flop** | **needs a leaf model** | **does not exist** |

## 3. The leaf model, and the one thing that must not be got wrong

Under ICM the value of a stack is **concave**. So a flop leaf may not be summarized by a scalar
chip EV: winning 10bb half the time and losing 10bb half the time is not worth the same as
keeping your stack. A leaf model must return a **distribution over the players' final stacks**,
which is then priced by `pushfold/icm.py`. Any leaf that returns "expected chips" is wrong under
ICM, and wrong in the direction that matters (it will under-tighten).

Three candidate leaves, in increasing cost:

- **L0 "checkdown".** Nobody bets again. The pot is awarded at all-in equity among the players who
  reached the flop; the remaining stacks stay where they are. This is a distribution over final
  stacks, so it prices under ICM with the machinery we already have. Bias is real and directional:
  it deletes position, fold equity and playability, so it makes calling a small open look better
  than it is, and it treats a hand that realizes equity badly as if it realized it fully.
- **L1 "realization".** L0 with a per-class equity-realization factor depending on seat count,
  SPR and position, still emitted as a distribution over stacks. Cheap, tunable, biased in a way
  we can at least name.
- **L2 "learned leaf value".** A value function over (range pair, pot, effective stack) returning
  a distribution over chip outcomes, trained from postflop solves. This is the DeepStack
  construction (Moravčík et al., *DeepStack*, Science 2017) applied at the preflop-to-flop
  boundary.

**What we may claim from v0.** An equilibrium of the model game *including its leaf model*, with a
measured exploitability in that model game. Not "the GTO ICM chart". The honest accuracy statement
for a product is the **spread between charts solved under L0 and L1** (and later L2): that spread
bounds nothing rigorously, but it is a measured sensitivity, and it is more than GTO Wizard
publishes for its multiway ICM solutions.

## 4. Caveats that must survive into the product copy

- With 3+ players, or with ICM payouts, the game is **general-sum**. CFR's convergence guarantee
  (Zinkevich et al., *Regret minimization in games with incomplete information*, NIPS 2007) covers
  two-player zero-sum only. Low exploitability there is **measured, not guaranteed**, equilibria are
  neither unique nor interchangeable, and playing your part of one gives you no guarantee against
  opponents who are not playing theirs.
- So every v0 chart must be re-solved from at least two methods (`cfr+`, `dcfr`) and report whether
  the strategies agree, not just whether each is low-exploitability.
- Units: report exploitability in **ICM chips per hand** (that is what `icm.py` scales to) and also
  as **% of pot**, so it can be set beside GTO Wizard's Nash distance. Do not compare a whole-game
  preflop number to their per-flop-subgame number without saying so.

## 5. Feasibility, measured

Commit `b75e315`, `.venv/bin/python`, full-width CFR+, chip EV, 15bb equal stacks,
20 iterations, `deepstack-swarm/workspace/bowling/` (timing only, no claim about the strategies):

| seats | nodes | terminals | ms / iteration |
|---|---|---|---|
| 3 | 6 | 7 | 7 |
| 6 | 40 | 41 | 16 |
| 9 | 128 | 129 | 38 |

A rough enumeration of the v0 tree (`count_tree.py`, approximate, cap logic crude, heads-up case
known wrong) gives roughly 125 nodes / 280 terminals at 6-handed and 480 / 1080 at 9-handed —
about **7-8x today's terminal count**, so of order 0.1-0.3 s per iteration. A 2000-iteration solve
is then minutes per spot, not hours. **Precomputing a library is feasible; solving on a user's
request in one second is not, on this design.**

## 6. Open questions I am not deciding yet

1. Bet sizes. One open size is an action abstraction; a finer one can score *worse* in the real
   game (Waugh et al., *Abstraction pathologies in extensive games*, AAMAS 2009).
2. Limps at 8-12bb.
3. What "essentially solved" should mean for an ICM preflop game: which ε, in which units, and
   whether a tournament player could ever tell the difference.
4. The scenario grid: an ICM chart is not a function of hero's stack alone. It depends on every
   stack, the field, and the payouts. The product needs a small, honest set of canonical spots.

## 6b. PI decision after the L0 finding: split the request in two

`workspace/findings/leaf-model-L0.md` (moravcik, verified) shows that under a checkdown leaf the BB
flat-calls a 2.2bb open with **100% of hands** at every opener range down to about the top 10%, and
that the calling range runs 100% -> 12% as the leaf is allowed to move 0% -> 100% of the money
behind. So in v0 as specified, **the chart is governed by the leaf model, not by the solver.** I am
not going to ship a chart whose ranges are set by a knob nobody has measured. I am splitting the
request:

**Tier 1 — "open or jam", exactly solvable, no leaf at all.** Actions: unopened {fold, open 2.2bb,
all-in}; facing an open {fold, all-in}; facing an all-in {fold, call}. **There is no flat call, so
every ending is a fold, an uncontested raise, or an all-in showdown — exactly the three ending types
`pushfold/` already prices.** No flop is ever seen, no leaf model exists to be wrong, and the
result is an equilibrium of a model game whose only abstractions are the ones we already ship (169
classes, independent priors, the 3-handed cap, Monte Carlo `eq3`). This is a real product: it adds
the open size, and therefore steal/fold-equity structure, that push/fold cannot express. The
honest caveat is one sentence: **nobody may flat, so the chart is wrong wherever flatting is a live
option** — which grows with depth and is worst in the BB.

**Tier 2 — add the flat call.** Needs a leaf. Not a solution until R and sigma are measured rather
than chosen. Gated on data (see below).

**A by-product worth more than the L0-vs-L1 spread.** Tier 1 and the L0 tree are two games that
differ in exactly one action: whether flatting exists. Tier 1 forbids the flat; L0 permits it with
full equity realization. Both are exactly computable with no tuned parameter. The difference
between their charts is therefore a **sensitivity to the one action the leaf model governs**, made
of two solves rather than two settings of our own dial. It is not a bound — denying the flat may
push the BB into over-jamming rather than simply making opens too good, so the direction is not
clean — but it is measurable and it is not a knob. This replaces §3's spread proposal, alongside
moravcik's sigma sweep.

## 7. The delivery path already exists (checked, not a claim about quality)

Two things I verified by reading the serving layer, because they change what has to be built:

- The display and chart format already handle **multi-action charts with mixed frequencies**.
  `harnesses/charts/preflop-tournament.json` stores entries of the shape
  `{stack, section, hero, villain, scenario, actions: "RRRF...", mixed: {"ATo": {"raise": 0.6,
  "fold": 0.4}}}`, and `scripts/voice/chart_grid.py` renders R/C/F with per-cell frequency shading.
  So an open/3bet chart needs no new presentation work, only new fields (payout setting, players
  left, stage). It does need a third action code drawn distinctly for 3bet vs open.
- The live solver path `scripts/voice/pushfold_chart.py` is capped at `MAX_STACK = 15`, and solves
  on demand in under two seconds. The user is asking for **30bb**, where that path will not hold:
  both the depth and the tree are bigger. Serving must move from solve-on-demand to a precomputed
  library with an explicit refusal when a question falls outside the grid.

**Correction to the first bullet above (checked again 2026-09-27 late, and my earlier claim was
wrong).** The format does *not* already handle the chart we are building. `harnesses/charts/
preflop-tournament.json` encodes one character per hand drawn from `{"R","C","F","-"}`, and
`scripts/voice/chart_grid.py:29` fixes the whole vocabulary at
`ACTION_CODES = {"raise": "R", "call": "C", "fold": "F"}` with `PLAIN` and a three-step colour ramp
(`chart_grid.py:32,38,39`). A Tier 1 cell has **two** distinct raises -- `open 2.2` and `all-in` --
and there is no second raise code. `chart["names"]` can only *rename* a code (that is how push/fold
shows "shove"); it cannot add one. So the delivery work is real: a fourth code, its colour and
legend in `chart_grid.py`, the same in the chart image path, and the mixed-frequency shading rule
(`chart_grid.py:70`) which currently assumes the winner of a mix is one of three. Small, but it is
code in `scripts/`, not a field in a JSON, and it should be scoped before anyone promises a ship
date.

## 8. Assignments

- `burch` — the tree and the solver for §2. Interface: a drop-in replacement for `floor.build`
  plus whatever `pricer`/`coach` need, in the workspace, never editing `pushfold/`.
- `moravcik` — the leaf model of §3. L0 first, as a distribution over final stacks; then say what
  L1/L2 would take.
- `johanson` — a **sequential** exact best response for the new tree. Today's Auditor is not one.
- `bard` — the scenario grid of §6.4, from the two payout files in `deepstack-swarm/assets/`.

## 9. Status, 2026-09-27, later the same day

Four findings landed: `burch-open3bet-tree-and-cost.md` (real tree 10-20x bigger than my §5
estimate; full width beats sampling; two correctness gaps: own-reach-weighted averaging, and
`pushfold/auditor.py` is not a best response here), `leaf-model-L0.md` (L0 alone is degenerate —
BB calls 100% — confirmed the Tier 1/2 split), `johanson-open3bet-seqbr.md` (sequential best
response built and validated against `pushfold/auditor.py` on push/fold; on a toy open/3bet tree
the old shortcut over-reports exploitability by 1.1-3.7x), `bard-scenario-grid.md` (bubble factor
alone is not a sufficient grid index; stack configuration and ante each need their own axis,
confirmed on push/fold as a lower bound). I then built and ran Tier 1 myself
(`bowling-tier1-first-solve.md`): the tree is exactly the 3 ending types claimed, it solves, the
shortcut is wrong here too (1.1-1.5x), and the reference engine is 8-60x too slow to be a
production path — that part is squarely burch's, not a new design question.

**Next assignment: `burch`** — build Tier 1 (open-or-jam, no flat, no 3bet) on your `floor3`
conventions (global sequence ids, `own_prev`) so it inherits your measured speed, and wire
`johanson`'s `seqbr.audit` as the stop rule once ported onto `own_prev`. Cross-check against
`deepstack-swarm/workspace/bowling/tier1.py`'s reference numbers on a small case before trusting
either. This is the path to an actual first Tier 1 chart with a real `target`.

## 10. Status, 2026-09-27, evening: Tier 1 chip EV is production-speed, ICM is not yet

`burch-tier1-solve.md`: Tier 1 on `floor3`/`pricer3`/`coach3`, real stop rule
(`seqbr3.FastAuditor`, 17-129x faster than johanson's generic oracle at chip EV by batching the
terminal-value contraction the way `pricer3.values` already does). Converges to 0.0001 bb/hand at
every n = 2..9 (9-handed: 4875 iterations, 370s). Cross-checked against my `tier1.py` reference on
an independent tree/solver at 3-handed: chip EV 0.8-2.4% apart, ICM 0.8% apart once actually
solved for ICM rather than audited under it (his first ICM attempt was 40x off from auditing a
chip-EV-optimal strategy — not a bug, wrong game, a useful cautionary data point for anyone
auditing under payouts a solve didn't target). Side finding: `johanson/toy_open3bet.solve` (my
reference's dependency) averages raw sigma, not own-reach-weighted — the bug burch's first finding
flagged, confirmed present in the file I used to cross-check against; moved the answer 0.8-2.4%
here, unknown on a bigger tree. Not fixed yet; low priority given the size of the effect measured
so far, but flagged for whoever next relies on that file.

**What's missing before a real chip-EV Tier 1 chart:** short-stack open-clipping and forced-post
handling for 5-12bb (§6.1/6.2), and a Monte Carlo `SEED` sweep, since 0.0001 bb/hand is far below
the unmeasured noise floor of `oddsmaker`'s 2000-sample 3-way tables — burch is right not to read
it as a real-money precision claim yet.

**What's missing before an ICM Tier 1 chart (the actual product ask):** a production ICM pricer.
`burch`'s ICM cross-check used the slow generic oracle (84s for one 3-handed spot) — correct, but
not chart-scale. Next assignment: **`burch`**, build `pricer3`'s ICM path, using
`pushfold/icm_pricer.py`'s three-ending-type structure as the template (Tier 1's terminals are
exactly ALLFOLD/UNCONTESTED/SHOWDOWN, the types that file already prices). This is the last piece
standing between the swarm and an actual first Tier 1 ICM chart with a stated exploitability.

## 11. Status, 2026-09-27, night: ICM pricer done and independently re-verified; the target is the open problem now

`burch-icm-pricer3.md`: `icm_pricer3` now solves Tier 1 for ICM at chart scale (167 ms/iteration
n=9, vs 22.6 s for the old reference), cross-checked against `johanson`'s slow oracle to float32
precision. **I re-ran `verify_icm3.py` myself on this commit before accepting it**: per-node max
|diff| 8.9e-15 / 1.1e-5 / 1.8e-5 / 5.2e-5 / 5.2e-5 at n=2/3/4/6/9, and n=3 iter 400 = 0.008117
ICM chips/hand — byte-for-byte the finding's numbers. `tests/test_pushfold/` (128 tests) passes.
So: solving is production-speed, in both chip EV and ICM; the **audit** is still the slow oracle
(318x iteration cost at n=6), which is a grid-scale concern, not a first-chart blocker.

The open problem is no longer "can we solve it" but **"what exploitability is worth stating, in
which units"** — my own §6.3. Two numbers bound any honest `target`:

- **Ceiling — the lifetime-of-play ε.** Cepheus's threshold (source 9): ε small enough that a
  lifetime of play (200 hands/hr × 12 hr/day × 365 × 70 yr = 61,320,000 hands) can't distinguish
  the strategy from exact at 95% (1.64 SDs): ε ≤ 1.64 σ / √(61.32M), where σ is the per-hand SD of
  the outcome. Nobody has measured σ for push/fold. → `davis`.
- **Floor — the model's own noise.** `oddsmaker`'s 3-way tables are Monte Carlo, `SAMPLES=2000`,
  `SEED` hardcoded. `burch` has flagged three times that any target below the seed-induced chart
  movement is meaningless; nobody has measured that movement. → `burch`.

If floor > ceiling, the honest answer is to raise `SAMPLES` (or go exact on 3-way), not to lower
the claim. Both are assigned in parallel; the choice of a final `target` waits on both.

## 12. Status, 2026-09-27, later still: the lifetime ε is measured; target is set; the model's own error is the real floor

`davis-lifetime-eps.md` landed and I verified it (re-read `lifetime_eps.json` / `noise_floor.json`,
checked the arithmetic ε = 1.64σ/√61.32M myself). σ_hand = 4.6–6.3 bb/hand chip EV, 3.0 ICM
chips/hand at the bubble, stable to <0.5% across targets 0.0005–0.003 and seeds. ε = 0.96–1.31
mbb/hand chip EV and 0.63 mICM/hand at the bubble. **Target decision: `0.001` bb/hand chip EV,
`0.0006` ICM chips/hand.** The default 0.01 is 8–16× ε and detectable in ~1 year; 0.001 is free
(25–100 CFR+ iterations). This replaces the habit target for the whole swarm.

Two findings inside it change the story, both to be carried into the product copy:

1. **The Monte Carlo table noise is NOT the floor.** Rebuilding eq3/pw under a different seed moves
   the chart 0.06–0.11% dTV and exploitability by ~0.0001 — 6× below ε. `SAMPLES=2000` is adequate
   for a 0.001 target. (`burch`'s independent Tier-1 cross-audit is consistent: "barely moves".)
2. **The independent-deal opponent model IS the floor** (davis §6). At 3+ seats `pricer.py` deals
   opponents independently; true blocker-aware pricing differs from the model EV by up to 0.026 ICM
   chips/hand = **40× ε**. So at 2 seats `0.001` is a real exploitability; at 3+ seats the honest
   quote is "solved to 0.001 **in a model** whose seat-level pricing error is ~0.01–0.03", not
   "0.001 exploitability". This is agenda item 1 and now the main open problem for the multiway
   product — assigned to `johanson` (full-combo exact best response with card removal) as the
   measurement, with the fix (card removal in the pricer) to follow whichever way the measurement
   points.

## 13. Status, 2026-09-27, night: seed-noise floor confirmed on the Tier 1 tree; one new product caveat

`burch-seed-noise-floor.md` (verified: I read the saved cross-audit and control JSONs — the
numbers reproduce exactly). Tier 1 n=6 15bb, three independent table seeds: reported
exploitability moves ≤ 1.2e-6 bb/hand (chip) and 7.4e-7 ICM chips/hand; the stated floor is
**1e-5 bb/hand and 1e-5 ICM chips/hand** (≈3σ). The targets (1e-4 chip / 1e-3 ICM) clear it by
50–5000x. **Conclusion stands: do not raise `SAMPLES`.** His uniform-profile control (a 2.04
exploitability moves 3.4e-4 under the same tables) proves the audit responds to the tables, so
the converged insensitivity is real, not a frozen measurement. Two results agree across two
independent implementations and two trees (his Tier 1, davis's push/fold): table noise is not the
binding uncertainty.

**New caveat for the product, from burch §8:** the *exploitability* is safe, but the *chart* is
not reproducible to better than dTV ≈ 0.002, and at near-indifferent call-off nodes an individual
class moves by up to **0.25** in frequency between seeds (KK at the BB facing a 3bet-jam, ICM).
That is regret-matching arbitrating between near-equal actions — an equilibrium does not pin down
a near-indifferent hand's mix — so it is a **display/selection** problem, not a solve-accuracy
one, and raising `SAMPLES` will not fix it. A stable-across-seeds selection rule (or marking such
cells "marginal" in the UI) is queued; I am not assigning it until `johanson`'s model-vs-real gap
lands, since that may change what "the chart" even claims to be.

## 14. Status, 2026-09-27, night: "exploitability ranks, it does not bound" — the response-function measurement

`davis-responder-ladder.md` (the queued half of agenda item 2; Davis, Burch, Bowling, *Using
Response Functions to Measure Strategy Strength*, AAAI 2014). One 6-max 10bb chip-EV spot, chart
solved to 0.00075, exploitability **0.000698** bb/hand (below the lifetime bar, invisible) — while
a ladder of *weaker-than-best* responders loses the chart **0.024 / 0.278 / 0.351** bb/hand
(static / k=100 / k=0), i.e. **35×/398×/503×** the exploitability. Validated: the extracted best
response has residual gain exactly 0.0000000, and the simulated BR value matches `auditor.audit`
within 0.9 se. The inversion test (does a lower-exploitability chart do worse against weak
responders?) was run on two charts 3.8× apart in exploitability and is **negative but without
power** — every rung inside 1.96 se, four of five nominally favour the tighter chart; it rules out
a gross (≥0.02) inversion, not a 0.001–0.003 one, and the fix is a bigger contrast (a CFR-f chart
trained against a weak responder), a build I am not scheduling yet.

**Product carry-forward:** "essentially solved" is a worst-case guarantee (nobody beats the chart
by more than ε); it says nothing about how much the chart *collects* from real, non-best
responders — that is opponent-dependent and measured here at 35–500× ε. Do not phrase "0.001
exploitability" as "wins X against your table"; if the product's value is win-rate against home
games, the response function at realistic opponent points (bard's real-population work) is the
right number, not the exploitability.

## 15. Status, 2026-09-27, late: two PI findings, and the next build is Tier 1.5

I ran the checks myself rather than waiting. Two findings, both mine:

1. **`bowling-tier1-flop-gap.md`.** Tier 1's "no leaf model is consulted" guarantee holds only at
   **equal stacks**. `floor3.close()` marks a terminal `SHOWDOWN` only when at most one live seat has
   chips behind, and Tier 1 still lets a bigger stack call a short jam, so unequal stacks produce
   FLOP terminals (25/131 at 6-max with 4-30bb stacks, 35/131 on a 5-30bb ladder, 1/17 at 3-max).
   `icm_pricer3.plan()` branches on `len(z.live)` only and `seqbr._worth` settles from `z.jammers`,
   so those terminals are priced as the **L0 checkdown leaf** -- silently, with no error. The grid
   running now is all equal-stack and is not affected; an uneven-stack chart would be. → `burch`.

2. **`bowling-tier1-what-it-computes.md`.** What the model actually produces. Seat 0 never mixes
   the two raise sizes: below ~15bb it jams (0.240 at 8bb, 0.178 at 12bb) and never opens (0.000);
   above it opens (0.217 at 20bb, 0.272 at 30bb) and never jams (0.000). Later seats do open at 8bb
   (0.29/0.33/0.42 for seats 2/3/4), so the chart is not just push/fold there. Facing one open, the
   per-seat mean re-jam is 0.55-0.70 at 8bb chip EV and 0.09-0.32 at 30bb. ICM at the bubble roughly
   halves the 8bb re-jam and barely moves the 30bb one -- an open question I have flagged, not a
   finding.

**The decision this forces.** Above ~15bb the Tier 1 game is "open-or-fold, answered by
jam-or-fold": no flat, no 3bet. That is the user's ask minus the 3bet. So the next build is
**Tier 1.5: add the 3bet, keep the no-flat rule**, which preserves the property that every terminal
is a fold, an uncontested raise or an all-in showdown -- no leaf, at equal stacks:

| situation | Tier 1 today | **Tier 1.5** |
|---|---|---|
| unopened | fold, open 2.2bb, all-in | unchanged |
| facing one raise, not all-in | fold, all-in | **fold, 3bet to 3x, all-in** |
| facing a 3bet (raises >= 2), not all-in | fold, all-in | fold, all-in |
| facing an all-in | fold, call | unchanged |

The only change is one branch: when `raises == 1` and the aggressor is not all-in, allow `RAISE`.
Note the trap: the existing code reaches `raises >= 2` through the `facing_allin or raises >= 2`
branch *before* any tier1 check, so that branch must also lose its `CALL` when the aggressor is not
all-in, or a flat call reappears and a FLOP terminal with it. A seat's decision depth is still 2
(open, then face a 3bet), which `pricer3`/`icm_pricer3` already support.

**Why it matters more than it looks:** in Tier 1 a 30bb stack facing an open can only fold or shove
30bb, so the chart cannot say "3bet AA". That is the single largest way the current chart is not a
30bb chart, and Tier 1.5 fixes exactly it at no modelling cost. → `burch`, after the FLOP item.

**Quantified, 2026-09-28 (`burch-tier1.5.md`).** The claim above was mine and unmeasured; burch
measured it by evaluating the Tier 1 chart *inside the Tier 1.5 game*, max seat:

| stack | cost of the missing 3bet | vs the 0.001 bb/hand bar |
|---|---|---|
| 15bb | +0.0002 bb/hand | below the bar |
| 30bb | **+0.041 bb/hand** | **41x the bar** |

A ~200x growth with depth, tracking a 3bet that is played 13-22% of hands at 15bb and 22-37% at
30bb. So the claim survives and is sharper than I stated it: **the missing 3bet is worth nothing at
15bb and 41x the lifetime bar at 30bb.** The practical reading is that the Tier 1 chart is a
short-stack chart, and it is the 20bb/30bb cells -- 24 of the 80 -- that need Tier 1.5 before they
are anything like a real 30bb chart.

Two caveats burch attached, both of which I accept:
- The 0.041 comes from a chart whose own gain is 0.00197, i.e. not converged, so read it as **>=0.039**.
- **Tier 1.5 is ~100x slower to converge at 30bb** (Tier 1 reaches 3e-5 by iteration 2000; Tier 1.5
  follows ~T^-0.4, needing ~1.4e5 iterations for 0.001 at n=3). It is the first game here where a
  seat acts twice on a path; the auditor is not at fault (`FastAuditor` agrees with the reference to
  1e-12 on these trees). At 15bb it is cheap (n=6: 1225 iters / 191s), so a Tier 1.5 build should
  start short and stop at 20bb, not start at 30bb.

## 16. Status, 2026-09-28: the first 41 cells are quarantined; every cell now carries its code

**What was wrong.** Each cell JSON said `"commit": "b75e315"`, and that was true but useless:
`deepstack-swarm/workspace/` is untracked by git (`git ls-files deepstack-swarm/workspace/` → 0
files), so the field pinned `pushfold/` and the repo around it, not the solver. Meanwhile the
solver modules were edited *during* the solve window (`fasticm3.py` 22:24 inside; `floor3.py` 23:30
and `solve3.py` 00:12 after), and `solve3.py` landed while a grid process was still running and had
already imported it. So the 41 cells were not one artifact, `final_gain` was not one auditor
version, and the chart could not be re-run from its own record. Full evidence and reasoning:
→ `findings/bowling-grid-provenance.md`.

**The rule from here.** A cell is only quotable if its `code_fingerprint` matches the fingerprint of
the run it belongs to. A grid is one artifact or it is nothing.

**What changed in the code.** New `tier1chart/provenance.py` (digests + `fingerprint()` +
`snapshot()`); `grid.py` writes `code_fingerprint` and the per-module `code` dict into every cell,
snapshots the exact modules into `cells/code-<fp>/`, and warns about any cell from another
fingerprint.

**Current artifact.** Fingerprint `fa654842`; the 13 digests are in every cell and the code is
frozen in `tier1chart/cells/code-fa654842/`. Key ones: `floor3` 205d0996b284, `solve3`
6651e736ebe4, `fasticm3` 6b6d8dde3333, `pricer3` ab3e7511cc15, `icm_pricer3` 550b3ef215f2,
`seqbr3` 760f67d7bb3e, `coach3` 631218729ebb.

**The 41 old cells** are in `tier1chart/cells-prev-noprov/`, quarantined not deleted — the only
record of that work, but not to be quoted. The grid was restarted from scratch into `cells/`, so
the delivered chart is a single artifact. Cost: ~8h re-solve, accepted rather than shipping one
chart built from two solvers. → asked `burch` to confirm `floor3.py`/`solve3.py` are final; any
further edit means another re-solve, and a strengthened-cap variant belongs under its own
fingerprint rather than perturbing this one.

## 17. Open risk: one `target` is being used for two different stages

**The hole.** `davis-lifetime-eps.md` §2 measures σ_hand and derives ε at **one** spot: the bubble,
6-handed 10bb with a bb-ante, 46 left of 300, σ_max 3.03 ICM chips/hand → ε = 0.000628. The grid
adopted `TARGET = 0.0006` and applies it to all 80 cells. But `scenarios.stages()` sweeps **two**
stages per structure -- `bubble` (`paid+1` left) and `past` (`paid*2` left, i.e. 90 of 300) -- and
only the first is the spot ε was measured at.

**Why it is a correctness risk and not a rounding one.** Past the money the payout ladder is much
flatter, so the marginal ICM value of a chip is nearer linear and I expect σ_ICM at `past` to sit
**below** the bubble σ. If so ε_past < 0.0006, and the stop rule is *looser* than the lifetime bar
for exactly those 40 cells: they would stop early and be under-solved, i.e. not quotable, rather
than wrong-but-fine. This is the failure mode the checklist exists to catch, and it is invisible in
the cell record -- `final_gain ≤ target` looks like success whether or not `target` was the right
number.

**What is not in doubt.** σ does not move with `target` (§2, stable to <0.5% across targets
0.0005-0.003 and across seeds), so this is not a re-derivation of the ε formula; it is one
measurement at one more spot. Also `big` (1500 runners) is a second structure with its own ladder,
so there is a second version of the same question.

**Action.** Asked `davis` for σ_hand at a representative `past` spot in each structure, and for
whether structure (`small` vs `big`) is an axis at all. If ε_past lands within ~10% of ε_bubble I
keep one target and record that it was checked; if it is materially lower I set a per-stage target
and re-solve the `past` cells. Either way `verify_cells.py` should stop accepting a bare
`final_gain ≤ target` and check the cell against the ε for *its own* stage.
