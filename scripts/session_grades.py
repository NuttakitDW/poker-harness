"""A/B/C grades of a reviewed session: the numbers a session-review video (or write-up) is built from.

    .venv/bin/python scripts/session_grades.py --hh <session.txt> --review <review dir> \
        --entries 57 --finish 11 --payouts 113.80,93.78,... [--out grades.json]

Grades every trusted decision with the review page's rules (plo5_progress.severity / trusted):
  A  solver-approved and an action the solver takes 25%+ of the time
  B  an action the solver takes 10-25%, a small leak, or "unclear" (followed the solver, exact cards disagree)
  C  a costly mistake: under 10% for the solver and over $0.20 of equity
Score = average of A 100, B 60, C 0. Also prints the A-game highlights (biggest pots played right),
every C decision, the small leaks and the split by street and position.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plo5_dashboard import collect  # noqa: E402
from plo5_progress import severity, trusted  # noqa: E402

STREETS = ("Preflop", "Flop", "Turn", "River")


def grade(d: dict) -> str:
    s = severity(d)
    if s == "costly":
        return "C"
    if s in ("leak", "unclear"):
        return "B"
    return "A" if d["mix"][d["took"]] >= 0.25 else "B"


def row(h: dict, d: dict) -> dict:
    return {"time": h["time"], "level": h["level"], "position": h["position"], "players": h["players"],
            "stack_bb": h["stack_bb"], "cards": h["cards"], "street": STREETS[d["street"]], "board": d["board"],
            "pot_bb": d["pot"], "to_call_bb": d["to_call"], "took": d["options"][d["took"]],
            "best": d["options"][d["best"]], "solver_mix": {o: round(m, 2) for o, m in zip(d["options"], d["mix"])},
            "loss": d["loss"], "severity": severity(d)}


def grades(hh: Path, review: Path, entries: int, finish: int, payouts: tuple[float, ...]) -> dict:
    data = collect(hh, review, "", entries, finish, payouts)
    rows = [(h, d) for h in data["hands"] for d in h["decisions"] if trusted(h, d)]
    counts = Counter(grade(d) for _, d in rows)
    n = max(len(rows), 1)
    lost = sum(d["loss"] for _, d in rows if severity(d) in ("costly", "leak"))
    by = lambda key: {k: dict(Counter(grade(d) for h, d in rows if key(h, d) == k))  # noqa: E731
                      for k in dict.fromkeys(key(h, d) for h, d in rows)}
    return {
        "hands": len(data["hands"]), "entries": entries, "finish": finish, "trusted": len(rows),
        "grades": {g: counts.get(g, 0) for g in "ABC"},
        "share": {g: round(100 * counts.get(g, 0) / n, 1) for g in "ABC"},
        "score": round((100 * counts.get("A", 0) + 60 * counts.get("B", 0)) / n, 1),
        "lost_dollars": round(lost, 2),
        "matched": round(100 * sum(1 for _, d in rows if d["mix"][d["took"]] >= 0.25) / n, 1),
        "unclear": sum(1 for _, d in rows if severity(d) == "unclear"),
        "by_street": by(lambda h, d: STREETS[d["street"]]),
        "by_position": by(lambda h, d: h["position"]),
        "a_highlights": [row(h, d) for h, d in sorted(((h, d) for h, d in rows if grade(d) == "A" and d["street"] > 0),
                                                       key=lambda t: -t[1]["pot"])[:6]],
        "c_game": [row(h, d) for h, d in sorted(((h, d) for h, d in rows if grade(d) == "C"), key=lambda t: -t[1]["loss"])],
        "small_leaks": [row(h, d) for h, d in sorted(((h, d) for h, d in rows if severity(d) == "leak"),
                                                      key=lambda t: -t[1]["loss"])[:8]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hh", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--entries", type=int, required=True)
    parser.add_argument("--finish", type=int, required=True)
    parser.add_argument("--payouts", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = grades(args.hh, args.review, args.entries, args.finish, tuple(float(x) for x in args.payouts.split(",")))
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
