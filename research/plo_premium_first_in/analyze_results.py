"""Build every table, number and figure of the 20bb paper from the generated datasets.

Usage: python analyze_results.py --stack 20|100 (outputs go to that stack's generated folder).
Inputs (run in this order first):
  solver_frequencies.py -> generated/solver_frequencies.json   exact tier mixes, both seeds
  class_actions.py      -> generated/class_actions.json        every class, features, solver mix
  audit_dataset.py      -> generated/audit_ev.json             per-hand EVs, population weights
Outputs: generated/*.tex, generated/fig_*.pdf|png, generated/web_data.json.
"""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

import thai  # noqa: E402
from study import from_args  # noqa: E402
from archetypes import ARCHETYPES, NAMES, ORDER, archetype  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = ROOT / "tmp" / "plo_premium_proof"
GEN = HERE / "generated"  # replaced by the chosen study in main()
TAG = "full20"
SEATS = ("UTG", "HJ", "CO", "BTN", "SB")
TIERS = ("Premium", "Speculative", "Marginal", "Trash")
ACTIONS = ("fold", "limp", "open")
BLUE, BRONZE, NEUTRAL, INK, MUTED, EDGE = "#2F6FDB", "#C08A3E", "#C9CED8", "#080B12", "#49556B", "#C2C9D8"
for _font in sorted(thai.FONT_DIR.glob("Sarabun-*.ttf")):
    font_manager.fontManager.addfont(str(_font))
THAI_RC = {"font.family": ["Sarabun", "DejaVu Sans"]}
LIMP = "#7FA3E6"  # lighter step of the same blue: limp is a softer entry than a raise


def load(name: str):
    return json.loads((GEN / name).read_text())


def pct(value: float, digits: int = 0) -> str:
    return f"{100 * value:.{digits}f}"


def fold_ev(seat: str) -> float:
    return -0.5 if seat == "SB" else 0.0


# ---------------------------------------------------------------- per-hand verdicts
def verdict(row: dict) -> str:
    fold = row["ev"]["fold"]
    if any(row["ev"][a] - 3 * row["se"][a] > fold for a in ("limp", "open")):
        return "enter"
    if all(row["ev"][a] + 3 * row["se"][a] < fold for a in ("limp", "open")):
        return "fold"
    return "close"


def verdict_shares(audit: list[dict]) -> dict:
    result: dict = {tier: {} for tier in TIERS}
    for tier in TIERS:
        for seat in SEATS:
            counts = collections.Counter()
            for row in audit:
                if row["tier"] == tier and row["seat"] == seat:
                    counts[verdict(row)] += row["weight"]
            mass = sum(counts.values())
            result[tier][seat] = {k: counts[k] / mass for k in ("enter", "close", "fold")}
    return result


# ---------------------------------------------------------------- drivers
def mix_by(classes: list[dict], key) -> dict:
    groups: dict = collections.defaultdict(lambda: collections.defaultdict(float))
    for row in classes:
        g = groups[key(row)]
        g["n"] += row["combos"]
        for seat in SEATS:
            for action in ACTIONS:
                g[f"{seat}.{action}"] += row["combos"] * row[seat][action]
    total = sum(g["n"] for g in groups.values())
    return {k: {"share": g["n"] / total,
                **{s: {a: g[f"{s}.{a}"] / g["n"] for a in ACTIONS} for s in SEATS}}
            for k, g in groups.items()}


def entry_value_by(audit: list[dict], key) -> dict:
    """Weighted mean of (best entry EV - fold EV) per group and seat."""
    groups: dict = collections.defaultdict(lambda: collections.defaultdict(float))
    for row in audit:
        g = groups[key(row)]
        value = max(row["ev"]["limp"], row["ev"]["open"]) - row["ev"]["fold"]
        g[row["seat"] + ".w"] += row["weight"]
        g[row["seat"] + ".v"] += row["weight"] * value
    return {k: {s: (g[s + ".v"] / g[s + ".w"] if g[s + ".w"] else None) for s in SEATS}
            for k, g in groups.items()}


