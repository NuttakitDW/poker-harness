# The chart renderer is binary: it would label the Tier 1 min-raise "shove"

`bowling` (PI), 2026-09-28. **Status: verified by code reading + one label dump. No patch applied
(`scripts/` is out of bounds for me); proposed patch below for whoever owns `scripts/`.**

**Claim in one sentence.** The shipped chart pipeline is binary per cell -- one action versus fold --
so fed a Tier 1 solution it renders the 2.2bb open under the name **"shove"**, with no way to
distinguish an open from a jam and no way to show a three-way mix; this is a presentation layer
rewrite, not a legend entry, and it has to land before the Tier 1 chart can ship.

**Game.** Not a poker claim. It is a claim about `scripts/voice/chart_grid.py` and
`scripts/voice/pushfold_chart.py` at commit `b75e315`.

## What the solver emits

```
.venv/bin/python -c "..."   # see reproduction
# labels: ['allin', 'call 12.8', 'call 14', 'call 14.5', 'call 15', 'fold', 'open 2.2']
```

Three distinct actions per unopened node: `fold`, `open 2.2`, `allin`. Note that call labels carry
amounts (`call 12.8`), so any consumer matching exact strings will miss them.

## Why the renderer cannot show this

`chart_grid.py:29` fixes the whole vocabulary at three codes:

```python
ACTION_CODES = {"raise": "R", "call": "C", "fold": "F"}
```

and `tone()` resolves an unknown action to fold:

```python
code = ACTION_CODES.get(action, "F")
```

so none of `allin`, `open 2.2` or `call 12.8` is a key, and **an all-in would be drawn as a fold**.
That path is only safe today because the producer never lets those labels through. The producer is
`pushfold_chart.py:_cells`, and it is binary by construction:

```python
def _cells(frequencies, action: str, order: list[str]) -> tuple[str, dict]:
    code = "C" if action == "call" else "R"      # line 296
    ...
        codes.append(code if p >= 0.5 else "F")  # line 301
```

One `action` per cell, a 0.5 threshold, everything else fold. The display name for that one code is
set at line 352 as `"names": {"raise": "shove"}`.

So for a Tier 1 cell with shares `{fold: 0.55, open 2.2: 0.40, allin: 0.05}`, the pipeline renders
**"shove"** for a hand that min-raises 40% and never shoves. An ICM chart that says shove when the
solver says min-raise is not a rendering nit; it is the wrong instruction, and it is the exact
action the product exists to show above 15bb (`open3bet-design.md` §15).

The mixed-share machinery can carry a three-way mix -- `shade()` already takes
`max(shares.items(), key=...)`, so it picks a dominant action and shades by its share. What is
missing is a fourth code, not a new mechanism.

## Proposed patch (not applied)

1. `chart_grid.py:29` add a jam code, keeping `R` for a non-all-in raise:
   `ACTION_CODES = {"raise": "R", "allin": "J", "call": "C", "fold": "F"}`.
2. Add `"J"` entries to `STYLES`, `SHADES`, `PLAIN` and `LEGEND` (suggested: `J` orange/magenta,
   distinct from the `R` red, and the legend word "all-in" vs "min-raise" rather than "raise").
3. `pushfold_chart.py:_cells` gains an `actions: list[str]` variant that maps the solver labels
   (`fold`, `open <amt>`, `allin`, `call <amt>`) to codes by dominant share instead of a bare 0.5
   threshold, and stops naming the raise "shove" unconditionally.
4. A regression that feeds one real Tier 1 cell through the renderer and asserts a hand that opens
   100% comes out `R`, not `J` and not `F`.

Items 1-2 are backward compatible if `J` is never emitted for the push/fold chart, so the existing
chart is untouched.

## The fix is demonstrated, not just proposed

`tier1chart/render.py` is a working four-code renderer (`F` fold, `R` non-all-in raise, `J` all-in,
`C` call) with an explicit `label_code()` that matches on the leading word -- because call labels
carry amounts (`call 12.8`) -- and deliberately has **no default fallback**, since a silent fallback
to `F` is the bug. Run on a real solved cell:

```
PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bowling/tier1chart/render.py small bubble 2 15
# small-bubble-n2-15bb-left46  seat 0, unopened
# gain 0.000590 ICM chips/hand over 850 iters, target 0.0006, fingerprint fa654842
# labels ('fold', 'open 2.2', 'allin') -> codes ['F', 'R', 'J']
#
# AAR1.0 AKsR1.0 AQsR1.0 AJsR1.0 ATsJ1.0 ...
# AKoR1.0 KKR1.0 KQsJ1.0 KJsJ1.0 KTsJ1.0 ...
# AQoJ1.0 KQoJ1.0 QQR1.0 QJsJ1.0 QTsJ1.0 ...
```

The distinction survives: in this heads-up 15bb bubble spot seat 0 min-raises every pair (AA through
22 all `R`) and jams most of the rest of its range, including `AKs`, `AKo`, `AQs`, `AJo`. Under the
shipped pipeline there is one non-call code, so a cell that opens and a cell that jams come out as
the **same letter**, and that letter's display word is `"shove"` (`pushfold_chart.py:352`) -- so
`AAR1.0` and `ATsJ1.0` both reach the user as "shove". That is the case for the fourth code, made
concrete.

(This output is a rendering demonstration on one cell, not a strategy claim; the grid is mid
re-solve and `small-bubble-n2-15bb-left46` is one of the six cells finished so far.)

## What would change my mind

If the user is content to ship Tier 1 as **jam-or-fold only** (drop the `open 2.2` branch), the
existing renderer is sufficient and this is not a blocker -- but then the chart is a push/fold chart
with a wider jam range and the §15 argument for it disappears. I do not think that is what was
asked for; the open is the point.

## Reproduction

```
cd /Users/nuttakit/project/poker-harness
PYTHONPATH=. .venv/bin/python -c "
import sys; sys.path.insert(0,'deepstack-swarm/workspace/burch/open3bet')
from pushfold.spot import Spot
import floor3
t=floor3.build(Spot(stacks=(15.,)*6), tier1=True)
labs=set()
for nd in t.nodes: labs.update(nd.labels)
print(sorted(labs))"
```
