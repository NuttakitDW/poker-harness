"""Bubble factor as a function of stack depth at 46-left/45-paid: which axis carries the flat?

bowling's question (2026-09-27): the Tier 1 ICM grid shows the re-jam roughly halving at 8bb
when chip EV -> ICM, and barely moving at 30bb. Is that a real property of the payout
structure, or an artifact of `scenarios.payouts` carrying the untouched field as a
single-stack crowd?

Definitions used here (stated because "bubble factor" is used loosely).
  V(S)  = Malmuth-Harville ICM value of a stack, in chips, prizes scaled to the chips in play
          (pushfold/icm.py). At equal stacks V(S) = S exactly, so V is in "chips".
  BF_x(S) = [V(S) - V(S-x)] / [V(S+x) - V(S)]
          = marginal value of a chip lost / marginal value of a chip won, for a swing of x
          chips against one opponent. BF = 1 is chip EV. This is the standard tournament
          bubble factor (risk premium) with chips transferred between hero and one opponent.
  RRA(S) = -S V''(S) / V'(S), the dimensionless relative risk aversion of V at S.

Axes:
  P  payout structure (ladder, 46 left, 45 paid, field size)
  G  betting geometry (sb 0.5 / bb 1 / open 2.2bb are FIXED in bb while the stack varies)
  C  crowd composition (do the players not at the table hold hero's stack, or a fixed average)

Run: PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/bard/bfdepth.py
"""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "deepstack-swarm/workspace/bowling/tier1chart")
import scenarios as S  # noqa: E402

from pushfold import icm  # noqa: E402

ASSETS = "deepstack-swarm/assets/"
LEFT, PAID = 46, 45
N = 6


def value_of(stacks: np.ndarray, fields: tuple[float, ...], crowd: int, crowd_stack: float,
             prizes: tuple[float, ...]) -> np.ndarray:
    """ICM value of each row of table stacks, in chips, given the rest of the field."""
    P = icm.Payouts(prizes=prizes, field=(), crowd=crowd, crowd_stack=crowd_stack)
    stacks = np.atleast_2d(np.asarray(stacks, dtype=float))
    start = tuple(stacks[0])
    return icm.value(stacks, start, P)


def equal_stacks(n: int, s: float) -> np.ndarray:
    return np.array([s] * n)


def bf_transfer(s: float, x: float, n: int = N, crowd_stack: float | None = None,
                crowd: int | None = None, prizes: tuple[float, ...] | None = None) -> float:
    """BF for hero transferring x chips to seat 1, from a table of n equal s-bb stacks."""
    prizes = prizes if prizes is not None else S.prizes("small")
    crowd_stack = s if crowd_stack is None else crowd_stack
    crowd = LEFT - n if crowd is None else crowd
    rows = []
    for d in (0.0, -x, +x):
        r = equal_stacks(n, s)
        r[0] += d
        r[1] -= d
        rows.append(r)
    v = value_of(np.array(rows), (), crowd, crowd_stack, prizes)
    now, lose, win = v[0, 0], v[1, 0], v[2, 0]
    return (now - lose) / (win - now)