def pair_class(row: dict) -> str:
    if row["aces"] >= 2:
        return "AA"
    if row["structure"] == "trips":
        return "trips"
    if row["structure"] == "unpaired":
        return "unpaired"
    rank = row["pair_rank"]
    return "KK-QQ" if rank >= 10 else "JJ-TT" if rank >= 8 else "99-22"


DRIVERS = (
    ("Big cards (T+)", lambda r: str(r["high"]), ["0", "1", "2", "3", "4"]),
    ("Suits", lambda r: r["shape"], ["ds", "ss", "3f", "rb", "mono"]),
    ("Best suit", lambda r: {"nut": "Ace", "high": "T-K", "low": "9 or lower", "none": "none"}[r["flush"]],
     ["Ace", "T-K", "9 or lower", "none"]),
    ("Pair", pair_class, ["AA", "KK-QQ", "JJ-TT", "99-22", "unpaired", "trips"]),
    ("Straight window", lambda r: {4: "rundown (4 in 5)", 3: "3 in 5"}.get(r["window"], "2 or fewer"),
     ["rundown (4 in 5)", "3 in 5", "2 or fewer"]),
)


def drivers_table(classes: list[dict], audit: list[dict]) -> tuple[str, dict]:
    lines = [r"\begin{tabular}{llrrrrr}", r"\toprule",
             r"Feature & Value & Hands & UTG play & BTN play & UTG entry EV & BTN entry EV \\", r"\midrule"]
    data = {}
    for title, key, order in DRIVERS:
        mixes, values = mix_by(classes, key), entry_value_by(audit, key)
        data[title] = {}
        for index, value in enumerate(order):
            if value not in mixes:
                continue
            m, v = mixes[value], values.get(value, {})
            row = {"share": m["share"], "utg_play": 1 - m["UTG"]["fold"], "btn_play": 1 - m["BTN"]["fold"],
                   "utg_ev": v.get("UTG"), "btn_ev": v.get("BTN")}
            data[title][value] = row
            ev = lambda x: "--" if x is None else f"{x:+.2f}"  # noqa: E731
            lines.append(f"{title if index == 0 else ''} & {value} & {pct(row['share'], 1)}\\% & "
                         f"{pct(row['utg_play'])}\\% & {pct(row['btn_play'])}\\% & "
                         f"{ev(row['utg_ev'])} & {ev(row['btn_ev'])} \\\\")
        lines.append(r"\midrule")
    lines[-1] = r"\bottomrule"
    lines.append(r"\end{tabular}")
    return "\n".join(lines), data


# ---------------------------------------------------------------- rules and evaluation
def hwang_literal(tier: str, seat: str) -> str:
    """Hwang: raise Premium, limp Speculative, Marginal late and minimum, fold Trash."""
    if tier == "Premium":
        return "open"
    if tier == "Speculative" or (tier == "Marginal" and seat in ("CO", "BTN", "SB")):
        return "limp"
    return "fold"


def fold_hash(hand: str) -> int:
    return hashlib.sha256(hand.encode()).digest()[0] % 2


def best_group_action(rows: list[dict], key) -> dict:
    sums: dict = collections.defaultdict(lambda: collections.defaultdict(float))
    for row in rows:
        for action in ACTIONS:
            sums[(key(row), row["seat"])][action] += row["weight"] * row["ev"][action]
    return {k: max(v, key=v.get) for k, v in sums.items()}


def loss(rows: list[dict], choose) -> float:
    total = sum(r["weight"] for r in rows)
    return sum(r["weight"] * (max(r["ev"].values()) - r["ev"][choose(r)]) for r in rows) / total


