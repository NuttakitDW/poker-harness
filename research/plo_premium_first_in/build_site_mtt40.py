"""Build the tamkwai.com research pages for the 40bb MTT study (Thai and English, site design).

Writes public/research-mtt40.html (explainer), public/research-mtt40-range.html (every hand), their
English versions public/research-mtt40-en.html and public/research-mtt40-range-en.html, and
public/static/mtt40-range.csv. Every table is computed here from the solver datasets; the wording
lives in site_text.py.
Usage: python build_site_mtt40.py
"""

from __future__ import annotations

import collections
import html
import json
import re
import shutil
from pathlib import Path

from analyze_results import DRIVERS, mix_by, r_squared
from archetypes import ARCHETYPES, archetype
from site_text import DRIVER, FORM, LANGS, RANGE, RANGE_PAGE, SUMMARY, TABLE, VALUE, alternates, switch
from thai import ARCHETYPES as TH_ARCHETYPES

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / "public"
GEN40 = HERE / "generated" / "mtt40"
GEN20 = HERE / "generated"
SEATS = ("UTG", "HJ", "CO", "BTN", "SB")
TIERS = ("Premium", "Speculative", "Marginal", "Trash")
TOTAL = 270_725


def pct(x: float, digits: int = 0) -> str:
    return f"{100 * x:.{digits}f}%"


def bar(mix: dict, title: str = "") -> str:
    r, l, f = (round(100 * mix[k]) for k in ("open", "limp", "fold"))
    f = max(0, 100 - r - l)
    tip = html.escape(f"{title} raise {r}% · limp {l}% · fold {f}%".strip())
    return (f'<span class="mix" title="{tip}" role="img" aria-label="{tip}"><i class="r" style="width:{r}%"></i>'
            f'<i class="l" style="width:{l}%"></i><i class="f" style="width:{f}%"></i></span>')


def hwang_action(tier: str, seat: str) -> str:
    return {"Premium": "open", "Speculative": "limp", "Trash": "fold",
            "Marginal": "limp" if seat in ("CO", "BTN", "SB") else "fold"}[tier]


def range_table(rows: list[dict], lang: str) -> str:
    words = TABLE[lang]
    mixes = mix_by(rows, lambda r: "all")["all"]
    body = "".join(
        f'<tr><th scope="row">{s}</th><td class="barcell">{bar(mixes[s], s)}</td>'
        f'<td class="num mono">{pct(mixes[s]["open"], 1)}</td><td class="num mono">{pct(mixes[s]["limp"], 1)}</td>'
        f'<td class="num mono">{pct(mixes[s]["fold"], 1)}</td><td class="num mono"><b>{pct(1 - mixes[s]["fold"], 1)}</b></td></tr>'
        for s in SEATS)
    return (f'<div class="table-wrap"><table><thead><tr><th>{words["seat"]}</th><th>{words["mix"]}</th><th class="num">raise</th>'
            f'<th class="num">limp</th><th class="num">fold</th><th class="num">{words["played"]}</th></tr></thead><tbody>{body}</tbody></table></div>')


