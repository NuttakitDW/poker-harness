"""Write the paper's macros, tables and TikZ figures from generated/summary.json.

    .venv/bin/python research/td27_arena/analyze.py
    .venv/bin/python research/td27_arena/build_paper.py
    cd research/td27_arena && pdflatex -output-directory output paper.tex (twice)
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "generated"
SUMMARY = OUT / "summary.json"
STREETS = ("draw1", "draw2", "draw3")
STREET_NAME = {"draw1": "Draw 1", "draw2": "Draw 2", "draw3": "Draw 3"}
BUCKETS = ("75", "76", "85", "86", "87", "9", "T", "J", "Q", "K", "A")
BUCKET_NAME = {"75": "7-5", "76": "7-6", "85": "8-5", "86": "8-6", "87": "8-7", "9": "9", "T": "T",
               "J": "J", "Q": "Q", "K": "K", "A": "A"}
MIN_CELL = 20


def pct(cell: dict | None, min_n: int = MIN_CELL) -> str:
    if not cell or cell["p"] is None or cell["n"] < min_n:
        return "--"
    return f"{100 * cell['p']:.0f}"


def num(x: float, digits: int = 0) -> str:
    return f"{x:,.{digits}f}".replace(",", "{,}")


def macros(s: dict) -> list[str]:
    d, k, rule = s["data"], s["kept_top"], s["discard_rule"]["agree"]
    p = lambda key, st, b: 100 * s["pat"][f"{key}:{st}"][b]["p"]  # noqa: E731
    hu = s["pat_hu_vs_draw"]
    sd = s["showdown"]
    rule_lo = min(v["p"] for v in rule.values())
    values = {
        "NMatchesAll": num(d["matches_27td"]), "NMatchesUsed": num(d["matches_used"]),
        "NHands": num(d["hands"]), "NSampleHands": num(d["sample_hands"]),
        "NDecisions": num(d["decisions"]), "NElite": num(d["elite_decisions"]),
        "NEliteHU": num(d["elite_hu"]), "NEliteSix": num(d["elite_6max"]),
        "NShowdowns": num(d["eval_checked"]),
        "RuleLow": f"{100 * rule_lo:.1f}", "RuleN": num(sum(v["n"] for v in rule.values())),
        "KeptEightHU": f"{100 * k['HU:1']['le8']:.0f}", "KeptEightSix": f"{100 * k['6MAX:1']['le8']:.0f}",
        "KeptNineHU": f"{100 * k['HU:1']['nine']:.1f}", "KeptNineSix": f"{100 * k['6MAX:1']['nine']:.1f}",
        "KeptEightTwoHU": f"{100 * k['HU:2']['le8']:.0f}",
        "PatEightSevenHU": f"{p('HU', 'draw1', '87'):.0f}", "PatEightSevenSix": f"{p('6MAX', 'draw1', '87'):.0f}",
        "PatNineDrawTwoHU": f"{p('HU', 'draw2', '9'):.0f}", "PatNineDrawTwoSix": f"{p('6MAX', 'draw2', '9'):.0f}",
        "PatNineDrawThreeHU": f"{p('HU', 'draw3', '9'):.0f}", "PatTenDrawThreeHU": f"{p('HU', 'draw3', 'T'):.0f}",
        "PatJackDrawThreeHU": f"{p('HU', 'draw3', 'J'):.0f}",
        "PatTenVsPat": pct(hu["draw3:0"]["T"]), "PatNineVsPat": pct(hu["draw3:0"]["9"]),
        "PatTenVsOne": pct(hu["draw3:1"]["T"]), "PatJackVsOne": pct(hu["draw3:1"]["J"]),
        "PatQueenVsOne": pct(hu["draw3:1"]["Q"]),
        "PatTNineTwo": pct(s["pat_second"]["HU:draw2"]["T9"]), "PatTEightTwo": pct(s["pat_second"]["HU:draw2"]["T8"]),
        "PatJNineThree": pct(s["pat_second"]["HU:draw3"]["J9"]),
        "PatJEightThree": pct(s["pat_second"]["HU:draw3"]["J8"]),
        "OutsTEightManyTwo": pct(s["pat_outs"]["draw2:T8"]["9+"]),
        "OutsTEightFewTwo": pct(s["pat_outs"]["draw2:T8"]["7-8"]),
        "SdNHU": num(sd["HU"]["n"]), "SdNSix": num(sd["6MAX"]["n"]),
        "SdCumEightSevenHU": f"{100 * sd['HU']['winner']['87']['cum']:.0f}",
        "SdCumNineHU": f"{100 * sd['HU']['winner']['9']['cum']:.0f}",
        "SdCumEightSevenSix": f"{100 * sd['6MAX']['winner']['87']['cum']:.0f}",
        "SdWinNineHU": pct(sd["HU"]["win_rate"]["9"]), "SdWinTenHU": pct(sd["HU"]["win_rate"]["T"]),
        "SdWinJackHU": pct(sd["HU"]["win_rate"]["J"]), "SdWinJackSix": pct(sd["6MAX"]["win_rate"]["J"]),
        "SdWinEightSevenHU": pct(sd["HU"]["win_rate"]["87"]),
        "SnowThreeHU": f"{100 * s['snows']['HU:draw3']['pair']['p']:.1f}",
        "SnowThreeSix": f"{100 * s['snows']['6MAX:draw3']['pair']['p']:.1f}",
        "StraightN": num(s["discard_rule"]["straight_breaks"]["n"]),
        "StraightTop": f"{100 * s['discard_rule']['straight_breaks']['top']:.0f}",
        "StraightInside": f"{100 - 100 * s['discard_rule']['straight_breaks']['top']:.0f}",
        "StraightMissShare": f"{100 * s['discard_rule']['straight_breaks']['misses_share']:.0f}",
        "BreakEightSevenTwo": f"{100 * s['best_four']['87']['two']:.0f}",
        "DeadSomeN": num(s["pat_dead"]["draw2"]["some"]["n"] + s["pat_dead"]["draw3"]["some"]["n"]),
    }
    return [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in values.items()]


def ranking_table(s: dict) -> list[str]:
    rows = []
    for fmt, label in (("HU", "Heads-up"), ("6MAX", "Six-max")):
        rows.append(f"\\multicolumn{{4}}{{l}}{{\\textit{{{label}}}}}\\\\")
        for r in s["ranking"][fmt][:7]:
            rows.append(f"\\texttt{{{r['bot']}}} & ${r['rate']:+.2f}$ & {r['matches']} & {num(r['hands'])}\\\\")
        rows.append("\\midrule")
    return rows[:-1]


def pat_table(s: dict) -> list[str]:
    rows = []
    for fmt, label in (("HU", "HU"), ("6MAX", "6-max")):
        for st in STREETS:
            cells = s["pat"][f"{fmt}:{st}"]
            rows.append(f"{label} & {STREET_NAME[st]} & " + " & ".join(pct(cells.get(b)) for b in BUCKETS) + "\\\\")
        rows.append("\\midrule")
    return rows[:-1]


def vs_draw_table(s: dict) -> list[str]:
    rows, labels = [], ("9", "T", "J", "Q", "K")
    seen = {0: "stood pat", 1: "drew 1", 2: "drew 2"}
    for st in STREETS:
        for k in (0, 1, 2):
            cells = s["pat_hu_vs_draw"][f"{st}:{k}"]
            if sum(c["n"] for c in cells.values()) < 60:
                continue
            rows.append(f"{STREET_NAME[st]} & {seen[k]} & " + " & ".join(pct(cells.get(b), 10) for b in labels) + "\\\\")
    return rows


def second_card_table(s: dict) -> list[str]:
    groups = (("9", ("96", "97", "98")), ("T", ("T6", "T7", "T8", "T9")), ("J", ("J7", "J8", "J9", "JT")))
    rows = []
    for fmt, label in (("HU", "HU"), ("6MAX", "6-max")):
        for st in ("draw2", "draw3"):
            cells = s["pat_second"][f"{fmt}:{st}"]
            vals = [pct(cells.get(c)) for _, cs in groups for c in cs]
            rows.append(f"{label} & {STREET_NAME[st]} & " + " & ".join(vals) + "\\\\")
    return rows


def outs_table(s: dict) -> list[str]:
    rows = []
    for st in ("draw2", "draw3"):
        for cls in ("97", "98", "T7", "T8"):
            cells = s["pat_outs"][f"{st}:{cls}"]
            vals = [f"{pct(cells.get(b), 10)} \\scriptsize({cells[b]['n']})" if b in cells else "--"
                    for b in ("<=6", "7-8", "9+")]
            rows.append(f"{STREET_NAME[st]} & {cls[0]}-{cls[1]} & " + " & ".join(vals) + "\\\\")
    return rows


def rule_table(s: dict) -> list[str]:
    agree = s["discard_rule"]["agree"]
    rows = []
    for n in (1, 2, 3, 4):
        hu, six = agree.get(f"HU:{n}"), agree.get(f"6MAX:{n}")
        cell = lambda c: f"{100 * c['p']:.1f} \\scriptsize({num(c['n'])})" if c else "--"  # noqa: E731
        rows.append(f"{n} & {cell(hu)} & {cell(six)}\\\\")
    return rows


def showdown_table(s: dict) -> list[str]:
    rows = []
    labels = ("76", "86", "87", "9", "T", "J", "Q", "K", "A")
    for fmt, label in (("HU", "HU"), ("6MAX", "6-max")):
        sd = s["showdown"][fmt]
        rows.append(f"{label} & cum.\\ share of winners & "
                    + " & ".join(f"{100 * sd['winner'][b]['cum']:.0f}" for b in labels) + "\\\\")
        rows.append(f"{label} & win rate holding it & " + " & ".join(pct(sd["win_rate"].get(b)) for b in labels) + "\\\\")
    return rows


def bots_table(s: dict) -> list[str]:
    rows = []
    for fmt, cols in (("HU", ("draw2:9", "draw3:T", "draw3:J")), ("6MAX", ("draw1:8", "draw2:9", "draw3:T"))):
        rows.append(f"\\multicolumn{{4}}{{l}}{{\\textit{{{'Heads-up' if fmt == 'HU' else 'Six-max'}: "
                    f"{', '.join(c.replace('draw', 'D').replace(':', ' ') for c in cols)}}}}}\\\\")
        for bot, row in s["bots"][fmt].items():
            rows.append(f"\\texttt{{{bot}}} & " + " & ".join(
                f"{pct(row[c], 1)} \\scriptsize({row[c]['n']})" for c in cols) + "\\\\")
    return rows


def pat_figure(s: dict) -> list[str]:
    """Pat frequency against the made hand's top cards, one line per draw, HU solid and 6-max dashed."""
    labels = ("86", "87", "9", "T", "J", "Q")
    w, h = 1.35, 4.0
    out = ["\\begin{tikzpicture}[font=\\small]"]
    for i in range(6):
        y = i * 20
        out.append(f"\\draw[noise] (0,{y / 100 * h:.2f}) -- ({(len(labels) - 1) * w:.2f},{y / 100 * h:.2f});")
        out.append(f"\\node[anchor=east] at (-0.1,{y / 100 * h:.2f}) {{{y}}};")
    for i, lab in enumerate(labels):
        out.append(f"\\node[anchor=north] at ({i * w:.2f},-0.1) {{{BUCKET_NAME[lab]}}};")
    styles = {"draw1": "streetone", "draw2": "streettwo", "draw3": "streetthree"}
    for fmt, dash in (("HU", "solid"), ("6MAX", "dashed")):
        for st in STREETS:
            cells = s["pat"][f"{fmt}:{st}"]
            pts = " -- ".join(f"({i * w:.2f},{cells[b]['p'] * h:.2f})" for i, b in enumerate(labels))
            out.append(f"\\draw[{styles[st]},line width=1.2pt,{dash}] {pts};")
            if fmt == "HU":
                for i, b in enumerate(labels):
                    out.append(f"\\fill[{styles[st]}] ({i * w:.2f},{cells[b]['p'] * h:.2f}) circle (1.6pt);")
    out.append(f"\\node[rotate=90] at (-0.75,{h / 2:.2f}) {{stand pat (\\%)}};")
    out.append(f"\\node at ({(len(labels) - 1) * w / 2:.2f},-0.65) {{made hand (top cards)}};")
    lx = (len(labels) - 1) * w + 0.4
    for j, st in enumerate(STREETS):
        y = h - j * 0.45
        out.append(f"\\draw[{styles[st]},line width=1.2pt] ({lx:.2f},{y:.2f}) -- ({lx + 0.5:.2f},{y:.2f});")
        out.append(f"\\node[anchor=west] at ({lx + 0.55:.2f},{y:.2f}) {{{STREET_NAME[st]}}};")
    out.append(f"\\draw[black,line width=1pt] ({lx:.2f},{h - 1.5:.2f}) -- ({lx + 0.5:.2f},{h - 1.5:.2f});")
    out.append(f"\\node[anchor=west] at ({lx + 0.55:.2f},{h - 1.5:.2f}) {{heads-up}};")
    out.append(f"\\draw[black,line width=1pt,dashed] ({lx:.2f},{h - 1.95:.2f}) -- ({lx + 0.5:.2f},{h - 1.95:.2f});")
    out.append(f"\\node[anchor=west] at ({lx + 0.55:.2f},{h - 1.95:.2f}) {{six-max}};")
    out.append("\\end{tikzpicture}")
    return out


def write(name: str, lines: list[str]) -> None:
    (OUT / name).write_text("\n".join(lines) + "\n")


def main() -> None:
    s = json.loads(SUMMARY.read_text())
    write("macros.tex", macros(s))
    write("ranking.tex", ranking_table(s))
    write("pat.tex", pat_table(s))
    write("vsdraw.tex", vs_draw_table(s))
    write("second.tex", second_card_table(s))
    write("outs.tex", outs_table(s))
    write("rule.tex", rule_table(s))
    write("showdown.tex", showdown_table(s))
    write("bots.tex", bots_table(s))
    write("patfig.tex", pat_figure(s))
    print(f"wrote {OUT}/*.tex")


if __name__ == "__main__":
    main()
