"""Risk premium (bubble factor) map for the two payout files, with chips conserved.

Total chips in play are fixed by the payout file (`chips`). So at a given stage the field
average stack in bb, A = total_chips / (bb_size * players_left), is NOT free: it is set by
the blind level. Everything not at the table goes in the ICM crowd at
  crowd_stack = (players_left * A - sum(table stacks)) / crowd.

Harville ICM is scale invariant, so the chart depends on (players_left, ladder, stack ratios)
and on hero's stack in bb only through the betting. That leaves A as the one extra axis.

Bubble factor, hero h vs opponent o, all-in for x = min(stacks):
  BF = (ICM(h) - ICM(h - x)) / (ICM(h + x) - ICM(h)).   BF = 1 is chip EV.
"""
from __future__ import annotations
import json
import numpy as np
from pushfold import icm

ASSETS = "deepstack-swarm/assets/"

def load(fn):
    s = json.load(open(ASSETS + fn))["structures"][0]
    pz = s["prizes"]
    return s["name"], tuple(pz[str(k)] for k in sorted(int(k) for k in pz)), float(s["chips"])

def payouts_for(prizes, players_left, table_stacks, avg_bb, field=()):
    """Chip-conserving Payouts. avg_bb = field average stack in bb at this stage."""
    n = len(table_stacks)
    crowd = players_left - n - len(field)
    paid = min(len(prizes), players_left)
    if crowd < 0:
        raise ValueError(f"players_left {players_left} < table {n}")
    away = players_left * avg_bb - sum(table_stacks) - sum(field)
    cs = away / crowd if crowd else 0.0
    if crowd and cs <= 0:
        raise ValueError(f"table holds more than all chips (avg {avg_bb}bb)")
    return icm.Payouts(prizes=prizes[:paid], field=field, crowd=crowd, crowd_stack=cs), cs

def bfs(table_stacks, P):
    s = np.array(table_stacks, float)
    out = []
    for o in range(1, len(s)):
        x = min(s[0], s[o])
        rows = []
        for d in (0.0, -x, +x):
            r = s.copy(); r[0] += d; r[o] -= d
            rows.append(r)
        v = icm.value(np.array(rows), tuple(s), P)
        now, lose, win = v[0, 0], v[1, 0], v[2, 0]
        out.append((now - lose) / (win - now) if win - now > 1e-12 else float("inf"))
    return out

if __name__ == "__main__":
    # (label, players_left).  A (avg stack bb) swept per stage over a realistic blind-level range.
    STAGES = {
        "mtt_300_players.json": [("late reg 250", 250), ("pre-bubble 60", 60), ("bubble 46", 46),
                                 ("just ITM 44", 44), ("ITM 36", 36), ("ITM 27", 27),
                                 ("ITM 18", 18), ("FT bubble 10", 10), ("FT 9", 9),
                                 ("FT 6", 6), ("FT 3", 3)],
        "mtt_1500_payout.json": [("late reg 1200", 1200), ("pre-bubble 300", 300),
                                 ("bubble 226", 226), ("just ITM 224", 224), ("ITM 150", 150),
                                 ("ITM 90", 90), ("ITM 45", 45), ("ITM 18", 18),
                                 ("FT bubble 10", 10), ("FT 9", 9), ("FT 6", 6), ("FT 3", 3)],
    }
    AVGS = (12.0, 20.0, 30.0, 45.0)
    for fn, stages in STAGES.items():
        name, prizes, chips = load(fn)
        print(f"\n===== {name}: {len(prizes)} paid, {chips:.0f} chips in play")
        print("  BF for hero 15bb at a table of equal 15bb stacks (9-max, then 6-max, then HU),")
        print("  as the field average stack A varies. '-' = stage cannot hold that table/A.")
        for label, left in stages:
            for n in (9, 6, 2):
                if left < n:
                    continue
                st = (15.0,) * n
                cells = []
                for A in AVGS:
                    try:
                        P, cs = payouts_for(prizes, left, st, A)
                        cells.append(f"A={A:>4.0f}(c={cs:>5.1f}): {bfs(st, P)[0]:.3f}")
                    except Exception:
                        cells.append(f"A={A:>4.0f}: ----------")
                print(f"  {label:<15} {left:>5} left  {n}-max  " + "  ".join(cells))

STAGES_LIST_300 = [("late reg 250", 250), ("pre-bubble 60", 60), ("bubble 46", 46),
                   ("just ITM 44", 44), ("ITM 36", 36), ("ITM 27", 27), ("ITM 18", 18),
                   ("FT bubble 10", 10), ("FT 9", 9), ("FT 6", 6), ("FT 3", 3)]