def tier_table(rows: list[dict], lang: str) -> str:
    words = TABLE[lang]
    mixes = mix_by(rows, lambda r: r["tier"])
    body = []
    for tier in TIERS:
        cells = "".join(f'<td class="barcell">{bar(mixes[tier][s], f"{tier} {s}")}'
                        f'<span class="mono small">{pct(1 - mixes[tier][s]["fold"])} {words["plays"]}</span></td>' for s in SEATS)
        body.append(f'<tr><th scope="row">{tier}</th>{cells}</tr>')
    head = "".join(f"<th>{s}</th>" for s in SEATS)
    return (f'<div class="table-wrap"><table class="tiers"><thead><tr><th>{words["hwang_tier"]}</th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def agreement_stats(rows20: list[dict], rows40: list[dict]) -> dict:
    stats = {}
    for name, rows in (("20bb", rows20), ("40bb", rows40)):
        stats[name] = {
            "agree": {s: sum(r["combos"] * ((1 - r[s]["fold"]) if hwang_action(r["tier"], s) != "fold" else r[s]["fold"])
                             for r in rows) / TOTAL for s in SEATS},
            "tiers": {s: r_squared(rows, lambda r: r["tier"], s) for s in SEATS},
            "forms": {s: r_squared(rows, lambda r: (r["tier"], r["form"]), s) for s in SEATS},
            "arch": {s: r_squared(rows, archetype, s) for s in SEATS},
        }
    return stats


def agreement_table(stats: dict, lang: str) -> str:
    words, s40 = TABLE[lang], stats["40bb"]
    # (label, values, shown as %, highlighted row)
    lines = [(words["agree"], s40["agree"], True, False), (words["r2_tiers"], s40["tiers"], False, False),
             (words["r2_forms"], s40["forms"], False, False), (words["r2_arch"], s40["arch"], False, True)]
    body = "".join(f'<tr{" class=\"now\"" if now else ""}><th scope="row">{label}</th>' + "".join(
        f'<td class="num mono">{pct(v[s]) if is_pct else f"{v[s]:.2f}"}</td>' for s in SEATS) + "</tr>"
        for label, v, is_pct, now in lines)
    head = "".join(f'<th class="num">{s}</th>' for s in SEATS)
    return (f'<div class="table-wrap"><table><thead><tr><th>{words["measure"]}</th>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def drivers_table(rows20: list[dict], rows40: list[dict], lang: str) -> str:
    words, names, values = TABLE[lang], DRIVER[lang], VALUE[lang]
    body = []
    for title, key, order in DRIVERS:
        a, b = mix_by(rows20, key), mix_by(rows40, key)
        first = True
        for value in order:
            if value not in a or value not in b:
                continue
            body.append(
                f'<tr><th scope="row">{names.get(title, title) if first else ""}</th><td>{values.get(value, value)}</td>'
                f'<td class="num mono">{pct(b[value]["share"], 1)}</td>'
                f'<td class="num mono">{pct(1 - a[value]["UTG"]["fold"])}</td><td class="num mono"><b>{pct(1 - b[value]["UTG"]["fold"])}</b></td>'
                f'<td class="num mono">{pct(1 - a[value]["BTN"]["fold"])}</td><td class="num mono"><b>{pct(1 - b[value]["BTN"]["fold"])}</b></td></tr>')
            first = False
    return (f'<div class="table-wrap"><table><thead><tr><th>{words["feature"]}</th><th>{words["value"]}</th><th class="num">{words["share"]}</th>'
            '<th class="num">UTG 20bb</th><th class="num">UTG 40bb</th><th class="num">BTN 20bb</th><th class="num">BTN 40bb</th>'
            f'</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def rundown_table(rows: list[dict], lang: str) -> str:
    groups: dict = collections.defaultdict(lambda: [0, 0.0])
    for r in rows:
        if r["tier"] == "Premium" and r["form"] in ("rundown", "bottom_gap", "middle_gap") and r["aces"] == 0:
            g = groups[(r["ranks"], r["shape"])]
            g[0] += r["combos"]
            g[1] += r["combos"] * r["UTG"]["fold"]
    shapes = ("ds", "ss", "3f", "mono")
    body = []
    for ranks in ("6543", "7654", "8765", "9876", "T987", "JT98", "QJT9"):
        cells = "".join(
            f'<td class="num mono{" warn" if groups[(ranks, s)][1] / groups[(ranks, s)][0] >= 0.5 else ""}">'
            f'{pct(groups[(ranks, s)][1] / groups[(ranks, s)][0])}</td>' if (ranks, s) in groups else "<td></td>"
            for s in shapes)
        body.append(f'<tr><th scope="row" class="mono">{ranks}</th>{cells}</tr>')
    return (f'<div class="table-wrap"><table><thead><tr><th>{TABLE[lang]["rundown_head"]}</th><th class="num">double-suited</th>'
            '<th class="num">single-suited</th><th class="num">three-flush</th><th class="num">monotone</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')



def mismatch_table(rows: list[dict], seat: str, lang: str, limit: int = 6) -> str:
    words, forms = TABLE[lang], FORM[lang]
    mixes = mix_by(rows, lambda r: (r["tier"], r["form"], r["shape"]))
    out = {"play": [], "fold": []}
    for (tier, form, shape), m in mixes.items():
        combos = m["share"] * TOTAL
        play = 1 - m[seat]["fold"]
        hwang_plays = hwang_action(tier, seat) != "fold"
        if combos < 300:
            continue
        if hwang_plays and play < 0.5:
            out["play"].append((combos, tier, form, shape, m[seat]))
        elif not hwang_plays and play > 0.5:
            out["fold"].append((combos, tier, form, shape, m[seat]))
    parts = []
    for group, title in (("play", words["hwang_plays"].format(seat=seat)),
                         ("fold", words["hwang_folds"].format(seat=seat))):
        total = sum(x[0] for x in out[group])
        line = words["group"].format(title=title, total=f"{total:,.0f}", share=f"{total / TOTAL:.1%}")
        parts.append(f'<tr class="group"><th colspan="4">{line}</th></tr>')
        for combos, tier, form, shape, mix in sorted(out[group], reverse=True)[:limit]:
            parts.append(f'<tr><td>{tier}</td><td>{forms.get(form, form.replace("_", " "))}, <span class="mono">{shape}</span></td>'
                         f'<td class="num mono">{combos:,.0f}</td><td class="barcell">{bar(mix)}</td></tr>')
    return (f'<div class="table-wrap"><table><thead><tr><th>{words["hwang_tier"]}</th><th>{words["form_suits"]}</th>'
            f'<th class="num">{words["combos"]}</th><th>{words["solver_does"]}</th></tr></thead>'
            f'<tbody>{"".join(parts)}</tbody></table></div>')


ACTION_TH = {"open": "raise", "limp": "limp", "fold": "fold"}


def main_action(mix: dict) -> str:
    ordered = sorted(("open", "limp", "fold"), key=lambda a: -mix[a])
    top, second = ordered[0], ordered[1]
    if mix[top] >= 0.6:
        return ACTION_TH[top]
    return f"{ACTION_TH[top]}/{ACTION_TH[second]}"


def archetype_table(rows: list[dict], lang: str) -> str:
    words = TABLE[lang]
    mixes = mix_by(rows, archetype)
    body = []
    for key, english, english_rule in ARCHETYPES:
        name, rule = TH_ARCHETYPES[key] if lang == "th" else (english, english_rule)
        m = mixes[key]
        cells = "".join(f'<td class="barcell">{bar(m[s], s)}<span class="small">{main_action(m[s])}</span></td>' for s in SEATS)
        body.append(f'<tr><th scope="row"><b>{name}</b><span class="rule">{rule}</span></th>'
                    f'<td class="num mono">{pct(m["share"], 1)}</td>{cells}</tr>')
    head = "".join(f"<th>{s}</th>" for s in SEATS)
    return (f'<div class="table-wrap"><table class="arch"><thead><tr><th>{words["arch_head"]}</th>'
            f'<th class="num">{words["share"]}</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def fill(page: str, values: dict[str, str], keep: str = "") -> str:
    """Replace every placeholder; any left over (except keep) is a template bug."""
    for key, value in values.items():
        page = page.replace(key, value)
    rest = page.replace(keep, "") if keep else page
    if "{{" in rest:
        raise RuntimeError("unfilled placeholder " + rest[rest.index("{{"):][:40])
    return page


def write_range_pages() -> None:
    data = json.dumps(json.loads((GEN40 / "range_first_in.json").read_text()), separators=(",", ":"),
                      ensure_ascii=False).replace("</", "<\\/")
    template = (HERE / "site_range_template.html").read_text()
    for lang in LANGS:
        words = RANGE[lang]
        page = re.sub(r"\{\{t:(\w+)\}\}", lambda m: words[m.group(1)], template)
        page = fill(page, {"{{ALTERNATES}}": alternates(RANGE_PAGE), "{{SWITCH}}": switch(lang, RANGE_PAGE),
                           "{{SUMMARY}}": SUMMARY[lang]}, keep="{{DATA}}")
        (PUBLIC / f"{RANGE_PAGE[lang]}.html").write_text(page.replace("{{DATA}}", data))
    shutil.copyfile(GEN40 / "range_first_in.csv", PUBLIC / "static" / "mtt40-range.csv")


def main() -> None:
    rows40 = json.loads((GEN40 / "class_actions.json").read_text())
    rows20 = json.loads((GEN20 / "class_actions.json").read_text())
    freq = json.loads((GEN40 / "solver_frequencies.json").read_text())
    stats = agreement_stats(rows20, rows40)
    everyone = mix_by(rows40, lambda r: "all")["all"]
    numbers = {
        "{{UTG_PLAY}}": pct(1 - everyone["UTG"]["fold"]),
        "{{BTN_PLAY}}": pct(1 - everyone["BTN"]["fold"]),
        "{{SB_PLAY}}": pct(1 - everyone["SB"]["fold"]),
        "{{AGREE_UTG}}": pct(stats["40bb"]["agree"]["UTG"]),
        "{{R2_TIERS}}": f'{stats["40bb"]["tiers"]["UTG"]:.2f}',
        "{{R2_ARCH}}": f'{stats["40bb"]["arch"]["UTG"]:.2f}',
        "{{DEALS}}": f'{freq["mtt40-seed1"]["meta"]["deals"] / 1e6:.0f}',
    }
    style = (HERE / "site_mtt40.css").read_text()
    for lang in LANGS:
        blocks = {
            "{{RANGE_TABLE}}": range_table(rows40, lang),
            "{{TIER_TABLE}}": tier_table(rows40, lang),
            "{{AGREE_TABLE}}": agreement_table(stats, lang),
            "{{DRIVERS_TABLE}}": drivers_table(rows20, rows40, lang),
            "{{RUNDOWN_TABLE}}": rundown_table(rows40, lang),
            "{{MISMATCH_UTG}}": mismatch_table(rows40, "UTG", lang),
            "{{MISMATCH_BTN}}": mismatch_table(rows40, "BTN", lang),
            "{{ARCHETYPE_TABLE}}": archetype_table(rows40, lang),
            "{{STYLE}}": style, "{{ALTERNATES}}": alternates(SUMMARY), "{{SWITCH}}": switch(lang, SUMMARY),
            "{{RANGE_PAGE}}": RANGE_PAGE[lang],
        }
        name = "site_mtt40_template.html" if lang == "th" else f"site_mtt40_template_{lang}.html"
        page = fill((HERE / name).read_text(), {**numbers, **blocks})
        (PUBLIC / f"{SUMMARY[lang]}.html").write_text(page)
    write_range_pages()
    print("wrote " + ", ".join(f"public/{name}.html" for lang in LANGS for name in (SUMMARY[lang], RANGE_PAGE[lang]))
          + ", public/static/mtt40-range.csv")
    print(json.dumps(numbers, ensure_ascii=False))


if __name__ == "__main__":
    main()