def evaluate_rules(audit: list[dict], classes: list[dict]) -> dict:
    """Two-fold cross-validated EV loss (bb per first-in decision) against each hand's best action."""
    solver_mix = {r["hand"]: r for r in classes}
    groupings = {
        "Hwang tiers, best action per tier": lambda r: r["tier"],
        "Hwang forms, best action per form": lambda r: (r["tier"], r["form"]),
        "New archetypes": lambda r: r["archetype"],
    }
    result = {}
    for seat in SEATS:
        rows = [r for r in audit if r["seat"] == seat]
        seat_result = {"Hwang's advice (raise P, limp S, M late, fold T)":
                       loss(rows, lambda r: hwang_literal(r["tier"], seat))}
        for name, key in groupings.items():
            total = 0.0
            weight = 0.0
            for held_out in (0, 1):
                train = [r for r in rows if fold_hash(r["hand"]) != held_out]
                test = [r for r in rows if fold_hash(r["hand"]) == held_out]
                policy = best_group_action(train, key)
                w = sum(r["weight"] for r in test)
                total += w * loss(test, lambda r: policy.get((key(r), seat), "fold"))
                weight += w
            seat_result[name] = total / weight
        seat_result["Solver's own bucket strategy (most likely action)"] = loss(
            rows, lambda r: max(ACTIONS, key=lambda a: r["solver"][a]))
        result[seat] = seat_result
    return result


def r_squared(classes: list[dict], key, seat: str) -> float:
    total = sum(r["combos"] for r in classes)
    mean = sum(r["combos"] * r[seat]["fold"] for r in classes) / total
    sst = sum(r["combos"] * (r[seat]["fold"] - mean) ** 2 for r in classes)
    groups: dict = collections.defaultdict(lambda: [0.0, 0.0])
    for r in classes:
        groups[key(r)][0] += r["combos"]
        groups[key(r)][1] += r["combos"] * r[seat]["fold"]
    sse = sum(r["combos"] * (r[seat]["fold"] - groups[key(r)][1] / groups[key(r)][0]) ** 2 for r in classes)
    return 1 - sse / sst


