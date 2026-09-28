# Read: GTO Wizard, "Now Live: Preflop ICM Solving" (blog post, 15 Sep 2026)

Source: https://blog.gtowizard.com/preflop-icm-solving/
Companion: https://blog.gtowizard.com/gto-wizard-ai-benchmarks/ ("GTO Wizard AI Benchmarks", 19 Jul 2023, updated through Apr 2025)

This is a literature/marketing read, **not a finding**. Nothing here was run. Quotes are from
the two pages above, retrieved 2026-09-27.

## What they claim to ship

- Custom preflop solving with ICM, up to **9 players**, up to **250bb** deep, fields to **4,096
  runners**, customizable payouts/antes/bet sizes. "Most spots solve in 1 second."
- Formats: MTT, satellite, KO / PKO / TKO, Mystery Bounty.
- 3-way postflop ICM, carrying preflop ranges forward.
- Nodelocking, Player Profiles, frequency locking.
- Stated tree limit: "Preflop trees currently allow up to 3 players to reach the flop... Spots
  where a 4th player over-calls or over-limps aren't supported yet."

## The accuracy numbers they give, and what they cover

Only one accuracy figure appears in the release post:

> "Our latest flop model delivers an average Nash distance of 0.108% of the pot, down from 0.121%
> in April 2025: a further 10% reduction in exploitability across 900 heads-up chip EV flop tests."

Read the qualifiers: **900**, **heads-up**, **chip EV**, **flop**. That is a measurement of a
different game from the one the post is announcing. There is **no published exploitability figure
for any multiway, preflop, ICM or bounty solution** on either page. The headline feature is
unmeasured in public.

From the benchmarks page:
- Nash Distance = "the maximum potential EV loss of the current solution in big blinds divided by
  the pot."
- "Nash Distance was measured by nodelocking flop strategies." I read that as: lock the AI's
  strategy into a conventional solver's tree and compute the best response there. That is an exact
  best response **inside that tree's action abstraction**, which is a lower bound on real-game
  exploitability, not the real-game number. Same distinction as Johanson et al., *Accelerating best
  response calculation in large extensive games* (2011) and Lisý & Bowling, LBR (2017).
- Pre-solved ("General"/"Simple") solutions: at least 0.3% pot. Rivers re-solved to 0.1%.
- "EV losses are shown ± one standard deviation" on their charts — good; the release post drops the
  spread and reports only the mean.
- **April 2025: "we upgraded our engine and switched from Nash Equilibrium to Quantal Response
  Equilibrium (QRE)."** Average flop exploitability 0.17% -> 0.12% pot.

## Four things worth pushing on

1. **The accuracy number is for a different game than the feature.** See above. A 9-player ICM
   preflop solve and a heads-up chip-EV flop solve share an engine, not an error bar.

2. **Head-to-head is not exploitability.** The benchmarks page leads with "GTO Wizard AI beat
   Slumbot for 19.4 bb/100 in a 150k hand heads-up match." That is a match result. Johanson et al.
   (2011) found ACPC bots that beat each other by tiny margins had a wide range of exploitability.
   No confidence interval is given for the 19.4 bb/100 either. (They also call Slumbot "open-source"
   and cite "the most recent ACPC" — the ACPC has not run since 2018. Worth checking before
   repeating.)

3. **Solution concept.** They compute a **QRE** and report distance to **Nash**, while the product
   language throughout is "GTO" and "the correct play." QRE is a logit-response fixed point, not a
   Nash equilibrium; using it as a regularizer that lowers measured Nash distance is plausible, but
   the object being shipped and the object being measured should be named separately. This is the
   "what are we actually converging to" question (Morrill).

4. **9-player ICM is a general-sum game.** Regret minimization has no convergence guarantee outside
   two-player zero-sum, and in general-sum games equilibria are neither unique nor interchangeable.
   So "According to GTO, folding is the correct play" in the 2026 WSOP Main Event example is not a
   well-formed claim: which equilibrium, and how far from it? The post's own honest line —
   "A balanced solution answers 1 specific question: what is optimal against 8 opponents who all
   understand ICM perfectly? You have never sat at that table." — is nearly the right caveat, but
   "optimal against 8 opponents" is still loose: with more than two players, equilibrium gives you
   no guarantee against opponents who are not playing their part of the same equilibrium.

## Where they are right, and where it touches our code

- **Fold EV is not zero under ICM.** Their section "Why Fold EV Isn't Always Zero" is correct:
  folding changes the continuation and therefore your tournament equity, and card removal on a fold
  perturbs the remaining players. They settle on a fixed reference payoff (the equity you'd have if
  you lost the pot and the remaining players split it) so every action is measured against the same
  baseline. That is a **presentation** choice about baselines, not a change to the game.
  Our `pushfold/auditor.py:34` reports **absolute** per-seat EV (ICM chips per hand,
  `hands.PRIOR @ (now.sum(axis=0) + fixed)`), not EV relative to folding, so we do not have this
  problem. Worth confirming nothing downstream subtracts a fold baseline.

- **Same 3-way cap.** Their "up to 3 players to reach the flop" is the same action abstraction as
  `pushfold/floor.py:18`, `MAX_ALLIN = 3` — beyond the cap our tree forces a fold
  (`floor.py:80-83`). Neither of us has published what that cap costs. Agenda item 1 (Johanson) and
  the abstraction-pathology check (Waugh) apply to them as much as to us.

- **Units.** They report % of pot; we report bb/hand. Their own worked example converts: "a 0.3%
  loss in a 5bb pot would mean that solution could be exploited for, at most, 0.015 bb/hand."
  By the same arithmetic their current 0.108% in a 5bb pot is ~0.0054 bb/hand. Our `coach.py`
  default `target` is 0.01 bb/hand. Same order of magnitude — but ours is a whole-game preflop
  number in a 169-class model game with Monte Carlo 3-way payoffs
  (`oddsmaker.py:36`, `SAMPLES = 2000`), and theirs is a per-flop-subgame number. **Do not compare
  the two as if they were the same quantity.** The right response is agenda item 2: derive a
  defensible target for push/fold from the per-hand standard deviation of chip results and a
  lifetime-of-play test, as in Bowling et al., *Heads-up limit hold'em poker is solved* (2015).

## What would change my mind

Publication of a best-response or LBR-style bound for a multiway ICM preflop solution, stating the
tree it was computed in, the payout structure, the number of players, and a spread rather than a
mean. That would make the headline claim checkable. Absent that, the correct summary is: the speed
claims are specific and credible, and the accuracy claims are about heads-up chip-EV flops only.
