"""Table of sigma_hand and the per-spot lifetime eps over the Tier 1 grid cells measured.

Reads `grid_sigma*.json` (and `grid_targets_*.json` for the convergence ladder) and prints the
per-cell eps in mICM chips/hand, next to the 0.0006 the grid was solved to.

    PYTHONPATH=. .venv/bin/python deepstack-swarm/workspace/davis/grid_summarize.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIFETIME = 200 * 12 * 365 * 70
Z = 1.64


def load(pat: str) -> list[dict]:
    out = []
    for p in sorted(HERE.glob(pat)):
        d = json.loads(p.read_text())
        for c in d.get("cells", []):
            if "error" not in c:
                c["_file"] = p.name
                out.append(c)
    return out


def main() -> None:
    rows = load("grid_sigma*.json")
    seen = {}
    for c in rows:                      # a cell measured twice: keep the one that solved less
        k = c["cell"]
        if k not in seen or c["strategy"].get("gain", 9) < seen[k]["strategy"].get("gain", 9):
            seen[k] = c
    rows = [seen[k] for k in sorted(seen)]

    hdr = (f"{'cell':<30}{'n':>3}{'stk':>5}{'sigma_max':>10}{'se':>7}{'sigma_min':>10}"
           f"{'eps_max':>9}{'need':>8}{'iters':>7}{'gain':>9}  verdict  source")
    print(hdr)
    print("-" * len(hdr))
    n_under = n_over = 0
    for c in rows:
        s = c["strategy"]
        worst = max(c["per_seat"], key=lambda p: p["sigma"])
        eps = 1e3 * c["eps_max"]
        tgt = 1e3 * float(c["strategy"].get("target", 0.0006))
        verdict = "under" if eps < tgt else "OVER"
        n_under += verdict == "under"
        n_over += verdict == "OVER"
        print(f"{c['cell']:<30}{c['n']:>3}{c['stack']:>5g}{c['sigma_max']:>10.4f}"
              f"{worst['se_sigma']:>7.3f}{c['sigma_min']:>10.4f}{eps:>9.4f}"
              f"{tgt:>8.4f}{s['iters']:>7}{s['gain']:>9.5f}  {verdict:<8} {s['source']}")
    print(f"\n{n_under} cells under-solved (eps below the 0.6 mICM target), "
          f"{n_over} over-solved. 'need' is the target the cell's own eps asks for.")

    print(f"\n{len(rows)} cells. eps_max over all: "
          f"{1e3 * max(c['eps_max'] for c in rows):.4f} mICM/hand "
          f"({max(rows, key=lambda c: c['eps_max'])['cell']}), min "
          f"{1e3 * min(c['eps_max'] for c in rows):.4f} "
          f"({min(rows, key=lambda c: c['eps_max'])['cell']})")
    print(f"the adopted single number is 0.6 mICM/hand; "
          f"{(1e3 * max(c['eps_max'] for c in rows)) / 0.6:.2f}x the smallest-eps cell, "
          f"{(1e3 * min(c['eps_max'] for c in rows)) / 0.6:.2f}x the largest")

    for attr in ("n", "setting", "stage"):
        print(f"\nby {attr}:")
        groups: dict = {}
        for c in rows:
            groups.setdefault(c[attr], []).append(1e3 * c["eps_max"])
        for k in sorted(groups, key=str):
            v = groups[k]
            print(f"  {str(k):<8} n={len(v):<3} eps_max {min(v):.3f}-{max(v):.3f} "
                  f"(median {sorted(v)[len(v) // 2]:.3f})")

    tgt = load("grid_targets_*.json")
    for t in tgt:
        print(f"\nconvergence ladder, {t['cell']} (crowd {t['crowd']}):")
        print(f"  {'iters':>7}{'gain':>10}{'sigma_min':>11}{'sigma_max':>11}{'eps_max':>9}")
        for r in t["ladder"]:
            print(f"  {r['iters']:>7}{r['gain']:>10.6f}{r['sigma_min']:>11.4f}"
                  f"{r['sigma_max']:>11.4f}{1e3 * r['eps_max']:>9.4f}")


if __name__ == "__main__":
    main()