def evaluation_table(losses: dict, r2: dict) -> str:
    names = list(next(iter(losses.values())))
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule",
             r"Rule & UTG & HJ & CO & BTN & SB \\", r"\midrule",
             r"\multicolumn{6}{l}{\textit{EV lost per first-in decision (bb), held-out hands}} \\"]
    for name in names:
        lines.append(name.replace("&", r"\&") + " & " + " & ".join(f"{losses[s][name]:.3f}" for s in SEATS) + r" \\")
    lines += [r"\midrule", r"\multicolumn{6}{l}{\textit{Share of variation in the solver's fold rate explained}} \\"]
    for name, values in r2.items():
        lines.append(name + " & " + " & ".join(f"{values[s]:.2f}" for s in SEATS) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


# ---------------------------------------------------------------- archetypes
MIXED_BAND = 0.10  # bb: entry EV this close to folding is reported as a mixed decision


def archetype_rows(classes: list[dict], audit: list[dict]) -> list[dict]:
    mixes = mix_by(classes, lambda r: archetype(r))
    values = entry_value_by(audit, lambda r: r["archetype"])
    tiers: dict = collections.defaultdict(collections.Counter)
    for r in classes:
        tiers[archetype(r)][r["tier"]] += r["combos"]
    sums: dict = collections.defaultdict(lambda: collections.defaultdict(float))
    for r in audit:
        s = sums[(r["archetype"], r["seat"])]
        s["w"] += r["weight"]
        for action in ACTIONS:
            s[action] += r["weight"] * (r["ev"][action] - r["ev"]["fold"])
    rows = []
    for key, name, rule in ARCHETYPES:
        n = sum(tiers[key].values())
        action = {}
        for seat in SEATS:
            s = sums[(key, seat)]
            limp, raise_ = s["limp"] / s["w"], s["open"] / s["w"]
            best = max(limp, raise_)
            action[seat] = ("mixed" if abs(best) < MIXED_BAND else "fold" if best < 0
                            else "open" if raise_ >= limp else "limp")
        rows.append({
            "key": key, "name": name, "rule": rule, "share": mixes[key]["share"],
            "tiers": {t: tiers[key][t] / n for t in TIERS},
            "mix": {s: mixes[key][s] for s in SEATS},
            "entry_ev": values.get(key, {}),
            "action": action,
        })
    return rows


ACTION_WORD = {"fold": "fold", "limp": "limp", "open": "raise", "mixed": "mixed"}


def archetype_table(rows: list[dict]) -> str:
    lines = [r"\begin{tabular}{>{\raggedright\arraybackslash}p{3.8cm}r>{\raggedright\arraybackslash}p{3.3cm}lllll}", r"\toprule",
             r"Archetype & Hands & Hwang tiers inside & UTG & HJ & CO & BTN & SB \\", r"\midrule"]
    for row in rows:
        tiers = ", ".join(f"{t[0]}\\,{pct(v)}" for t, v in sorted(row["tiers"].items(), key=lambda kv: -kv[1]) if v >= 0.05)
        cells = " & ".join(ACTION_WORD[row["action"][s]] for s in SEATS)
        lines.append(f"{row['name']} & {pct(row['share'], 1)}\\% & {tiers} & {cells} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def archetype_rules_table(rows: list[dict]) -> str:
    lines = [r"\begin{tabular}{>{\raggedright\arraybackslash}p{3.8cm}>{\raggedright\arraybackslash}p{8.8cm}r}", r"\toprule",
             r"Archetype & Rule (first match wins) & UTG entry EV \\", r"\midrule"]
    for row in rows:
        ev = row["entry_ev"].get("UTG")
        lines.append(f"{row['name']} & {row['rule']} & {'--' if ev is None else f'{ev:+.2f}'} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


# ---------------------------------------------------------------- Hwang mismatches
def mismatch_rows(classes: list[dict], audit: list[dict]) -> list[dict]:
    key = lambda r: (r["tier"], r["form"], r["shape"])  # noqa: E731
    mixes = mix_by(classes, key)
    values = entry_value_by(audit, key)
    total = sum(r["combos"] for r in classes)
    out = []
    for k, m in mixes.items():
        tier, form, shape = k
        hwang_plays_utg = hwang_literal(tier, "UTG") != "fold"
        play = 1 - m["UTG"]["fold"]
        combos = m["share"] * total
        if combos < 250 or (hwang_plays_utg and play > 0.5) or (not hwang_plays_utg and play < 0.5):
            continue
        out.append({"tier": tier, "form": form.replace("_", " "), "shape": shape, "combos": round(combos),
                    "hwang": "play" if hwang_plays_utg else "fold", "utg_play": play,
                    "btn_play": 1 - m["BTN"]["fold"], "utg_ev": values.get(k, {}).get("UTG")})
    return sorted(out, key=lambda r: (r["hwang"], -r["combos"]))


def mismatch_table(rows: list[dict]) -> str:
    lines = [r"\begin{tabular}{lllrrrr}", r"\toprule",
             r"Hwang tier & Form & Suits & Combos & Solver UTG play & Solver BTN play & UTG entry EV \\", r"\midrule"]
    for group, title in (("play", r"\textit{Hwang enters from UTG; the solver mostly folds}"),
                         ("fold", r"\textit{Hwang folds from UTG; the solver mostly enters}")):
        lines.append(r"\multicolumn{7}{l}{" + title + r"} \\")
        for r in [x for x in rows if x["hwang"] == group][:10]:
            ev = "--" if r["utg_ev"] is None else f"{r['utg_ev']:+.2f}"
            lines.append(f"{r['tier']} & {r['form']} & {r['shape']} & {r['combos']:,} & {pct(r['utg_play'])}\\% & "
                         f"{pct(r['btn_play'])}\\% & {ev} \\\\")
        lines.append(r"\midrule")
    lines[-1] = r"\bottomrule"
    lines.append(r"\end{tabular}")
    return "\n".join(lines)


def crosstab(classes: list[dict]) -> dict:
    table: dict = collections.defaultdict(collections.Counter)
    for r in classes:
        table[r["tier"]][archetype(r)] += r["combos"]
    return {t: {a: table[t][a] for a in ORDER} for t in TIERS}


# ---------------------------------------------------------------- tier frequency and verdict tables
def tier_table(freq: dict) -> str:
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule", r"Tier & UTG & HJ & CO & BTN & SB \\", r"\midrule"]
    for tier in (*TIERS, "All"):
        cells = []
        for seat in SEATS:
            mixes = [freq[f"{TAG}-seed{s}"]["seats"][seat][tier] for s in (1, 2)]
            mean = {a: (mixes[0][k] + mixes[1][k]) / 2 for a, k in (("fold", "fold"), ("limp", "limp"),
                                                                     ("open", "pot_open"))}
            cells.append(f"{pct(mean['fold'])}/{pct(mean['limp'])}/{pct(mean['open'])}")
        lines.append(("\\textit{All hands}" if tier == "All" else tier) + " & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


def verdict_table(shares: dict) -> str:
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule", r"Tier & UTG & HJ & CO & BTN & SB \\", r"\midrule"]
    for tier in TIERS:
        lines.append(tier + " & " + " & ".join(
            f"{pct(shares[tier][s]['enter'])}/{pct(shares[tier][s]['close'])}/{pct(shares[tier][s]['fold'])}"
            for s in SEATS) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines)


# ---------------------------------------------------------------- figures
def style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(EDGE)
    ax.tick_params(colors=MUTED, labelsize=7.5)


def archetype_figure(rows: list[dict], path: Path, lang: str = "en") -> None:
    cols = 4
    grid_rows = -(-len(rows) // cols)
    fig, axes = plt.subplots(grid_rows, cols, figsize=(7.2, 1.55 * grid_rows + 0.4), sharex=True)
    flat = [ax for line in axes for ax in line]
    for ax, row in zip(flat, rows):
        for index, seat in enumerate(SEATS):
            left = 0.0
            for action, color in (("open", BLUE), ("limp", LIMP), ("fold", BRONZE)):
                width = row["mix"][seat][action]
                ax.barh(len(SEATS) - 1 - index, width, left=left, color=color, height=0.74,
                        edgecolor="white", linewidth=0.7)
                left += width
        of_hands = thai.FIGURE["share_of_hands"] if lang == "th" else "of hands"
        ax.set_title(f"{row['name']}\n{pct(row['share'], 1)}% {of_hands}", fontsize=7, color=INK, loc="left")
        ax.set_yticks(range(len(SEATS)))
        ax.set_yticklabels(SEATS[::-1], fontsize=6.5)
        ax.set_xlim(0, 1)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["0", "100%"], fontsize=6.5)
        style(ax)
    for ax in flat[len(rows):]:
        ax.axis("off")
    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in (BLUE, LIMP, BRONZE)],
               labels=["Raise (pot)", "Limp", "Fold"], loc="lower right", bbox_to_anchor=(0.97, 0.08),
               ncol=1, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def verdict_figure(shares: dict, path: Path, lang: str = "en") -> None:
    fig, axes = plt.subplots(1, 4, figsize=(7.2, 2.2), sharey=True)
    for ax, tier in zip(axes, TIERS):
        left = [0.0] * len(SEATS)
        for key, color in (("enter", BLUE), ("close", NEUTRAL), ("fold", BRONZE)):
            widths = [shares[tier][s][key] for s in SEATS]
            ax.barh(range(len(SEATS))[::-1], widths, left=left, color=color, height=0.72,
                    edgecolor="white", linewidth=0.8)
            left = [a + b for a, b in zip(left, widths)]
        ax.set_title(tier, fontsize=8.5, color=INK, loc="left")
        ax.set_yticks(range(len(SEATS))[::-1])
        ax.set_yticklabels(SEATS, fontsize=7.5)
        ax.set_xlim(0, 1)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["0", "100%"])
        style(ax)
    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in (BLUE, NEUTRAL, BRONZE)],
               labels=thai.FIGURE["verdict_legend"] if lang == "th"
               else ["Entering proven better", "Too close", "Folding proven better"],
               loc="lower center", bbox_to_anchor=(0.5, -0.1), ncol=3, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def rundown_grid(audit: list[dict]) -> dict:
    cells: dict = collections.defaultdict(list)
    for row in audit:
        if row["seat"] == "UTG" and row["tier"] == "Premium" and row["form"] in ("rundown", "bottom_gap", "middle_gap"):
            ranks = "".join(sorted({c for c in row["hand"][0::2]}, key="23456789TJQKA".index, reverse=True))
            if len(ranks) == 4:
                cells[(ranks, row["shape"])].append(max(row["ev"]["limp"], row["ev"]["open"]) - row["ev"]["fold"])
    order = "23456789TJQKA"
    ranks = sorted({k[0] for k in cells}, key=lambda r: [order.index(c) for c in r])
    shapes = ["ds", "ss", "3f", "mono"]
    grid = [[(sum(cells[(r, s)]) / len(cells[(r, s)])) if cells.get((r, s)) else None for s in shapes] for r in ranks]
    return {"ranks": ranks, "shapes": shapes, "grid": grid}


def rundown_figure(grid: dict, path: Path, lang: str = "en") -> None:
    cmap = LinearSegmentedColormap.from_list("fold_enter", [BRONZE, "#F1F3F8", BLUE])
    values = [[float("nan") if v is None else v for v in row] for row in grid["grid"]]
    fig, ax = plt.subplots(figsize=(3.6, 6.0))
    image = ax.imshow(values, cmap=cmap, vmin=-1.2, vmax=1.2, aspect="auto")
    for i, row in enumerate(grid["grid"]):
        for j, v in enumerate(row):
            if v is not None:
                ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=6,
                        color="#F1F3F8" if abs(v) >= 0.85 else INK)
    ax.set_xticks(range(len(grid["shapes"])))
    ax.set_xticklabels(grid["shapes"], fontsize=8)
    ax.set_yticks(range(len(grid["ranks"])))
    ax.set_yticklabels(grid["ranks"], fontsize=7, family="monospace")
    style(ax)
    bar = fig.colorbar(image, ax=ax, orientation="horizontal", fraction=0.04, pad=0.05)
    bar.set_label(thai.FIGURE["rundown_bar"] if lang == "th" else "UTG: best entry minus fold (bb)", fontsize=8, color=MUTED)
    bar.ax.tick_params(labelsize=7, colors=MUTED)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- main