def main() -> None:
    prizes = S.prizes("small")
    depths = (5.0, 8.0, 12.0, 15.0, 20.0, 30.0, 50.0, 100.0)

    print("=" * 78)
    print("A. Payout axis, crowd pinned to hero's stack (scenarios.payouts)")
    print("=" * 78)
    print(f"   {N}-max table, {LEFT} left, {PAID} paid, crowd {LEFT - N} at hero's stack.")
    print("   BF_allin = full-stack transfer vs one table seat; BF_3.7 = a 3.7bb swing.")
    print(f"   {'stack':>7} {'V/S':>10} {'BF_allin':>14} {'BF_3.7bb':>12} {'RRA':>10}")
    for s in depths:
        bf_all = bf_transfer(s, s)
        bf_small = bf_transfer(s, 3.7)
        # RRA by central difference on the hero seat, crowd pinned to hero's stack
        h = s * 1e-3
        rows = []
        for d in (-2 * h, -h, 0.0, h, 2 * h):
            r = equal_stacks(N, s)
            r[0] += d
            rows.append(r)
        v = value_of(np.array(rows), (), LEFT - N, s, prizes)[:, 0]
        vp = (-v[4] + 8 * v[3] - 8 * v[1] + v[0]) / (12 * h)
        vpp = (-v[4] + 16 * v[3] - 30 * v[2] + 16 * v[1] - v[0]) / (12 * h * h)
        rra = -s * vpp / vp
        v0 = value_of(equal_stacks(N, s), (), LEFT - N, s, prizes)[0, 0]
        print(f"   {s:>7.1f} {v0 / s:>10.6f} {bf_all:>14.9f} {bf_small:>12.6f} {rra:>10.6f}")

    print()
    print("=" * 78)
    print("B. Same payout axis, field-average held fixed (chip-conserving, my")
    print("   icm_geometry.payouts_for convention): hero/table stack S, crowd at A bb.")
    print("=" * 78)
    for A in (12.0, 20.0, 30.0):
        print(f"   field average A = {A:.0f}bb")
        print(f"   {'stack':>7} {'BF_allin':>12} {'BF_3.7bb':>12}")
        for s in (5.0, 8.0, 12.0, 15.0, 20.0, 30.0, 50.0):
            try:
                print(f"   {s:>7.1f} {bf_transfer(s, s, crowd_stack=A):>12.6f} "
                      f"{bf_transfer(s, 3.7, crowd_stack=A):>12.6f}")
            except Exception as e:  # noqa: BLE001
                print(f"   {s:>7.1f}  {type(e).__name__}: {e}")

    print()
    print("=" * 78)
    print("C. Geometry axis: the re-jam node, exactly.")
    print("=" * 78)
    print("   BB at S faces an open to 2.2. SB 0.5, BB 1 posted, others S, crowd at S,")
    print("   46 left / 45 paid.  Options at the BB node:")
    print("     fold          -> BB S-1")
    print("     jam, all fold -> BB S+2.7 (wins SB 0.5 + open 2.2)")
    print("     jam, opener calls -> winner takes 2S+0.5, loser 0")
    print("   p = BB equity when called, f = fold equity. Solve for break-even p vs fold,")
    print("   under chip EV (p_cev) and under ICM (p_icm).")
    print()
    hdr = f"   {'f':>5} | " + " | ".join(f"{'S=' + str(int(s)) + 'bb':>21}" for s in depths)
    print(hdr)
    print("   " + "-" * (len(hdr) - 3))
    for f in (0.3, 0.5, 0.7):
        row_c, row_i, row_p = [], [], []
        for s in depths:
            st = equal_stacks(N, s)
            st[1] = s - 0.5  # SB, folds
            fold = st.copy(); fold[0] = s - 1
            taken = st.copy(); taken[0] = s + 2.7; taken[1] = s - 2.2
            won = st.copy(); won[0] = 2 * s + 0.5; won[1] = 0.0
            lost = st.copy(); lost[0] = 0.0; lost[1] = 2 * s + 0.5
            v = value_of(np.array([fold, taken, won, lost]), (), LEFT - N, s, prizes)[:, 0]
            # jam value = f*d_t + (1-f)*(p*d_w + (1-p)*d_l); break even against fold = v_fold
            for tag, (d_f, d_t, d_w, d_l) in (
                    ("cev", (fold[0] - s, taken[0] - s, won[0] - s, lost[0] - s)),
                    ("icm", (0.0, v[1] - v[0], v[2] - v[0], v[3] - v[0]))):
                p_star = (d_f - f * d_t - (1 - f) * d_l) / ((1 - f) * (d_w - d_l))
                (row_c if tag == "cev" else row_i).append(p_star)
            row_p.append(row_i[-1] - row_c[-1])
        print(f"   {f:>5.2f} | " + " | ".join(f"{x * 100:>20.2f}%" for x in row_c)
              + "   <- p* chip EV")
        print(f"   {'':>5} | " + " | ".join(f"{x * 100:>20.2f}%" for x in row_i)
              + "   <- p* ICM")
        print(f"   {'':>5} | " + " | ".join(f"{x * 100:>20.2f}" for x in row_p)
              + "   <- p_icm - p_cev, equity points")
        print()


if __name__ == "__main__":
    main()
