"""Per-hand EV audit rows at 20bb, with features and population weights.

Premium is audited exhaustively (weight = class size); Speculative, Marginal and Trash
are audited on 400 uniformly drawn physical hands each (weight = draws scaled so each
tier sums to its true number of combinations). Writes generated/audit_ev.json.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from plo_equity.cards import parse_cards

from archetypes import archetype
from features import features

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[1] / "tmp" / "plo_premium_proof"
OUT = HERE / "generated" / "audit_ev.json"
TIER_COMBOS = {"Premium": 14868, "Speculative": 37440, "Marginal": 53912, "Trash": 164505}
SOURCES = {
    "Premium": RUNS / "full20-report-seed-1.json",
    "Speculative": RUNS / "tiers" / "full20-Speculative.json",
    "Marginal": RUNS / "tiers" / "full20-Marginal.json",
    "Trash": RUNS / "tiers" / "full20-Trash.json",
}


def main() -> None:
    rows = []
    for tier, path in SOURCES.items():
        audited = json.loads(path.read_text())["premium_rows"]
        mass = collections.Counter()
        for row in audited:
            mass[row["position"]] += row.get("sample_weight", row["combos"])
        for row in audited:
            cards = tuple(parse_cards(row["hand"]))
            feats = features(cards)
            raw = row.get("sample_weight", row["combos"])
            rows.append({
                "hand": row["hand"], "seat": row["position"], "tier": tier, "form": row["form"],
                "weight": raw * TIER_COMBOS[tier] / mass[row["position"]],
                "ev": {"fold": row["ev"]["fold"], "limp": row["ev"]["limp"], "open": row["ev"]["pot_open"]},
                "se": {"limp": row["se"]["limp"], "open": row["se"]["pot_open"]},
                "solver": {"fold": row["solver_frequency"]["fold"], "limp": row["solver_frequency"]["limp"],
                           "open": row["solver_frequency"]["pot_open"]},
                "archetype": archetype(feats), **feats,
            })
    OUT.write_text(json.dumps(rows))
    print(f"wrote {len(rows)} hand-seat rows -> {OUT}")


if __name__ == "__main__":
    main()
