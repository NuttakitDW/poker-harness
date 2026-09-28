"""Read the lifetime_eps runs and print the tables for the finding."""
from __future__ import annotations

import json
import math
from pathlib import Path

Z = 1.64
HANDS_PER_DAY = 200 * 12
HERE = Path(__file__).resolve().parent
FILES = {"t=0.001 s=1": "lifetime_eps.json", "t=0.003 s=1": "eps-target0.003.json",
         "t=0.0005 s=1": "eps-target0.0005.json", "t=0.001 s=2": "eps-seed2.json"}


def load() -> dict:
    runs = {}
    for key, name in FILES.items():
        path = HERE / name
        if path.exists():
            runs[key] = json.load(open(path))
    return runs


def main() -> None:
    runs = load()
    base = runs["t=0.001 s=1"]
    names = [s["name"] for s in base["spots"]]

    print(f"# sigma per spot, across solver target and simulation seed "
          f"(lifetime {base['lifetime_hands']:,} hands, z={base['z']})\n")
    head = f"{'spot':<28}{'unit':<11}{'n':>2} " + " ".join(f"{k:>13}" for k in runs)
    print(head)
    for i, name in enumerate(names):
        unit = base["spots"][i]["unit"]
        n = base["spots"][i]["n"]
        cells = []
        for key, run in runs.items():
            spot = next(s for s in run["spots"] if s["name"] == name)
            cells.append(f"{spot['sigma_max']:>13.4f}")
        print(f"{name:<28}{unit:<11}{n:>2} " + " ".join(cells))
    print()

    print(f"{'spot':<28}{'niters':>7}{'exploit':>9}{'smax':>8}{'eps(1.64)':>11}{'eps(1.96)':>11}"
          f"{'m-unit':>9}")
    for s in base["spots"]:
        print(f"{s['name']:<28}{s['iterations']:>7}{s['exploitability']:>9.5f}"
              f"{s['sigma_max']:>8.4f}{s['eps_max']:>11.6f}{s['eps_max'] * 1.96 / Z:>11.6f}"
              f"{s['eps_max'] * 1000:>9.4f}")
    print()

    print("# hands of play needed for the per-hand result to separate a strategy with an")
    print("# exploitability of g from exact, N = (z sigma / g)^2, and the years that is at")
    print(f"# {HANDS_PER_DAY:,} hands/day\n")
    print(f"{'spot':<28}{'sigma':>7}" + "".join(f"{g:>14}" for g in (0.01, 0.005, 0.003, 0.001)))
    for s in base["spots"]:
        cells = []
        for g in (0.01, 0.005, 0.003, 0.001):
            n_hands = (Z * s["sigma_max"] / g) ** 2
            cells.append(f"{n_hands / 1e6:>8.1f}M/{n_hands / HANDS_PER_DAY / 365:>4.0f}y")
        print(f"{s['name']:<28}{s['sigma_max']:>7.4f}" + "".join(cells))
    print()

    print("# simulated mean minus auditor EV, in the spot's own unit (the pricing model's")
    print("# error at 2 seats is zero by construction; at 3+ it is the independent-deal")
    print("# opponent model of pushfold/pricer.py)\n")
    print(f"{'spot':<28}" + "".join(f"{'seat ' + str(i):>10}" for i in range(6)))
    for s in base["spots"]:
        diff = [p["mean"] - ev for p, ev in zip(s["per_seat"], s["audit_ev"])]
        print(f"{s['name']:<28}" + "".join(f"{d:>10.4f}" for d in diff))


if __name__ == "__main__":
    main()
