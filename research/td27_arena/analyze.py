"""Measure how strong 2-7 triple draw bots choose to stand pat, break, and discard.

Reads the hands saved by collect.py and writes generated/summary.json, which build_paper.py turns
into the paper's tables and the Thai page quotes.

    .venv/bin/python research/td27_arena/analyze.py
"""

from __future__ import annotations

import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

from collect import CACHE, ELITE_6MAX, ELITE_HU, MIN_HANDS, is_baseline

HERE = Path(__file__).resolve().parent
OUT = HERE / "generated"
RANKS = "23456789TJQKA"
VALUE = {r: i for i, r in enumerate(RANKS, 2)}
STREETS = ("draw1", "draw2", "draw3")
FORMATS = ("HU", "6MAX")
# Made no-pair hands, best first. 75 = 7-5-4-3-2 only; 9, T, J... cover every hand with that top card.
BUCKETS = ("75", "76", "85", "86", "87", "9", "T", "J", "Q", "K", "A")
SECOND_CARD = ("95", "96", "97", "98", "T6", "T7", "T8", "T9", "J6", "J7", "J8", "J9", "JT")
PAIRED_CATEGORIES = {1, 2, 3, 6, 7}


def cards(text: str | None) -> list[str]:
    text = text or ""
    return [text[i:i + 2] for i in range(0, len(text), 2)]


def low_value(hand: list[str]) -> tuple[int, tuple[int, ...]]:
    """Deuce-to-seven value; smaller is better. Category 0 = no pair, no straight, no flush."""
    ranks = sorted((VALUE[c[0]] for c in hand), reverse=True)
    counts = Counter(ranks)
    flush = len({c[1] for c in hand}) == 1
    straight = len(counts) == 5 and ranks[0] - ranks[4] == 4
    shape = tuple(sorted(counts.values(), reverse=True))
    if shape == (1, 1, 1, 1, 1):
        category = 8 if straight and flush else 5 if flush else 4 if straight else 0
    else:
        category = {(2, 1, 1, 1): 1, (2, 2, 1): 2, (3, 1, 1): 3, (3, 2): 6, (4, 1): 7}[shape]
    return category, tuple(sorted(ranks, key=lambda r: (-counts[r], -r)))


def bucket(value: tuple) -> str:
    category, ranks = value
    if category:
        return "pair+" if category in PAIRED_CATEGORIES else "st/fl"
    top = RANKS[ranks[0] - 2]
    return top + RANKS[ranks[1] - 2] if top in "78" else top


def top_two(value: tuple) -> str:
    return RANKS[value[1][0] - 2] + RANKS[value[1][1] - 2]


def elite_for(n_players: int) -> frozenset:
    return ELITE_HU if n_players == 2 else ELITE_6MAX


def parse_hand(hand: dict, samples: set[int]) -> tuple[list[dict], dict | None, tuple[int, int]]:
    """Return (draw decisions, showdown record, (evaluator agrees, checked)) for one hand."""
    names = hand["players"]
    fmt = "HU" if len(names) == 2 else "6MAX"
    elite = elite_for(len(names))
    all_elite = set(names) <= elite
    current, folded, dead = {}, set(), defaultdict(list)
    drawn: dict[str, dict[int, int]] = defaultdict(dict)
    decisions = []
    for e in hand["events"]:
        kind, seat, street = e["kind"], e["player"], e["street"]
        if kind == "initial-cards":
            current[seat] = cards(e["cards"])
        elif kind == "action" and e["action"] == "fold":
            folded.add(seat)
        elif kind == "replacement":
            discarded, new = cards(e["detail"]), cards(e["cards"])
            before = list(current[seat])
            kept = [c for c in before if c not in discarded]
            live = [s for s in current if s not in folded]
            decisions.append({
                "fmt": fmt, "bot": names[seat], "elite": names[seat] in elite, "all_elite": all_elite,
                "street": street, "before": before, "kept": kept, "n": len(discarded),
                "value": low_value(before), "opponents": len(live) - 1,
                "seen": [n for s, n in drawn[street].items() if s != seat],
                "dead": list(dead[seat]),
            })
            drawn[street][seat] = len(discarded)
            dead[seat] += discarded
            current[seat] = kept + new
    number = hand["hand"]["number"]
    live = [s for s in current if s not in folded]
    showdown, check = None, (0, 0)
    if hand["hand"]["showdown"] and len(live) >= 2:
        values = [low_value(current[s]) for s in live]
        best = min(values)
        showdown = {"fmt": fmt, "players": len(live), "values": values, "winner": best,
                    "sample": number in samples, "all_elite": all_elite}
        awarded = {i for i, a in enumerate(hand["hand"]["awardsMilli"]) if a and a > 0}
        mine = {s for s, v in zip(live, values) if v == best}
        check = (int(mine == awarded), 1)
    return decisions, showdown, check


