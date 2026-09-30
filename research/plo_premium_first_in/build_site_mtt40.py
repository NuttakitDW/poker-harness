"""Build the tamkwai.com research pages for the 40bb MTT study (Thai, site design).

Writes public/research-mtt40.html (explainer), public/research-mtt40-range.html (every hand)
and public/static/mtt40-range.csv. Every table is computed here from the solver datasets.
Usage: python build_site_mtt40.py
"""

from __future__ import annotations

import collections
import html
import json
import shutil
from pathlib import Path

from analyze_results import DRIVERS, mix_by, r_squared
from archetypes import ARCHETYPES, archetype
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


def range_table(rows: list[dict]) -> str:
    mixes = mix_by(rows, lambda r: "all")["all"]
    body = "".join(
        f'<tr><th scope="row">{s}</th><td class="barcell">{bar(mixes[s], s)}</td>'
        f'<td class="num mono">{pct(mixes[s]["open"], 1)}</td><td class="num mono">{pct(mixes[s]["limp"], 1)}</td>'
        f'<td class="num mono">{pct(mixes[s]["fold"], 1)}</td><td class="num mono"><b>{pct(1 - mixes[s]["fold"], 1)}</b></td></tr>'
        for s in SEATS)
    return ('<div class="table-wrap"><table><thead><tr><th>ตำแหน่ง</th><th>สัดส่วน</th><th class="num">raise</th>'
            f'<th class="num">limp</th><th class="num">fold</th><th class="num">เล่นรวม</th></tr></thead><tbody>{body}</tbody></table></div>')


def tier_table(rows: list[dict]) -> str:
    mixes = mix_by(rows, lambda r: r["tier"])
    body = []
    for tier in TIERS:
        cells = "".join(f'<td class="barcell">{bar(mixes[tier][s], f"{tier} {s}")}'
                        f'<span class="mono small">{pct(1 - mixes[tier][s]["fold"])} เล่น</span></td>' for s in SEATS)
        body.append(f'<tr><th scope="row">{tier}</th>{cells}</tr>')
    head = "".join(f"<th>{s}</th>" for s in SEATS)
    return f'<div class="table-wrap"><table class="tiers"><thead><tr><th>Tier ของ Hwang</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def agreement(rows20: list[dict], rows40: list[dict]) -> tuple[str, dict]:
    stats = {}
    for name, rows in (("20bb", rows20), ("40bb", rows40)):
        stats[name] = {
            "agree": {s: sum(r["combos"] * ((1 - r[s]["fold"]) if hwang_action(r["tier"], s) != "fold" else r[s]["fold"])
                             for r in rows) / TOTAL for s in SEATS},
            "tiers": {s: r_squared(rows, lambda r: r["tier"], s) for s in SEATS},
            "forms": {s: r_squared(rows, lambda r: (r["tier"], r["form"]), s) for s in SEATS},
            "arch": {s: r_squared(rows, archetype, s) for s in SEATS},
        }
    s40 = stats["40bb"]
    lines = [("การตัดสินใจเล่น/ทิ้งที่ตรงกับ Hwang", s40["agree"], True),
             ("R² ของ 4 tier ของ Hwang", s40["tiers"], False),
             ("R² ของรูปแบบมือ 62 แบบของ Hwang", s40["forms"], False),
             ("R² ของ archetype ใหม่ 11 กลุ่ม", s40["arch"], False)]
    body = "".join(f'<tr{" class=\"now\"" if "archetype" in label else ""}><th scope="row">{label}</th>' + "".join(
        f'<td class="num mono">{pct(v[s]) if is_pct else f"{v[s]:.2f}"}</td>' for s in SEATS) + "</tr>"
        for label, v, is_pct in lines)
    head = "".join(f'<th class="num">{s}</th>' for s in SEATS)
    return f'<div class="table-wrap"><table><thead><tr><th>ตัวชี้วัด (40bb MTT)</th>{head}</tr></thead><tbody>{body}</tbody></table></div>', stats


