"""Build the private PLO5 session review page from the review solves (plo_premium_proof.review).

    .venv/bin/python scripts/plo5_dashboard.py --hh <file> --out <page.html> --review tmp/plo5/review \
        --title "PLO-5 Classic $10" --entries 57 --finish 11 --payouts 113.80,93.78,...

Reads tmp/plo5/review/*/review_ev.json (option values per hero decision) and the hand history, and
writes one self-contained HTML page: session summary, stack graph, leaks by street and position,
the costliest decisions, and every hand with the solver's mix and the value of each option.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plo_equity.cards import card_text  # noqa: E402
from plo_premium_proof.finaltable import SEAT_NAMES  # noqa: E402
from plo_premium_proof.hh import parse_file, session_nets  # noqa: E402

REVIEW = ROOT / "tmp" / "plo5" / "review"
STREETS = ("Preflop", "Flop", "Turn", "River")


def _label(action: str, to_call: float) -> str:
    if action == "pot":
        return "Bet pot" if to_call <= 0 else "Raise pot"
    return action.capitalize()


def collect(hh: Path, review: Path = REVIEW, title: str = "PLO-5 Classic $10", entries: int = 57, finish: int = 11,
            payouts: tuple[float, ...] = (113.80, 93.78, 77.31, 63.73, 52.53, 43.30, 35.70, 24.26, 19.99)) -> dict:
    hands = parse_file(hh)
    nets = session_nets(hands)
    rated: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for path in sorted(review.glob("*/skipped.json")):
        info = json.loads(path.read_text())
        for hand_id in info["job"]["hands"]:
            skipped[hand_id] = info["reason"]
    for path in sorted(review.glob("*/review_ev.json")):
        job = json.loads((path.parent / "review.json").read_text())
        data = json.loads(path.read_text())
        for hand_id, review in data["hands"].items():
            chart_file = path.parent / "chart.json"
            chart = json.loads(chart_file.read_text()).get(hand_id, []) if chart_file.exists() else []
            rated[hand_id] = {"review": review, "chart": chart, "job": job["job"]["kind"], "spec": job["spec"],
                              "left": job["players_left"], "meta": job["meta"]}
    rows = []
    for hand, net in zip(hands, nets):
        n = len(hand.players)
        names = SEAT_NAMES.get(n, tuple(f"S{i}" for i in range(n)))
        entry = {"id": hand.hand_id, "time": hand.time.strftime("%H:%M"), "level": hand.level,
                 "blinds": f"{hand.sb:,}/{hand.bb:,} ({hand.ante:,})", "players": n,
                 "position": names[hand.hero], "cards": card_text(hand.hero_cards), "board": card_text(hand.board),
                 "stack_bb": round(hand.stacks_bb[hand.hero], 1), "chips": hand.chips[hand.hero], "net": net,
                 "line": [{"street": a.street, "who": names[hand.players.index(a.player)] if a.player in hand.players
                           else a.player, "hero": a.player == "Hero", "kind": a.kind,
                           "bb": round(a.amount / hand.bb, 1), "all_in": a.all_in} for a in hand.actions],
                 "decisions": [], "rated": hand.hand_id in rated, "skipped": skipped.get(hand.hand_id)}
        if hand.hand_id in rated:
            r = rated[hand.hand_id]
            entry.update(solve=r["job"], left=r["left"], note=r["review"].get("note"),
                         quality=r["meta"].get("quality"),
                         effective=min((d.get("effective_deals") or 0) for d in r["review"]["decisions"])
                         if r["review"]["decisions"] else None)
            for index, d in enumerate(r["review"]["decisions"]):
                if d.get("values") is None:
                    continue
                chart = r["chart"][index] if index < len(r["chart"]) else None
                labels = [_label(a, d["to_call_bb"]) for a in d["legal"]]
                best = max(range(len(labels)), key=lambda i: d["values"][i])
                entry["decisions"].append({
                    "street": d["street"], "board": d["board"], "pot": d["pot_bb"], "to_call": d["to_call_bb"],
                    "options": labels, "mix": d["mix"], "values": d["values"], "se": d["value_se"],
                    "took": d["slot"], "best": best, "loss": d["loss"], "mix_loss": d["mix_loss"],
                    "real": d["real"], "real_bb": round(d["real_amount"] / hand.bb, 1), "all_in": d["all_in"],
                    "chart": chart})
        rows.append(entry)
    return {"title": title, "date": hands[0].time.strftime("%Y-%m-%d"),
            "start": hands[0].time.strftime("%H:%M"), "end": hands[-1].time.strftime("%H:%M"),
            "entries": entries, "finish": finish, "paid": len(payouts), "payouts": list(payouts), "hands": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hh", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--title", default="PLO-5 Classic $10")
    parser.add_argument("--entries", type=int, default=57)
    parser.add_argument("--finish", type=int, default=11)
    parser.add_argument("--payouts", default="113.80,93.78,77.31,63.73,52.53,43.30,35.70,24.26,19.99")
    parser.add_argument("--bullets", type=int, default=1, help="entries the hero bought (1 + re-entries)")
    parser.add_argument("--previous", type=Path, help="session_grades.py JSON of the last session, to show the change")
    args = parser.parse_args()
    data = collect(args.hh, args.review, args.title, args.entries, args.finish,
                   tuple(float(x) for x in args.payouts.split(",")))
    data["bullets"] = args.bullets
    if args.previous:
        prev = json.loads(args.previous.read_text())
        data["previous"] = {"date": prev.get("date", args.previous.parent.name), "score": prev["score"], "share": prev["share"]}
    template = (Path(__file__).parent / "plo5_dashboard.html").read_text()
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    template = template.replace("<title>PLO-5 Classic Review</title>", f"<title>PLO5 Review {data['date']}</title>")
    args.out.write_text(template.replace("/*DATA*/null", payload))
    rated = sum(1 for h in data["hands"] if h["rated"])
    print(f"{args.out}: {len(data['hands'])} hands, {rated} rated, "
          f"{sum(len(h['decisions']) for h in data['hands'])} decisions")


if __name__ == "__main__":
    main()