def load() -> tuple[list[dict], list[dict], tuple[int, int], int, int]:
    samples = {int(k): set(v) for k, v in json.loads((CACHE / "samples.json").read_text()).items()}
    decisions, showdowns, agree, checked, n_hands, n_sample = [], [], 0, 0, 0, 0
    for path in sorted((CACHE / "hands").glob("*.json")):
        hand = json.loads(path.read_text())
        is_sample = hand["hand"]["number"] in samples.get(hand["match"], set())
        d, s, (a, c) = parse_hand(hand, samples.get(hand["match"], set()))
        decisions += d
        if s:
            showdowns.append(s)
        agree, checked, n_hands, n_sample = agree + a, checked + c, n_hands + 1, n_sample + is_sample
    return decisions, showdowns, (agree, checked), n_hands, n_sample


def rate(rows: list[dict], test) -> dict:
    hits = sum(1 for r in rows if test(r))
    return {"p": hits / len(rows) if rows else None, "n": len(rows)}


def pat_table(rows: list[dict], key, labels) -> dict:
    groups = defaultdict(list)
    for d in rows:
        if d["value"][0] == 0:
            groups[key(d)].append(d)
    return {lab: rate(groups[lab], lambda d: d["n"] == 0) for lab in labels if groups[lab]}


def ranking(matches: dict) -> dict:
    per_bot = {fmt: defaultdict(lambda: [0.0, 0, 0]) for fmt in FORMATS}
    for match in matches.values():
        info = match["matchInfo"]
        names = info["players"]
        if (info["status"] != "completed" or info["completedHands"] < MIN_HANDS or len(set(names)) < 2
                or any(is_baseline(n) for n in names)):
            continue
        table = per_bot["HU" if len(names) == 2 else "6MAX"]
        for name, milli in zip(names, info["ratePer100Milli"]):
            table[name][0] += milli / 1000 * info["completedHands"]
            table[name][1] += info["completedHands"]
            table[name][2] += 1
    out = {}
    for fmt, table in per_bot.items():
        rows = [{"bot": b, "rate": s / h, "hands": h, "matches": m} for b, (s, h, m) in table.items()]
        out[fmt] = sorted(rows, key=lambda r: -r["rate"])[:12]
    return out, sum(1 for m in matches.values() if m["matchInfo"]["status"] == "completed")


def rule_keep(hand: list[str], k: int) -> set[str] | None:
    """Keep k cards of distinct rank with the lowest ranks; on ties prefer more suits."""
    best = None
    for combo in itertools.combinations(hand, k):
        ranks = [VALUE[c[0]] for c in combo]
        if len(set(ranks)) < k:
            continue
        key = (sorted(ranks, reverse=True), -len({c[1] for c in combo}))
        if best is None or key < best[0]:
            best = (key, combo)
    return {c[0] for c in best[1]} if best else None


def rank_string(cs) -> str:
    return "".join(sorted((c[0] for c in cs), key=lambda r: -VALUE[r]))


