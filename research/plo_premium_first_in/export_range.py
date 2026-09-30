"""Export the solved first-in range for every hand class: CSV plus compact JSON for the viewer.

Usage: python export_range.py --stack 40  ->  <generated>/range_first_in.csv and range_first_in.json
Frequencies are the seed-averaged mix of the hand's preflop bucket (hands in one bucket share it).
"""

from __future__ import annotations

import csv
import json

from study import from_args

SEATS = ("UTG", "HJ", "CO", "BTN", "SB")
RANKS = "23456789TJQKA"
SUIT_SYMBOL = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}


def pretty(hand: str) -> str:
    """Cards high to low with suit symbols, e.g. KcKdAcAd -> A♣A♦K♣K♦."""
    cards = [hand[i:i + 2] for i in range(0, 8, 2)]
    cards.sort(key=lambda c: (RANKS.index(c[0]), c[1]), reverse=True)
    return "".join(c[0] + SUIT_SYMBOL[c[1]] for c in cards)


def main() -> None:
    study = from_args(__doc__)
    rows = json.loads((study.generated / "class_actions.json").read_text())
    rows.sort(key=lambda r: (-(1 - r["UTG"]["fold"]), -(1 - r["BTN"]["fold"]), r["ranks"]))
    with (study.generated / "range_first_in.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["hand", "cards", "ranks", "suits", "combos", "hwang_tier", "hwang_form",
                         *[f"{seat}_{action}" for seat in SEATS for action in ("fold", "limp", "raise")]])
        for r in rows:
            writer.writerow([r["hand"], pretty(r["hand"]), r["ranks"], r["shape"], r["combos"], r["tier"], r["form"],
                             *[f"{100 * r[seat][a]:.1f}" for seat in SEATS for a in ("fold", "limp", "open")]])
    compact = {
        "seats": SEATS,
        "stack": study.stack,
        "ante": study.ante,
        # per row: cards, ranks, suits, combos, tier initial, [limp%, raise%] x 5 seats (fold is the rest)
        "rows": [[pretty(r["hand"]), r["ranks"], r["shape"], r["combos"], r["tier"][0],
                  *[x for seat in SEATS for x in (round(100 * r[seat]["limp"]), round(100 * r[seat]["open"]))]]
                 for r in rows],
    }
    (study.generated / "range_first_in.json").write_text(json.dumps(compact, separators=(",", ":"),
                                                                    ensure_ascii=False))
    print(f"exported {len(rows)} classes -> {study.generated / 'range_first_in.csv'}")


if __name__ == "__main__":
    main()