DRIVER_TH = {"Big cards (T+)": "ไพ่ใหญ่ (T ขึ้นไป)", "Suits": "ดอก", "Best suit": "ดอกที่ดีที่สุด", "Pair": "คู่",
             "Straight window": "ไพ่เรียง"}
VALUE_TH = {"Ace": "A มีดอก", "T-K": "T-K มีดอก", "9 or lower": "9 ลงไป", "none": "ไม่มีดอกคู่", "unpaired": "ไม่มีคู่",
            "trips": "ตอง", "rundown (4 in 5)": "4 ใบในช่วง 5", "3 in 5": "3 ใบในช่วง 5", "2 or fewer": "น้อยกว่านั้น"}


def drivers_table(rows20: list[dict], rows40: list[dict]) -> str:
    body = []
    for title, key, order in DRIVERS:
        a, b = mix_by(rows20, key), mix_by(rows40, key)
        first = True
        for value in order:
            if value not in a or value not in b:
                continue
            body.append(
                f'<tr><th scope="row">{DRIVER_TH[title] if first else ""}</th><td>{VALUE_TH.get(value, value)}</td>'
                f'<td class="num mono">{pct(b[value]["share"], 1)}</td>'
                f'<td class="num mono">{pct(1 - a[value]["UTG"]["fold"])}</td><td class="num mono"><b>{pct(1 - b[value]["UTG"]["fold"])}</b></td>'
                f'<td class="num mono">{pct(1 - a[value]["BTN"]["fold"])}</td><td class="num mono"><b>{pct(1 - b[value]["BTN"]["fold"])}</b></td></tr>')
            first = False
    return ('<div class="table-wrap"><table><thead><tr><th>ลักษณะ</th><th>ค่า</th><th class="num">สัดส่วนมือ</th>'
            '<th class="num">UTG 20bb</th><th class="num">UTG 40bb</th><th class="num">BTN 20bb</th><th class="num">BTN 40bb</th>'
            f'</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def rundown_table(rows: list[dict]) -> str:
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
    return ('<div class="table-wrap"><table><thead><tr><th>Rundown (Premium)</th><th class="num">double-suited</th>'
            '<th class="num">single-suited</th><th class="num">three-flush</th><th class="num">monotone</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


FORM_TH = {
    "pair_connectors": "คู่กับไพ่ต่อ", "pair_ace": "คู่กับ A มีดอก", "middle_gap": "rundown ช่องกลาง",
    "bottom_gap": "rundown ช่องล่าง", "rundown": "rundown", "two_gap_middle": "straight ช่องสองกลาง",
    "two_single_gaps": "straight สองช่อง", "two_gap_bottom": "straight ช่องสองล่าง",
    "big_pair_danglers": "คู่ใหญ่กับไพ่ห้อย", "ace_weak": "A มีดอกอ่อน", "three_broadway_dangler": "Broadway สามใบกับไพ่ห้อย",
    "ace_broadway_dangler": "A มีดอก Broadway กับไพ่ห้อย", "double_small": "คู่เล็กสองคู่", "top_two_gaps": "straight ช่องบน",
    "no_structure": "ไม่มีโครงสร้าง", "small_pair_danglers": "คู่เล็กกับไพ่ห้อย", "ace_sucker_low": "A มีดอกกับ 2-3/2-4",
    "top_gap": "rundown ช่องบน", "top_bottom_gap": "rundown ช่องบนและล่าง",
}


def mismatch_table(rows: list[dict], seat: str, limit: int = 6) -> str:
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
    for group, title in (("play", f"Hwang ให้เล่นจาก {seat} แต่ solver ทิ้งเป็นส่วนใหญ่"),
                         ("fold", f"Hwang ให้ทิ้งจาก {seat} แต่ solver เล่นเป็นส่วนใหญ่")):
        total = sum(x[0] for x in out[group])
        parts.append(f'<tr class="group"><th colspan="4">{title} · {total:,.0f} คอมโบ ({total / TOTAL:.1%} ของมือทั้งหมด)</th></tr>')
        for combos, tier, form, shape, mix in sorted(out[group], reverse=True)[:limit]:
            parts.append(f'<tr><td>{tier}</td><td>{FORM_TH.get(form, form.replace("_", " "))}, <span class="mono">{shape}</span></td>'
                         f'<td class="num mono">{combos:,.0f}</td><td class="barcell">{bar(mix)}</td></tr>')
    return ('<div class="table-wrap"><table><thead><tr><th>Tier ของ Hwang</th><th>รูปแบบ, ดอก</th><th class="num">คอมโบ</th>'
            f'<th>สิ่งที่ solver ทำ</th></tr></thead><tbody>{"".join(parts)}</tbody></table></div>')


ACTION_TH = {"open": "raise", "limp": "limp", "fold": "fold"}


def main_action(mix: dict) -> str:
    ordered = sorted(("open", "limp", "fold"), key=lambda a: -mix[a])
    top, second = ordered[0], ordered[1]
    if mix[top] >= 0.6:
        return ACTION_TH[top]
    return f"{ACTION_TH[top]}/{ACTION_TH[second]}"


def archetype_table(rows: list[dict]) -> str:
    mixes = mix_by(rows, archetype)
    body = []
    for key, _, _ in ARCHETYPES:
        name, rule = TH_ARCHETYPES[key]
        m = mixes[key]
        cells = "".join(f'<td class="barcell">{bar(m[s], s)}<span class="small">{main_action(m[s])}</span></td>' for s in SEATS)
        body.append(f'<tr><th scope="row"><b>{name}</b><span class="rule">{rule}</span></th>'
                    f'<td class="num mono">{pct(m["share"], 1)}</td>{cells}</tr>')
    head = "".join(f"<th>{s}</th>" for s in SEATS)
    return (f'<div class="table-wrap"><table class="arch"><thead><tr><th>Archetype (ตรวจตามลำดับ ข้อแรกที่ตรงใช้ข้อนั้น)</th>'
            f'<th class="num">สัดส่วนมือ</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def write_range_page(rows: list[dict]) -> None:
    data = json.loads((GEN40 / "range_first_in.json").read_text())
    page = (HERE / "site_range_template.html").read_text().replace(
        "{{DATA}}", json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/"))
    (PUBLIC / "research-mtt40-range.html").write_text(page)
    shutil.copyfile(GEN40 / "range_first_in.csv", PUBLIC / "static" / "mtt40-range.csv")


def main() -> None:
    rows40 = json.loads((GEN40 / "class_actions.json").read_text())
    rows20 = json.loads((GEN20 / "class_actions.json").read_text())
    freq = json.loads((GEN40 / "solver_frequencies.json").read_text())
    agree_html, stats = agreement(rows20, rows40)
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
    blocks = {
        "{{RANGE_TABLE}}": range_table(rows40),
        "{{TIER_TABLE}}": tier_table(rows40),
        "{{AGREE_TABLE}}": agree_html,
        "{{DRIVERS_TABLE}}": drivers_table(rows20, rows40),
        "{{RUNDOWN_TABLE}}": rundown_table(rows40),
        "{{MISMATCH_UTG}}": mismatch_table(rows40, "UTG"),
        "{{MISMATCH_BTN}}": mismatch_table(rows40, "BTN"),
        "{{ARCHETYPE_TABLE}}": archetype_table(rows40),
    }
    page = (HERE / "site_mtt40_template.html").read_text()
    for key, value in {**numbers, **blocks}.items():
        page = page.replace(key, value)
    if "{{" in page:
        raise RuntimeError("unfilled placeholder " + page[page.index("{{"):][:40])
    (PUBLIC / "research-mtt40.html").write_text(page)
    write_range_page(rows40)
    print("wrote public/research-mtt40.html, public/research-mtt40-range.html, public/static/mtt40-range.csv")
    print(json.dumps({k: v for k, v in numbers.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