def discard_rule(elite: list[dict]) -> dict:
    agree, misses = defaultdict(lambda: [0, 0]), Counter()
    for d in elite:
        k = 5 - d["n"]
        if d["n"] == 0 or k == 0:
            continue
        rule = rule_keep(d["before"], k)
        if rule is None:
            continue
        ok = rule == {c[0] for c in d["kept"]}
        agree[f"{d['fmt']}:{d['n']}"][0] += ok
        agree[f"{d['fmt']}:{d['n']}"][1] += 1
        if not ok:
            misses[(rank_string(d["kept"]), "".join(sorted(rule, key=lambda r: -VALUE[r])))] += 1
    straights = [d for d in elite if d["n"] == 1 and d["value"][0] == 4]
    top_dropped = sum(1 for d in straights if {c[0] for c in d["kept"]} == rule_keep(d["before"], 4))
    misses_in_straights = sum(1 for d in straights if {c[0] for c in d["kept"]} != rule_keep(d["before"], 4))
    return {"agree": {k: {"p": a / n, "n": n} for k, (a, n) in agree.items()},
            "straight_breaks": {"n": len(straights), "top": top_dropped / len(straights),
                                "misses_share": misses_in_straights / max(sum(misses.values()), 1)},
            "misses": [{"bot": b, "rule": r, "count": c} for (b, r), c in misses.most_common(6)]}


def break_outs(d: dict) -> int:
    """Live cards that make an 8-or-better no-pair low after discarding the top card."""
    keep = sorted(d["before"], key=lambda c: VALUE[c[0]])[:4]
    kept = {VALUE[c[0]] for c in keep}
    seen = Counter(c[0] for c in d["before"] + d["dead"])
    outs = 0
    for r in RANKS:
        v = VALUE[r]
        made = kept | {v}
        if v in kept or v > 8 or max(made) - min(made) == 4:
            continue
        outs += 4 - seen[r]
    return outs


def outs_bucket(n: int) -> str:
    return "<=6" if n <= 6 else "7-8" if n <= 8 else "9+"


def dead_outs(d: dict) -> int:
    keep = sorted(d["before"], key=lambda c: VALUE[c[0]])[:4]
    kept = {VALUE[c[0]] for c in keep}
    good = {r for r in RANKS if VALUE[r] <= 8 and VALUE[r] not in kept
            and max(kept | {VALUE[r]}) - min(kept | {VALUE[r]}) != 4}
    return sum(1 for c in d["dead"] if c[0] in good)


def showdown_tables(showdowns: list[dict]) -> dict:
    out = {}
    for fmt in FORMATS:
        rows = [s for s in showdowns if s["fmt"] == fmt and s["sample"] and s["players"] == 2]
        winners = Counter(bucket(s["winner"]) for s in rows)
        cum, dist = 0, {}
        for lab in BUCKETS + ("pair+",):
            cum += winners[lab]
            dist[lab] = {"p": winners[lab] / len(rows), "cum": cum / len(rows)}
        wins = defaultdict(lambda: [0, 0])
        for s in rows:
            for v in s["values"]:
                wins[bucket(v)][0] += v == s["winner"]
                wins[bucket(v)][1] += 1
        out[fmt] = {"n": len(rows), "winner": dist,
                    "win_rate": {lab: {"p": w / n, "n": n} for lab, (w, n) in wins.items()}}
    return out


def kept_top(elite: list[dict]) -> dict:
    out = {}
    for fmt in FORMATS:
        for n in (1, 2, 3):
            rows = [d for d in elite if d["fmt"] == fmt and d["n"] == n]
            tops = Counter(max(VALUE[c[0]] for c in d["kept"]) for d in rows)
            out[f"{fmt}:{n}"] = {"n": len(rows),
                                 "le8": sum(c for v, c in tops.items() if v <= 8) / len(rows),
                                 "nine": tops[9] / len(rows),
                                 "le7": sum(c for v, c in tops.items() if v <= 7) / len(rows)}
    return out


def best_four_choice(elite: list[dict]) -> dict:
    groups = defaultdict(Counter)
    for d in elite:
        if d["fmt"] != "HU" or d["street"] != "draw1":
            continue
        ranks = [VALUE[c[0]] for c in d["before"]]
        lows = sorted({r for r in ranks if r <= 8})
        if len(lows) != 4 or (d["value"][0] == 0 and max(ranks) <= 8):
            continue
        groups[RANKS[lows[-1] - 2] + RANKS[lows[-2] - 2]][d["n"]] += 1
    return {k: {"n": sum(c.values()), "one": c[1] / sum(c.values()), "two": c[2] / sum(c.values())}
            for k, c in groups.items() if sum(c.values()) >= 50}


