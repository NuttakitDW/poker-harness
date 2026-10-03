"""Tables from the sizing experiment's summary.json: value per size, seed noise, frequencies.

Values are in the solver's units: chip EV arms in bb won, ICM arms in prize equity expressed
in chips (prizes scaled to all chips in play), so 1 unit = (prize pool / total chips) dollars.

    .venv/bin/python research/plo_sizing/report.py tmp/plo_sizing/summary.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import warnings

import numpy as np

warnings.filterwarnings("ignore", "All-NaN", RuntimeWarning)

SEATS = ("UTG", "HJ", "CO", "BTN", "SB")
DOLLARS_PER_UNIT = 8602 / (60 * 30)   # Monster Stack pool over 60 players x 30bb


def open_name(x: float) -> str:
    return "pot" if x == 0 else f"{x:g}x"


def collect(summary: dict) -> dict:
    """(chip_ev, open_x, three_f) -> list of per-seed value dicts."""
    arms = defaultdict(list)
    for arm in summary.values():
        arms[(arm["chip_ev"], arm["open_x"], arm["three_f"])].append(arm)
    return arms


def table(arms: dict, chip_ev: bool, three_f: float, key: str, names: list[str]) -> list[str]:
    opens = sorted({o for (c, o, f) in arms if c == chip_ev and f == three_f}, key=lambda o: (o == 0, o))
    if not opens:
        return ["(not run yet)"]
    lines = [f"| {key} | " + " | ".join(open_name(o) for o in opens) + " | seed gap |", "|---" * (len(opens) + 2) + "|"]
    for name in names:
        cells, gaps = [], []
        means = {}
        for o in opens:
            runs = [r["values"][key][name]["value"] for r in arms[(chip_ev, o, three_f)] if name in r["values"][key]]
            means[o] = float(np.mean(runs))
            gaps.append(abs(runs[0] - runs[1]) if len(runs) > 1 else float("nan"))
        best = max(means, key=means.get)
        for o in opens:
            mark = "**" if o == best else ""
            cells.append(f"{mark}{means[o] - means[0] if 0 in means else means[o]:+.3f}{mark}")
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {np.nanmax(gaps):.3f} |")
    return lines


def frequencies(arms: dict, chip_ev: bool, three_f: float) -> list[str]:
    opens = sorted({o for (c, o, f) in arms if c == chip_ev and f == three_f}, key=lambda o: (o == 0, o))
    if not opens:
        return ["(not run yet)"]
    lines = ["| raise % first in | " + " | ".join(open_name(o) for o in opens) + " |", "|---" * (len(opens) + 1) + "|"]
    for seat in SEATS:
        cells = []
        for o in opens:
            freq = [r["values"]["first_in"][seat]["frequency"] for r in arms[(chip_ev, o, three_f)]]
            raise_share = np.mean([f[2] if len(f) > 2 else 0.0 for f in freq])
            limp_share = np.mean([f[1] for f in freq])
            cells.append(f"{raise_share:.0%} (limp {limp_share:.0%})")
        lines.append(f"| {seat} | " + " | ".join(cells) + " |")
    return lines


def three_bets(arms: dict) -> list[str]:
    icm = {(o, f): runs for (c, o, f), runs in arms.items() if not c}
    opens = {o for (o, f) in icm if f != 1.0}
    if not opens:
        return ["(no 3-bet arms yet)"]
    best_open = opens.pop()
    fractions = sorted(f for (o, f) in icm if o == best_open)
    pairs = list(icm[(best_open, 1.0)][0]["values"]["facing_open"])
    lines = [f"Open size {open_name(best_open)}; value of the player facing one open, relative to a pot 3-bet",
             "", "| opener>defender | " + " | ".join("pot" if f >= 1 else f"{f:g} pot" for f in fractions)
             + " | seed gap |", "|---" * (len(fractions) + 2) + "|"]
    for pair in pairs:
        means, gaps = {}, []
        for f in fractions:
            runs = [r["values"]["facing_open"][pair]["value"] for r in icm[(best_open, f)]]
            means[f] = float(np.mean(runs))
            gaps.append(abs(runs[0] - runs[1]) if len(runs) > 1 else float("nan"))
        best = max(means, key=means.get)
        cells = [f"{'**' if f == best else ''}{means[f] - means[1.0]:+.3f}{'**' if f == best else ''}" for f in fractions]
        lines.append(f"| {pair} | " + " | ".join(cells) + f" | {np.nanmax(gaps):.3f} |")
    return lines


def main() -> int:
    summary = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else "tmp/plo_sizing/summary.json").read_text())
    arms = collect(summary)
    out = ["## Open size: first-in value relative to a pot open (ICM, units = chips of prize equity)", ""]
    out += table(arms, False, 1.0, "first_in", list(SEATS))
    out += ["", f"1 unit = ${DOLLARS_PER_UNIT:.2f} of prize equity", "", "## Same, chip EV control (bb)", ""]
    out += table(arms, True, 1.0, "first_in", list(SEATS))
    out += ["", "## How often each seat raises first in (ICM)", ""] + frequencies(arms, False, 1.0)
    out += ["", "## 3-bet size", ""] + three_bets(arms)
    print("\n".join(out))
    return 0


if __name__ == "__main__" and "--stacks" not in sys.argv:
    sys.exit(main())


def stack_tables(summary: dict) -> list[str]:
    """Uneven-stack runs (``--table``): the named opener's first-in value and frequencies by size."""
    by_table = defaultdict(lambda: defaultdict(list))
    for arm in summary.values():
        if arm.get("table"):
            by_table[arm["table"]][arm["open_x"]].append(arm)
    out = []
    for name, sizes in by_table.items():
        opener = "UTG" if "UTG" in name else "BTN"
        stacks = next(iter(sizes.values()))[0]["stacks"]
        opens = sorted(sizes, key=lambda o: (o == 0, o))
        base = np.mean([r["values"]["first_in"][opener]["value"] for r in sizes.get(0.0, [])]) if 0.0 in sizes else 0
        out += [f"### {name}  (stacks {' / '.join(f'{x:g}' for x in stacks)}; opener {opener})", "",
                "| open | value vs pot | seed gap | raise | limp | fold | defenders 3-bet / call |", "|---" * 7 + "|"]
        for o in opens:
            runs = sizes[o]
            values = [r["values"]["first_in"][opener]["value"] for r in runs]
            freq = np.mean([r["values"]["first_in"][opener]["frequency"] for r in runs], axis=0)
            facing = [v for r in runs for k, v in r["values"]["facing_open"].items() if k.startswith(opener + ">")]
            three = np.mean([f["frequency"][2] for f in facing if len(f["frequency"]) > 2]) if facing else float("nan")
            call = np.mean([f["frequency"][1] for f in facing]) if facing else float("nan")
            gap = abs(values[0] - values[1]) if len(values) > 1 else float("nan")
            out.append(f"| {open_name(o)} | {np.mean(values) - base:+.3f} | {gap:.3f} | {freq[2]:.0%} | {freq[1]:.0%} | "
                       f"{freq[0]:.0%} | {three:.0%} / {call:.0%} |")
        out.append("")
    return out or ["(no uneven-stack runs)"]


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[2] == "--stacks":
    print("\n".join(stack_tables(json.loads(Path(sys.argv[1]).read_text()))))
