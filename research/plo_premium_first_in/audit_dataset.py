"""Per-hand EV audit rows for one stack depth, with features and population weights.

Usage: python audit_dataset.py --stack 20|100  ->  <generated>/audit_ev.json

Premium is audited exhaustively (weight = class size); Speculative, Marginal and Trash
are audited on 400 uniformly drawn physical hands each (weight = draws scaled so each
tier sums to its true number of combinations).
"""

from __future__ import annotations

import collections
import json

from plo_equity.cards import parse_cards

from archetypes import archetype
from features import features
from study import TIERS, from_args

TIER_COMBOS = {"Premium": 14868, "Speculative": 37440, "Marginal": 53912, "Trash": 164505}


def main() -> None:
    study = from_args(__doc__)
    rows = []
    for tier in TIERS:
        path = study.tier_report(tier)
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
    out = study.generated / "audit_ev.json"
    out.write_text(json.dumps(rows))
    print(f"wrote {len(rows)} hand-seat rows -> {out}")


if __name__ == "__main__":
    main()