def summarize() -> dict:
    decisions, showdowns, (agree, checked), n_hands, n_sample = load()
    matches = json.loads((CACHE / "matches.json").read_text())
    elite = [d for d in decisions if d["elite"]]
    by = lambda fmt, st: [d for d in elite if d["fmt"] == fmt and d["street"] == st]  # noqa: E731
    ranks, n_matches = ranking(matches)
    hu_second = {f"{st}:{k}": pat_table([d for d in by("HU", st) if d["seen"] == [k]],
                                        lambda d: bucket(d["value"]), BUCKETS)
                 for st in STREETS for k in (0, 1, 2)}
    outs = {}
    for st in ("draw2", "draw3"):
        for cls in ("97", "98", "T7", "T8"):
            rows = [d for d in by("HU", st) if d["value"][0] == 0 and top_two(d["value"]) == cls]
            outs[f"{st}:{cls}"] = pat_table(rows, lambda d: outs_bucket(break_outs(d)), ("<=6", "7-8", "9+"))
    dead = {}
    for st in ("draw2", "draw3"):
        rows = [d for d in by("HU", st) if d["value"][0] == 0 and top_two(d["value"])[0] in "9T"
                and top_two(d["value"])[1] in "678"]
        dead[st] = pat_table(rows, lambda d: "none" if dead_outs(d) == 0 else "some", ("none", "some"))
    snows = {f"{fmt}:{st}": {
        "pair": rate([d for d in by(fmt, st) if d["value"][0] in PAIRED_CATEGORIES], lambda d: d["n"] == 0),
        "ka": rate([d for d in by(fmt, st) if d["value"][0] == 0 and d["value"][1][0] >= 13],
                   lambda d: d["n"] == 0)} for fmt in FORMATS for st in STREETS}
    bots = {}
    for fmt, cells in (("HU", (("draw2", "9"), ("draw3", "T"), ("draw3", "J"))),
                       ("6MAX", (("draw1", "8"), ("draw2", "9"), ("draw3", "T")))):
        for bot in sorted({d["bot"] for d in elite if d["fmt"] == fmt}):
            row = {f"{st}:{top}": rate([d for d in by(fmt, st) if d["bot"] == bot and d["value"][0] == 0
                                        and RANKS[d["value"][1][0] - 2] == top], lambda d: d["n"] == 0)
                   for st, top in cells}
            if min(v["n"] for v in row.values()) >= 15:
                bots.setdefault(fmt, {})[bot] = row
    draw_counts = {f"{fmt}:{st}": {str(k): v / len(by(fmt, st)) for k, v in
                                   Counter(d["n"] for d in by(fmt, st)).items()} for fmt in FORMATS
                   for st in STREETS}
    return {
        "data": {"matches_27td": n_matches, "matches_used": len({p.name.split("_")[0] for p in (CACHE / "hands").glob("*.json")}),
                 "hands": n_hands, "sample_hands": n_sample, "decisions": len(decisions),
                 "elite_decisions": len(elite), "showdowns": len(showdowns),
                 "eval_checked": checked, "eval_agree": agree,
                 "elite_hu": len([d for d in elite if d["fmt"] == "HU"]),
                 "elite_6max": len([d for d in elite if d["fmt"] == "6MAX"])},
        "ranking": ranks,
        "discard_rule": discard_rule(elite),
        "draw_counts": draw_counts,
        "kept_top": kept_top(elite),
        "best_four": best_four_choice(elite),
        "pat": {f"{fmt}:{st}": pat_table(by(fmt, st), lambda d: bucket(d["value"]), BUCKETS)
                for fmt in FORMATS for st in STREETS},
        "pat_second": {f"{fmt}:{st}": pat_table(by(fmt, st), lambda d: top_two(d["value"]), SECOND_CARD)
                       for fmt in FORMATS for st in STREETS},
        "pat_hu_vs_draw": hu_second,
        "pat_outs": outs,
        "pat_dead": dead,
        "snows": snows,
        "bots": bots,
        "showdown": showdown_tables(showdowns),
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    summary = summarize()
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    d = summary["data"]
    print(f"{d['hands']} hands ({d['sample_hands']} sample), {d['elite_decisions']} elite decisions, "
          f"evaluator agrees on {d['eval_agree']}/{d['eval_checked']} showdowns")


if __name__ == "__main__":
    main()