def seed_agreement() -> dict:
    a = json.loads((RUNS / f"{TAG}-report-seed-1.json").read_text())["premium_rows"]
    b = json.loads((RUNS / f"{TAG}-report-seed-2.json").read_text())["premium_rows"]
    to = {"must_not_fold": "enter", "fold_beats_every_deviation": "fold", "inconclusive": "close"}
    first = {(r["hand"], r["position"]): to[r["verdict"]] for r in a}
    pairs = [(first[(r["hand"], r["position"])], to[r["verdict"]]) for r in b if (r["hand"], r["position"]) in first]
    return {"pairs": len(pairs), "contradictions": sum(1 for x, y in pairs if {x, y} == {"enter", "fold"})}


def write_thai(shares, freq, drivers_tex, mismatches, arch_rows, losses, r2, rundowns) -> None:
    """Thai edition: same numbers, Thai labels (poker terms stay in English)."""
    rows_th = [{**row, "name": thai.ARCHETYPES[row["key"]][0], "rule": thai.ARCHETYPES[row["key"]][1]}
               for row in arch_rows]
    tables = {
        "table_tiers_th.tex": tier_table(freq),
        "table_verdicts_th.tex": verdict_table(shares),
        "table_drivers_th.tex": drivers_tex,
        "table_mismatch_th.tex": mismatch_table(mismatches),
        "table_archetypes_th.tex": archetype_table(rows_th),
        "table_archetype_rules_th.tex": archetype_rules_table(rows_th),
        "table_evaluation_th.tex": evaluation_table(losses, r2),
    }
    for name, tex in tables.items():
        (GEN / name).write_text(thai.localize_table(tex))
    with plt.rc_context(THAI_RC):
        for suffix in ("pdf", "png"):
            archetype_figure(rows_th, GEN / f"fig_archetypes_th.{suffix}", lang="th")
            verdict_figure(shares, GEN / f"fig_verdicts_th.{suffix}", lang="th")
            rundown_figure(rundowns, GEN / f"fig_rundowns_th.{suffix}", lang="th")


