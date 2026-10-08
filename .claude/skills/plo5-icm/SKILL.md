---
name: plo5-icm
description: Review a PLO5 (or PLO4) tournament session from a GGPoker hand history with per-hand ICM CFR solves, rate every hero decision in dollars of tournament equity, build the private review dashboard, and publish the solved spots to tamkwai.com/plo5. Use when the user shares a GG Omaha tournament hand history (often with a payout screenshot) and asks to solve it with ICM, rate their play, compare to GTO, build a dashboard, or host the solutions on the site.
---

# PLO5 ICM session review

End to end: hand history → one ICM spot per hand → all-streets CFR solve → replay the real line →
dollar value of every hero option → private dashboard (Artifact) → optional public spot library.
Built 2026-10-07/08 for the GG "PLO-5 Classic $10" session; every piece is in this repo.

## Before starting: confirm with the user

Say what is possible and what is not, then wait for a go-ahead (the user asks "can you do that?" first):

- Preflop + postflop are both solved (the solver plays to the river); bets are **pot-size only**, so
  their bet sizing is not judged.
- Players left at each hand and the other tables' stacks are **not in the hand history**: they are
  estimated (linear from `--first-left` to `--finish`, rest of the chips spread evenly).
- Hands are grouped (1,000 preflop buckets by HU and 3-way equity; postflop strength / flush draw /
  straight outs), so values use exact cards but the solver's mix is its bucket's.
- **Six-handed spots with 60bb+ stacks are skipped** ("too deep": trees over 40M strategy rows cannot
  be solved in minutes). Agree this up front.
- Time: about 6–10 minutes per solve, ~70 solves for a 130-hand session → **a night**. Give a time,
  and say the dashboard comes the next morning. Don't promise sooner.

## Inputs to collect

| Input | Where it comes from |
|---|---|
| Hand history | GG export `GG<date> - <tournament>.txt` (Desktop) |
| Payouts 1st..last paid | lobby "Prize Pool" screenshot |
| Entries | lobby "Players Left x / entries" (re-entries count) |
| Finish place | lobby or the user ("Finished 11") |
| Start stack | first hand's stacks (usually 10,000); check `entries × start = avg × left` |
| `first-left` | players left at the first hand: estimate (late registration) |

## Run it

```sh
# 1. PLO5 preflop table (once per machine; ~30 min; tmp/plo5/tables.npz)
.venv/bin/python -m plo_premium_proof.plo5 build

# 2. Size check (prints every solve, its tree rows and minutes, and the total hours)
.venv/bin/python -m plo_premium_proof.review plan --hh "<hh>" --payouts 113.80,93.78,... \
    --entries 57 --finish 11 --first-left 45 --out tmp/plo5/sessions/<tag>/review

# 3. Everything else, unattended and resumable (solves -> values -> dashboard.html)
nohup scripts/plo5_icm_pipeline.sh "<hh>" <tag> 113.80,93.78,... 57 11 45 10000 >/dev/null 2>&1 &
tail -f tmp/plo5/sessions/<tag>/pipeline.log      # "ALL DONE <tag>" at the end
```

Then publish `tmp/plo5/sessions/<tag>/dashboard.html` with the Artifact tool (private by default;
load `artifact-design` first). Before publishing, sanity-check the top mistakes: a rating whose solver
mix is an even 33/33/33 is an untouched bucket; the page already treats those and every hand from a
`thin` solve as "Low confidence" and leaves them out of the totals.

## Publish the spots on the site (only when the user asks)

```sh
.venv/bin/python -m plo_premium_proof.plo5_web --out tmp/plo5/web --review tmp/plo5/sessions/<tag>/review \
    --tag <tag> --entries 57 --payouts 113.80,93.78,...
```

- Publish **solid and fair** solves only; leave `thin` out. Merge the new rows into
  `public/static/plo5-spots.json` (the library index, in git).
- Upload `spot-*.json` (of the published rows) and `plo5-classes.json` to R2 `tamkwai/plo5/v1/`
  (`aws s3 sync … --content-type application/json`, R2 keys in `.env`); `vercel.json` already rewrites
  `/static/plo5/v1/:file` to `data.tamkwai.com/plo5/v1/:file`, and `scripts/web/server.py` serves
  `tmp/plo5/web` locally.
- Only solver output goes public: no hand history, hole cards, results or player names. The review
  dashboard stays a private Artifact.
- Deploy the site from a clean `git archive HEAD` copy (see the web-deploy memory); never mention
  hosting or machine details on the page.

## Files

| File | Role |
|---|---|
| `plo_premium_proof/plo5.py` | PLO5 classes (134,459), MC equities, 40×25 = 1,000 buckets, `Plo5Tables` |
| `plo_premium_proof/hh.py` | GG Omaha tournament parser (preflop order UTG…BB, bb stacks, actions); `session_nets` from stack deltas (GG omits returned uncalled bets) |
| `plo_premium_proof/review.py` | spots (`FinalTableSpec` + crowd ICM), jobs (voluntary hands alone, fold-only hands grouped by table/level/size), budgets, solve, replay, `evaluate` |
| `plo_premium_proof/review_ev.py` | numba kernel: option values by reach-weighted deals with common random numbers |
| `scripts/plo5_dashboard.py` + `.html` | the review page (tamkwai CI, both themes) |
| `scripts/plo5_icm_pipeline.sh` | supervisor: solve → evaluate → dashboard |
| `plo_premium_proof/plo5_web.py`, `public/plo5.html` | public spot library + explorer |
| `tests/test_plo_premium_proof/test_plo5.py` | parser, five-card showdown, bucket split |

The kernels take the hole-card count from `len(bucket_of)` (270,725 → PLO4, 2,598,960 → PLO5), so the
same solver runs both games; `public/static/plo-explorer.js` reads 4- or 5-card class lists.

## Gotchas (each cost hours the first time)

- **Numba cache**: after editing any kernel, delete `plo_premium_proof/**/*.nbi|*.nbc` and
  `plo_chipev_fast/**/*.nbi|*.nbc`; stale caches segfault (exit 139, no traceback). The solver and the
  evaluator must use **different `NUMBA_CACHE_DIR`s**, and the solver runs with `NUMBA_BOUNDSCHECK=1`
  (the plain build segfaulted rarely mid-run). The pipeline script does all of this.
- `review_ev.action_values` needs `boundscheck=True` in its decorator (multi-threaded crash without).
- A job crashing twice is written as `skipped.json` ("the solver crashed twice") — the loop goes on.
- Background shell waiters stop after 2 hours: always launch long work with `nohup`, and check the
  log when the user asks instead of promising an alert.
- Quality = deals / strategy rows: solid ≥ 5, fair ≥ 1, thin < 1. Medium trees (10–40M rows) get
  20 minutes; small ones 4 (fold groups) or 8 minutes.
- `effective_deals` per decision is the importance-sampling ESS; values below ~1,000 are noisy.
