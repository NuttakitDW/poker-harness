"""Render the web edition of the 20bb paper from generated/web_data.json (static inline SVG)."""

from __future__ import annotations

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "generated" / "web_data.json"
OUT = HERE / "output" / "web" / "index.html"
SEATS = ("UTG", "HJ", "CO", "BTN", "SB")
TIERS = ("Premium", "Speculative", "Marginal", "Trash")
BLUE, LIMP, BRONZE, NEUTRAL, INK, PAPER2 = "#2F6FDB", "#7FA3E6", "#C08A3E", "#C9CED8", "#080B12", "#F1F3F8"
ACTION_LABEL = {"open": "raise", "limp": "limp", "mixed": "mixed", "fold": "fold"}


def esc(text: object) -> str:
    return html.escape(str(text))


def pct(value: float, digits: int = 0) -> str:
    return f"{100 * value:.{digits}f}%"


def signed(value: float | None) -> str:
    return "&ndash;" if value is None else f"{value:+.2f}"


def stacked_rows(rows: list[tuple[str, str, list[tuple[float, str, str]]]], label_w: int = 70,
                 bar_w: int = 300, aria: str = "") -> str:
    """rows: (group label, row label, [(share, colour, name)])."""
    row_h, gap = 14, 3
    height = len(rows) * (row_h + gap) + 22
    parts = [f'<svg viewBox="0 0 {label_w + bar_w + 6} {height}" role="img" aria-label="{esc(aria)}">']
    y = 4
    for group, label, segments in rows:
        if group:
            parts.append(f'<text x="0" y="{y + 10.5}" class="lbl strong">{esc(group)}</text>')
        parts.append(f'<text x="{label_w - 6}" y="{y + 10.5}" class="lbl" text-anchor="end">{esc(label)}</text>')
        x = label_w
        for share, colour, name in segments:
            width = share * bar_w
            if width > 0.3:
                parts.append(f'<rect x="{x:.1f}" y="{y}" width="{max(width - 1.5, 0.6):.1f}" height="{row_h}" rx="2" '
                             f'fill="{colour}"><title>{esc(group)} {esc(label)}: {esc(name)} {pct(share)}</title></rect>')
            x += width
        y += row_h + gap
    for tick, anchor in ((0, "start"), (0.5, "middle"), (1, "end")):
        parts.append(f'<text x="{label_w + tick * bar_w:.0f}" y="{y + 12}" class="lbl" text-anchor="{anchor}">{pct(tick)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def verdict_chart(verdicts: dict, tier: str) -> str:
    rows = [("", seat, [(verdicts[tier][seat]["enter"], BLUE, "enter proven"),
                        (verdicts[tier][seat]["close"], NEUTRAL, "too close"),
                        (verdicts[tier][seat]["fold"], BRONZE, "fold proven")]) for seat in SEATS]
    return stacked_rows(rows, label_w=34, bar_w=210, aria=f"{tier}: per-hand verdicts by seat")


def archetype_chart(row: dict) -> str:
    rows = [("", seat, [(row["mix"][seat]["open"], BLUE, "raise"), (row["mix"][seat]["limp"], LIMP, "limp"),
                        (row["mix"][seat]["fold"], BRONZE, "fold")]) for seat in SEATS]
    return stacked_rows(rows, label_w=34, bar_w=210, aria=f"{row['name']}: solved first-in mix by seat")


def archetype_cards(rows: list[dict]) -> str:
    cards = []
    for row in rows:
        chips = "".join(f'<li class="chip {row["action"][s]}"><span>{s}</span>{ACTION_LABEL[row["action"][s]]}</li>'
                        for s in SEATS)
        tiers = ", ".join(f"{t} {pct(v)}" for t, v in sorted(row["tiers"].items(), key=lambda kv: -kv[1]) if v >= 0.05)
        cards.append(
            f'<article class="arch"><header><h3>{esc(row["name"])}</h3><span class="share">{pct(row["share"], 1)} of hands</span></header>'
            f'<p class="rule">{esc(row["rule"])}</p><ul class="chips" aria-label="Recommended first action by seat">{chips}</ul>'
            f'<p class="small">UTG entry value <b>{signed(row["entry_ev"].get("UTG"))}bb</b> &middot; BTN '
            f'<b>{signed(row["entry_ev"].get("BTN"))}bb</b><br>Hwang tiers inside: {esc(tiers)}</p>'
            f'<details><summary>Solver mix by seat</summary>{archetype_chart(row)}</details></article>')
    return "".join(cards)


def drivers_table(drivers: dict) -> str:
    body = []
    for title, values in drivers.items():
        first = True
        for value, row in values.items():
            width = row["utg_play"] * 100
            body.append(
                f'<tr><th>{esc(title) if first else ""}</th><td class="l">{esc(value)}</td><td>{pct(row["share"], 1)}</td>'
                f'<td class="barcell"><span class="bar" style="width:{width:.0f}%"></span><span class="v">{pct(row["utg_play"])}</span></td>'
                f'<td>{pct(row["btn_play"])}</td><td>{signed(row["utg_ev"])}</td><td>{signed(row["btn_ev"])}</td></tr>')
            first = False
    return ('<div class="scroll"><table class="drivers"><thead><tr><th>Feature</th><th class="l">Value</th><th>Hands</th>'
            '<th>UTG play</th><th>BTN play</th><th>UTG entry EV</th><th>BTN entry EV</th></tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table></div>")


def mismatch_table(rows: list[dict]) -> str:
    body = []
    for group, title in (("play", "Hwang enters under the gun; the solver mostly folds"),
                         ("fold", "Hwang folds under the gun; the solver mostly enters")):
        body.append(f'<tr class="group"><th colspan="6">{title}</th></tr>')
        for r in [x for x in rows if x["hwang"] == group][:8]:
            body.append(f'<tr><th>{esc(r["tier"])}</th><td class="l">{esc(r["form"])}, {esc(r["shape"])}</td>'
                        f'<td>{r["combos"]:,}</td><td>{pct(r["utg_play"])}</td><td>{pct(r["btn_play"])}</td>'
                        f'<td>{signed(r["utg_ev"])}</td></tr>')
    return ('<div class="scroll"><table><thead><tr><th>Hwang tier</th><th class="l">Form, suits</th><th>Combos</th>'
            '<th>Solver UTG play</th><th>Solver BTN play</th><th>UTG entry EV</th></tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table></div>")


def evaluation_chart(losses: dict) -> str:
    names = list(losses["UTG"])
    short = {names[0]: "Hwang's advice", names[1]: "Hwang tiers, best action", names[2]: "Hwang forms, best action",
             names[3]: "New archetypes", names[4]: "Solver's own buckets"}
    label_w, bar_w, row_h, gap = 150, 250, 13, 4
    top = 6
    scale = bar_w / 0.14
    height = top + len(SEATS) * (len(names) * (row_h + gap) + 12) + 20
    parts = [f'<svg viewBox="0 0 {label_w + bar_w + 40} {height}" role="img" aria-label="EV lost per first-in decision by rule and seat">']
    y = top
    for seat in SEATS:
        parts.append(f'<text x="0" y="{y + 10}" class="lbl strong">{seat}</text>')
        for name in names:
            value = losses[seat][name]
            colour = BLUE if name == names[3] else NEUTRAL
            parts.append(f'<text x="{label_w - 6}" y="{y + 10}" class="lbl" text-anchor="end">{esc(short[name])}</text>'
                         f'<rect x="{label_w}" y="{y}" width="{max(value * scale, 1):.1f}" height="{row_h}" rx="2" fill="{colour}">'
                         f'<title>{seat}, {esc(short[name])}: {value:.3f} bb</title></rect>'
                         f'<text x="{label_w + value * scale + 5:.1f}" y="{y + 10}" class="val">{value:.3f}</text>')
            y += row_h + gap
        y += 12
    parts.append("</svg>")
    return "".join(parts)


def heat_colour(value: float) -> str:
    t = max(-1.0, min(1.0, value / 1.2))
    end = BLUE if t > 0 else BRONZE
    base = [int(PAPER2[i:i + 2], 16) for i in (1, 3, 5)]
    tip = [int(end[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(round(b + (c - b) * abs(t)) for b, c in zip(base, tip))


def heat_chart(grid: dict) -> str:
    ranks, shapes, cells = grid["ranks"], grid["shapes"], grid["grid"]
    cw, ch, left, top = 62, 16, 44, 20
    parts = [f'<svg viewBox="0 0 {left + cw * len(shapes) + 4} {top + ch * len(ranks) + 4}" role="img" '
             'aria-label="Premium straight hands under the gun: entry minus fold">']
    for j, shape in enumerate(shapes):
        parts.append(f'<text x="{left + j * cw + cw / 2}" y="13" class="lbl" text-anchor="middle">{shape}</text>')
    for i, rank in enumerate(ranks):
        y = top + i * ch
        parts.append(f'<text x="{left - 8}" y="{y + 11.5}" class="lbl" text-anchor="end">{rank}</text>')
        for j, value in enumerate(cells[i]):
            if value is None:
                continue
            ink = PAPER2 if abs(value) >= 0.85 else INK
            parts.append(f'<rect x="{left + j * cw + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" rx="2" '
                         f'fill="{heat_colour(value)}"><title>{rank} {shapes[j]}: {value:+.2f} bb vs fold</title></rect>'
                         f'<text x="{left + j * cw + cw / 2}" y="{y + 11.5}" class="cell" text-anchor="middle" fill="{ink}">{value:+.1f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def verdict_table(verdicts: dict) -> str:
    head = "".join(f"<th>{s}</th>" for s in SEATS)
    body = "".join(
        f"<tr><th>{t}</th>" + "".join(
            f"<td>{pct(verdicts[t][s]['enter'])} / {pct(verdicts[t][s]['close'])} / {pct(verdicts[t][s]['fold'])}</td>"
            for s in SEATS) + "</tr>" for t in TIERS)
    return f'<div class="scroll"><table><thead><tr><th>Enter / close / fold</th>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def page(data: dict) -> str:
    template = (HERE / "web_template.html").read_text()
    replacements = {
        "{{VERDICT_" + t.upper() + "}}": verdict_chart(data["verdicts"], t) for t in TIERS
    }
    replacements.update({
        "{{VERDICT_TABLE}}": verdict_table(data["verdicts"]),
        "{{DRIVERS}}": drivers_table(data["drivers"]),
        "{{MISMATCH}}": mismatch_table(data["mismatches"]),
        "{{ARCHETYPES}}": archetype_cards(data["archetypes"]),
        "{{EVALUATION}}": evaluation_chart(data["losses"]),
        "{{HEAT}}": heat_chart(data["rundowns"]),
    })
    for key, value in data["numbers"].items():
        replacements["{{" + key + "}}"] = esc(value)
    for key, value in replacements.items():
        template = template.replace(key, value)
    if "{{" in template:
        raise RuntimeError("unfilled placeholder: " + template[template.index("{{"):][:40])
    return template


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page(json.loads(DATA.read_text())))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