def main() -> None:
    global GEN, TAG
    study = from_args(__doc__)
    GEN, TAG = study.generated, study.tag
    freq = load("solver_frequencies.json")
    classes = load("class_actions.json")
    audit = load("audit_ev.json")
    for row in audit:
        row["archetype"] = archetype(row)  # rules may have changed since the dataset was written
    shares = verdict_shares(audit)
    drivers_tex, drivers = drivers_table(classes, audit)
    losses = evaluate_rules(audit, classes)
    r2 = {name: {s: r_squared(classes, key, s) for s in SEATS} for name, key in (
        ("Hwang tiers (4 groups)", lambda r: r["tier"]),
        ("Hwang forms (62 groups)", lambda r: (r["tier"], r["form"])),
        (f"New archetypes ({len(ARCHETYPES)} groups)", lambda r: archetype(r)))}
    arch_rows = archetype_rows(classes, audit)
    mismatches = mismatch_rows(classes, audit)
    agreement = seed_agreement()
    rundowns = rundown_grid(audit)
    meta = freq[f"{TAG}-seed1"]["meta"]
    numbers = {
        "PremFoldUTG": pct(shares["Premium"]["UTG"]["fold"]),
        "PremEnterUTG": pct(shares["Premium"]["UTG"]["enter"]),
        "PremFoldBTN": pct(shares["Premium"]["BTN"]["fold"]),
        "TrashFoldUTG": pct(shares["Trash"]["UTG"]["fold"]),
        "SeedPairs": str(agreement["pairs"]),
        "SeedContra": str(agreement["contradictions"]),
        "Deals": f"{meta['deals'] / 1e6:.1f}",
        "ArchCount": str(len(ARCHETYPES)),
        "LossHwangUTG": f"{losses['UTG'][next(iter(losses['UTG']))]:.3f}",
        "LossArchUTG": f"{losses['UTG']['New archetypes']:.3f}",
        "RsqTierUTG": f"{r2['Hwang tiers (4 groups)']['UTG']:.2f}",
        "RsqArchUTG": f"{r2[f'New archetypes ({len(ARCHETYPES)} groups)']['UTG']:.2f}",
        "AuditRows": f"{len(audit):,}",
        "AuditClasses": f"{len({r['hand'] for r in audit}):,}",
    }
    GEN.mkdir(parents=True, exist_ok=True)
    (GEN / "macros.tex").write_text("".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in numbers.items()))
    (GEN / "table_tiers.tex").write_text(tier_table(freq))
    (GEN / "table_verdicts.tex").write_text(verdict_table(shares))
    (GEN / "table_drivers.tex").write_text(drivers_tex)
    (GEN / "table_mismatch.tex").write_text(mismatch_table(mismatches))
    (GEN / "table_archetypes.tex").write_text(archetype_table(arch_rows))
    (GEN / "table_archetype_rules.tex").write_text(archetype_rules_table(arch_rows))
    (GEN / "table_evaluation.tex").write_text(evaluation_table(losses, r2))
    for suffix in ("pdf", "png"):
        archetype_figure(arch_rows, GEN / f"fig_archetypes.{suffix}")
        verdict_figure(shares, GEN / f"fig_verdicts.{suffix}")
        rundown_figure(rundowns, GEN / f"fig_rundowns.{suffix}")
    write_thai(shares, freq, drivers_tex, mismatches, arch_rows, losses, r2, rundowns)
    (GEN / "web_data.json").write_text(json.dumps({
        "numbers": numbers, "verdicts": shares, "drivers": drivers, "losses": losses, "r2": r2,
        "archetypes": arch_rows, "mismatches": mismatches, "crosstab": crosstab(classes),
        "rundowns": rundowns, "agreement": agreement, "names": NAMES,
    }, indent=1))
    print(json.dumps({"numbers": numbers, "losses": losses}, indent=1))


if __name__ == "__main__":
    main()
