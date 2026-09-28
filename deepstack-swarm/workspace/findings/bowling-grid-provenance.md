# The Tier 1 grid's 41 first cells were not one artifact and could not be reproduced from their own record

`bowling` (PI), 2026-09-28. **Status: measured (git + file times) and fixed (restart under one
fingerprint).** Nothing in `pushfold/` edited. This is a claim about the *record*, not about poker.

**Claim in one sentence.** Every cell JSON carried `"commit": "b75e315"`, but
`deepstack-swarm/workspace/` is untracked by git (`git ls-files deepstack-swarm/workspace/` returns
0 files), so that field pinned only `pushfold/` and the surrounding repo and said nothing about the
solver that produced the numbers; the solver modules were in fact edited *during* the solve window,
so the 41 first cells were not one artifact and the delivered chart could not be re-run from its own
record.

**Game.** NLHE, preflop only, Tier 1 action set (`floor3.build(..., tier1=True)`), cap 3,
`fee = 0`, ICM payouts, equal stacks, sb 0.5 / bb 1, no ante. The claim below is about provenance
and holds for any of those settings.

## Evidence

```
git -C /Users/nuttakit/project/poker-harness ls-files deepstack-swarm/workspace/ | wc -l
# -> 0
```

Solver module mtimes (`stat -f "%Sm %N" -t "%Y-%m-%d %H:%M:%S"`) against the cell write window
22:22-23:10 on 2026-09-27:

| module | mtime | relation to the 22:22-23:10 cell window |
|---|---|---|
| `coach3.py` | 19:41 | before |
| `pricer3.py`, `seqbr3.py` | 20:28 | before |
| `icm_pricer3.py` | 20:46 | before |
| `fasticm3.py` | 22:24 | **inside** |
| `floor3.py` | 23:30 | **after** |
| `solve3.py` | 00:12 (2026-09-28) | **after** |

`solve3.py` at 00:12 is the decisive one: a grid process was still running at that time and had
imported `solve3` at start-up, so the cell it was mid-way through was solved against a version of
`solve3.py` that no longer existed on disk. This was not only a historical gap — it was live when
I found it.

Two consequences:

1. **The record cannot reproduce the artifact.** `b75e315` is true of `pushfold/` and irrelevant to
   the solver. Re-running the grid from the record would silently pick up whatever the workspace
   holds later.
2. **The 41 cells are not a set.** `fasticm3.py` changed 2 minutes into the window, so at minimum
   some cells were audited by one version and some by another. `fasticm3` is the auditor whose
   number the cell *reports* (`final_gain`), so this touches the headline figure, not a
   detail.

## The fix

New `tier1chart/provenance.py`: SHA-256[:12] of the 13 modules on the solve path
(`floor3, pricer3, icm_pricer3, seqbr3, fasticm3, coach3, solve3, scenarios, pushfold/{icm,hands,spot,cashier,oddsmaker}`),
a combined `fingerprint()`, and `snapshot()` which copies the exact files next to the cells.

`grid.py` now writes `code_fingerprint` and the full per-module `code` dict into every cell, calls
`snapshot()` at start-up, and prints a warning listing any cell whose fingerprint differs from the
run's.

**A file hash is not enough: record the build kwargs too.** `burch` pointed out that the FLOP-gap
variant reuses the same `floor3.py` through a kwarg (`behind_cap=1`), so `tier1=True, behind_cap=None`
and `tier1=True, behind_cap=1` have the *same* module digest and would be indistinguishable in the
record. Every cell therefore also carries `build` (the kwargs dict), `cap`, and `stacks`:

```
"build": {"tier1": true}, "cap": 3, "stacks": [8.0, 8.0],
"counts": {"allfold": 1, "uncontested": 3, "showdown": 2, "flop": 0}
```

and a run-level `cells/RUN.json` records the fingerprint, digests, build kwargs, `target`,
`check_every`, `method`, `auditor` and the full 80-cell plan. `counts["flop"]` is also the positive
evidence the leaf-free claim needs: an equal-stack cell showing `flop: 0` demonstrates leaf-freeness
directly rather than by argument.

```
.venv/bin/python deepstack-swarm/workspace/bowling/tier1chart/grid.py
# code fingerprint fa654842  snapshot -> .../tier1chart/cells/code-fa654842
```

Verified in the record:

```
small-bubble-n2-8bb-left46  code_fingerprint fa654842
  floor3 205d0996b284  solve3 6651e736ebe4  fasticm3 6b6d8dde3333  pricer3 ab3e7511cc15
  icm_pricer3 550b3ef215f2  seqbr3 760f67d7bb3e  coach3 631218729ebb  scenarios 5db854a9ffd5
```

The 41 unprovenanced cells were moved to `tier1chart/cells-prev-noprov/` (82 files, 41 json +
41 npz) and the grid restarted from scratch into `cells/`. **Quarantined, not deleted**: they are
still the only record of that work, but they must not be quoted. A partial second run (6 cells,
correct fingerprint but before the `build` kwargs were recorded) is in `tier1chart/cells-run3/` and
is likewise superseded; the only quotable cells are those in `cells/`.

**Cost of the fix.** The grid was restarted twice -- once for the fingerprint, once for the build
kwargs -- but at 6 and 11 cells respectively, so the wasted compute was ~20 minutes against a
~4h run. Cheaper to pay that at the start than to carry a record that cannot answer "which code and
which build produced this number".

## What would change my mind

Evidence that `fasticm3.py`'s 22:24 edit was comment-only would make the *reported exploitability*
of all 41 cells a single version after all; it would not fix the `floor3.py`/`solve3.py` edits, which
change the strategies rather than only the audit. I have not diffed the pre-edit `fasticm3.py`
against the current one and no copy of it exists in the workspace, so I cannot settle that — which
is itself the point of the finding.

A cheaper alternative I considered and rejected: re-audit the old cells with the current
`fasticm3` and keep those whose number is unchanged. That fixes the headline figure but not the
strategies, and it would ship one chart built from two solvers. Re-solving is the only fix that
makes the deliverable one artifact.

## Reproduction

```
git -C /Users/nuttakit/project/poker-harness ls-files deepstack-swarm/workspace/ | wc -l   # 0
.venv/bin/python deepstack-swarm/workspace/bowling/tier1chart/provenance.py                # fa654842
stat -f "%Sm %N" -t "%Y-%m-%d %H:%M:%S" deepstack-swarm/workspace/burch/open3bet/{floor3,solve3,fasticm3}.py
```
