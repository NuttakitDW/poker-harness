"""Personal progress page: every reviewed PLO5 session scored the same way, side by side and over time.

    .venv/bin/python scripts/plo5_progress.py --sessions tmp/plo5/sessions.json --out <page.html>

sessions.json lists each session: {"tag", "title", "date", "hh", "review", "entries", "finish", "bullets",
"buy_in", "payouts": [...], "dashboard": "<artifact url>"}. Decisions are rated with the dashboard's
rules (plo5_dashboard.html): trusted = the solve had data for the hand group and was not thin; a
mistake = an action the solver uses under 10% of the time, costing more than the sampling noise.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from plo5_dashboard import collect  # noqa: E402

STREETS = ("Preflop", "Flop", "Turn", "River")
POSITIONS = ("UTG", "HJ", "CO", "BTN", "SB", "BB")


def severity(d: dict) -> str:
    noise = math.hypot(d["se"][d["best"]], d["se"][d["took"]])
    if d["loss"] <= max(0.02, 2 * noise):
        return "fine"
    if d["mix"][d["took"]] >= 0.10:
        return "unclear"
    return "costly" if d["loss"] >= 0.2 else "leak" if d["loss"] >= 0.05 else "fine"


def trusted(hand: dict, d: dict) -> bool:
    n = len(d["mix"])
    even = max(abs(m - 1 / n) for m in d["mix"]) < 0.02
    return not even and hand.get("quality") != "thin"


def score(session: dict) -> dict:
    data = collect(Path(session["hh"]), Path(session["review"]), session["title"], session["entries"],
                   session["finish"], tuple(session["payouts"]))
    buy_in = session.get("buy_in", 10.0)
    rows = [(h, d) for h in data["hands"] for d in h["decisions"] if trusted(h, d)]
    lost = [d["loss"] if severity(d) in ("costly", "leak") else 0.0 for _, d in rows]
    by = lambda key, names: {  # noqa: E731
        name: {"decisions": sum(1 for (h, d) in rows if key(h, d) == name),
               "lost_bi": round(sum(l for (h, d), l in zip(rows, lost) if key(h, d) == name) / buy_in, 3)}
        for name in names}
    n = max(len(rows), 1)
    return {
        "tag": session["tag"], "title": session["title"], "date": session["date"],
        "entries": session["entries"], "finish": session["finish"], "bullets": session.get("bullets", 1),
        "hands": len(data["hands"]), "rated": sum(1 for h in data["hands"] if h["rated"]),
        "decisions": len(rows),
        "lost_bi": round(sum(lost) / buy_in, 3),
        "lost_per_100": round(100 * sum(lost) / buy_in / n, 3),
        "match": round(sum(1 for _, d in rows if d["mix"][d["took"]] >= 0.25) / n, 3),
        "costly_per_100": round(100 * sum(1 for _, d in rows if severity(d) == "costly") / n, 1),
        "mistakes": sum(1 for _, d in rows if severity(d) in ("costly", "leak")),
        "streets": by(lambda h, d: STREETS[d["street"]], STREETS),
        "positions": by(lambda h, d: h["position"], POSITIONS),
        "worst": sorted(({"time": h["time"], "position": h["position"], "street": STREETS[d["street"]],
                          "cards": h["cards"], "board": d["board"], "took": d["options"][d["took"]],
                          "best": d["options"][d["best"]], "lost_bi": round(d["loss"] / buy_in, 3)}
                         for (h, d), l in zip(rows, lost) if l > 0), key=lambda w: -w["lost_bi"])[:5],
        "dashboard": session.get("dashboard"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sessions = json.loads(args.sessions.read_text())
    scored = sorted((score(s) for s in sessions), key=lambda s: s["date"])
    template = (Path(__file__).parent / "plo5_progress.html").read_text()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(template.replace("/*DATA*/null", json.dumps(scored, separators=(",", ":")).replace("</", "<\\/")))
    for s in scored:
        print(s["date"], s["title"], f"{s['decisions']} decisions, {s['lost_per_100']} buy-ins lost per 100, "
              f"match {s['match']:.0%}")


if __name__ == "__main__":
    main()
