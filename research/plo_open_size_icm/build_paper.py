"""Generate the paper's numbers, tables and TikZ figures from the sizing experiment summaries.

Reads tmp/plo_sizing/summary.json (equal 30bb stacks, open and 3-bet arms) and
tmp/plo_sizing_stacks/summary.json (uneven tables) and writes generated/*.tex for paper.tex.

    .venv/bin/python research/plo_open_size_icm/build_paper.py
    cd research/plo_open_size_icm && pdflatex -output-directory output paper.tex (twice)
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EQUAL = ROOT / "tmp" / "plo_sizing" / "summary.json"
UNEVEN = ROOT / "tmp" / "plo_sizing_stacks" / "summary.json"
OUT = HERE / "generated"
SEATS = ("UTG", "HJ", "CO", "BTN", "SB")
DOLLARS_PER_UNIT = 8602 / (60 * 30)
SIZE_NAME = {2.0: "2x", 2.5: "2.5x", 3.0: "3x", 0.0: "pot"}
SIZE_COLOR = {2.0: "sizetwo", 2.5: "sizetwofive", 3.0: "sizethree"}
TABLE_ORDER = ("A1", "A2", "B1", "B2")
TABLE_NAME = {"A1": "Deep UTG vs short", "A2": "Deep BTN vs short blinds", "B1": "Short UTG vs deep",
              "B2": "Short BTN vs deep blinds"}


def signed(x: float, digits: int = 3) -> str:
    text = f"{abs(x):.{digits}f}"
    return f"$+{text}$" if x > 0 else f"$-{text}$" if x < 0 else f"${text}$"


def equal_arms(summary: dict) -> dict:
    arms = defaultdict(list)
    for arm in summary.values():
        arms[(arm["chip_ev"], arm["open_x"], arm["three_f"])].append(arm)
    return arms


def first_in(runs: list, seat: str) -> list[float]:
    return [r["values"]["first_in"][seat]["value"] for r in runs]


def equal_section(arms: dict) -> tuple[list[str], dict]:
    pot = arms[(False, 0.0, 1.0)]
    rows, macros = [], {}
    figure = []
    lo, hi, width = -0.03, 0.045, 11.0
    x = lambda v: (v - lo) / (hi - lo) * width  # noqa: E731
    for i, seat in enumerate(SEATS):
        base = np.mean(first_in(pot, seat))
        cells = []
        y = (len(SEATS) - 1 - i) * 1.0
        figure.append(f"\\node[anchor=east,font=\\small] at (-0.15,{y}) {{{seat}}};")
        for k, size in enumerate((2.0, 2.5, 3.0)):
            runs = [v - base for v in first_in(arms[(False, size, 1.0)], seat)]
            mean = float(np.mean(runs))
            cells.append(signed(mean))
            yy = y + (k - 1) * 0.22
            figure.append(f"\\draw[{SIZE_COLOR[size]},line width=1.6pt,opacity=.45] ({x(min(runs)):.3f},{yy:.2f}) -- "
                          f"({x(max(runs)):.3f},{yy:.2f});")
            figure.append(f"\\fill[{SIZE_COLOR[size]}] ({x(mean):.3f},{yy:.2f}) circle (2.3pt);")
        gap = max(abs(a - b) for a, b in (first_in(arms[(False, s, 1.0)], seat) for s in (2.0, 2.5, 3.0, 0.0)))
        freq2 = np.mean([r["values"]["first_in"][seat]["frequency"] for r in arms[(False, 2.0, 1.0)]], axis=0)
        freqp = np.mean([r["values"]["first_in"][seat]["frequency"] for r in pot], axis=0)
        rows.append(f"{seat} & {' & '.join(cells)} & ${gap:.3f}$ & {freq2[2]:.0%} / {freq2[1]:.0%} & "
                    f"{freqp[2]:.0%} / {freqp[1]:.0%} \\\\".replace("%", "\\%"))
    axis = [f"\\draw[gray!60] ({x(v):.3f},-0.6) -- ({x(v):.3f},{len(SEATS) - 0.4});" for v in (-0.03, -0.02, -0.01, 0.01, 0.02, 0.03, 0.04)]
    axis.append(f"\\draw[black,line width=.8pt] ({x(0):.3f},-0.6) -- ({x(0):.3f},{len(SEATS) - 0.4});")
    labels = [f"\\node[font=\\scriptsize,anchor=north] at ({x(v):.3f},-0.65) {{{'pot' if v == 0 else f'{v:+.2f}'}}};"
              for v in (-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04)]
    tikz = ["\\begin{tikzpicture}[x=1cm,y=0.85cm]", *axis, *labels, *figure,
            f"\\node[font=\\scriptsize,anchor=north east] at ({width},-1.15) {{value relative to a pot open (units of prize equity)}};",
            "\\end{tikzpicture}"]
    seat_means = {s: float(np.mean([np.mean(first_in(arms[(False, size, 1.0)], seat)) - np.mean(first_in(pot, seat))
                                    for seat in SEATS])) for s, size in (("Two", 2.0), ("TwoFive", 2.5), ("Three", 3.0))}
    for key, value in seat_means.items():
        macros[f"EqAvg{key}"] = signed(value)
    largest = max(abs(np.mean(first_in(arms[(False, s, 1.0)], seat)) - np.mean(first_in(pot, seat)))
                  for s in (2.0, 2.5, 3.0) for seat in SEATS)
    macros["EqLargest"] = f"{largest:.3f}"
    macros["EqLargestDollars"] = f"{largest * DOLLARS_PER_UNIT:.2f}"
    macros["NodesTwo"] = f"{pot[0]['meta']['nodes'] / 1e6:.1f}"
    macros["NodesTwoX"] = f"{arms[(False, 2.0, 1.0)][0]['meta']['nodes'] / 1e6:.1f}"
    return rows, macros, tikz


def three_bet_section(arms: dict) -> tuple[list[str], dict]:
    opens = {o for (c, o, f) in arms if not c and f != 1.0}
    best_open = opens.pop()
    pot = arms[(False, best_open, 1.0)]
    pairs = list(pot[0]["values"]["facing_open"])
    rows, macros = [], {"ThreeOpen": SIZE_NAME[best_open]}
    for frac, name in ((0.5, "Half"), (0.75, "ThreeQ")):
        diffs, wins, beyond = [], 0, []
        for pair in pairs:
            runs = {f: [r["values"]["facing_open"][pair]["value"] for r in arms[(False, best_open, f)]] for f in (0.5, 0.75, 1.0)}
            means = {f: float(np.mean(v)) for f, v in runs.items()}
            gap = max(abs(v[0] - v[1]) for v in runs.values())
            d = means[frac] - means[1.0]
            diffs.append(d)
            if max(means, key=means.get) == frac or abs(d) < 1e-6:
                wins += 1
            if d > gap:
                beyond.append(f"{pair.replace('>', ' vs ')} ({signed(d)} against a gap of ${gap:.3f}$)")
        macros[f"Three{name}Mean"] = signed(float(np.mean(diffs)))
        rows.append(f"{'$\\frac12$' if frac == 0.5 else '$\\frac34$'} pot & {signed(float(np.mean(diffs)))} & "
                    f"{signed(max(diffs))} & {wins} & {len(beyond)} \\\\")
        macros[f"Three{name}Beyond"] = "; ".join(beyond) if beyond else "none"
    return rows, macros


def uneven_section(summary: dict) -> tuple[list[str], dict, list[str]]:
    tables = defaultdict(lambda: defaultdict(list))
    for arm in summary.values():
        tables[arm["table"].split()[0]][arm["open_x"]].append(arm)
    rows, macros, figure = [], {}, []
    lo, hi, width = -0.10, 0.02, 9.0
    x = lambda v: (v - lo) / (hi - lo) * width  # noqa: E731
    for i, key in enumerate(TABLE_ORDER):
        sizes = tables[key]
        opener = "UTG" if "UTG" in TABLE_NAME[key] else "BTN"
        stacks = " / ".join(f"{s:g}" for s in sizes[0.0][0]["stacks"])
        base = np.mean([r["values"]["first_in"][opener]["value"] for r in sizes[0.0]])
        gap = max(abs(r[0]["values"]["first_in"][opener]["value"] - r[1]["values"]["first_in"][opener]["value"])
                  for r in sizes.values())
        y = (len(TABLE_ORDER) - 1 - i) * 1.25
        figure.append(f"\\fill[noise] ({x(-gap):.3f},{y - 0.42:.2f}) rectangle ({x(gap):.3f},{y + 0.42:.2f});")
        figure.append(f"\\node[anchor=east,font=\\small,align=right] at (-0.15,{y}) {{{TABLE_NAME[key]}\\\\[-1pt]"
                      f"{{\\scriptsize {stacks}}}}};")
        for k, size in enumerate((2.0, 2.5)):
            d = float(np.mean([r["values"]["first_in"][opener]["value"] for r in sizes[size]]) - base)
            yy = y + 0.17 - k * 0.34
            figure.append(f"\\fill[{SIZE_COLOR[size]}] ({x(d):.3f},{yy - 0.13:.2f}) rectangle ({x(0):.3f},{yy + 0.13:.2f});")
            figure.append(f"\\node[anchor=east,font=\\scriptsize] at ({x(d) - 0.05:.3f},{yy:.2f}) {{{signed(d)}}};")
        for size in (2.0, 2.5, 0.0):
            runs = sizes[size]
            values = [r["values"]["first_in"][opener]["value"] for r in runs]
            freq = np.mean([r["values"]["first_in"][opener]["frequency"] for r in runs], axis=0)
            facing = [v for r in runs for k2, v in r["values"]["facing_open"].items() if k2.startswith(opener + ">")]
            call = np.mean([f["frequency"][1] for f in facing])
            d = float(np.mean(values) - base)
            label = {2.0: TABLE_NAME[key], 2.5: f"{{\\scriptsize {stacks}}}", 0.0: ""}[size]
            rows.append(f"{label} & {SIZE_NAME[size]} & {signed(d) if size else '$0$'} & ${abs(values[0] - values[1]):.3f}$ & "
                        f"{freq[2]:.0%} & {freq[1]:.0%} & {freq[0]:.0%} & {call:.0%} \\\\".replace("%", "\\%"))
        rows.append("\\midrule" if i < len(TABLE_ORDER) - 1 else "")
        word = key[0] + {"1": "One", "2": "Two"}[key[1]]
        macros[f"Gap{word}"] = f"{gap:.3f}"
        macros[f"Two{word}"] = signed(float(np.mean([r["values"]["first_in"][opener]["value"] for r in sizes[2.0]]) - base))
    axis = [f"\\draw[gray!60] ({x(v):.3f},-0.75) -- ({x(v):.3f},{(len(TABLE_ORDER) - 1) * 1.25 + 0.6});" for v in (-0.1, -0.08, -0.06, -0.04, -0.02)]
    axis.append(f"\\draw[black,line width=.8pt] ({x(0):.3f},-0.75) -- ({x(0):.3f},{(len(TABLE_ORDER) - 1) * 1.25 + 0.6});")
    labels = [f"\\node[font=\\scriptsize,anchor=north] at ({x(v):.3f},-0.8) {{{'pot' if v == 0 else f'{v:+.2f}'}}};"
              for v in (-0.1, -0.08, -0.06, -0.04, -0.02, 0.0)]
    tikz = ["\\begin{tikzpicture}[x=1cm,y=1cm]", *figure[:0], *[f for f in figure if f.startswith("\\fill[noise]")], *axis,
            *labels, *[f for f in figure if not f.startswith("\\fill[noise]")],
            f"\\node[font=\\scriptsize,anchor=north east] at ({width},-1.3) {{opener value relative to a pot open}};",
            "\\end{tikzpicture}"]
    return rows, macros, tikz


def main() -> int:
    equal = json.loads(EQUAL.read_text())
    uneven = json.loads(UNEVEN.read_text())
    arms = equal_arms(equal)
    eq_rows, macros, eq_tikz = equal_section(arms)
    three_rows, three_macros = three_bet_section(arms)
    un_rows, un_macros, un_tikz = uneven_section(uneven)
    macros |= three_macros | un_macros
    macros["DollarsPerUnit"] = f"{DOLLARS_PER_UNIT:.2f}"
    macros["Solves"] = str(len(equal) + len(uneven))
    OUT.mkdir(exist_ok=True)
    (OUT / "macros.tex").write_text("\n".join(f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in macros.items()) + "\n")
    # Whole tabulars: an \\input between rows and \\bottomrule breaks booktabs.
    def tabular(spec: str, head: str, rows: list[str]) -> str:
        return "\n".join([f"\\begin{{tabular}}{{{spec}}}", "\\toprule", head, "\\midrule", *rows,
                          "\\bottomrule", "\\end{tabular}"]) + "\n"
    (OUT / "equal_table.tex").write_text(tabular(
        "lrrrrrr", "Seat & 2x & 2.5x & 3x & Run gap & 2x raise / limp & Pot raise / limp \\\\", eq_rows))
    (OUT / "three_table.tex").write_text(tabular(
        "lrrrr", "3-bet & Mean vs pot & Largest gain & Pairs where best & Gains beyond run gap \\\\",
        three_rows + ["pot & $0$ & reference & 9 & -- \\\\"]))
    (OUT / "uneven_table.tex").write_text(tabular(
        "llrrrrrr", "Table & Open & vs pot & Run gap & Raise & Limp & Fold & Others call \\\\",
        [r for r in un_rows if r]))
    (OUT / "fig_equal.tex").write_text("\n".join(eq_tikz) + "\n")
    (OUT / "fig_uneven.tex").write_text("\n".join(un_tikz) + "\n")
    print("\n".join(f"{k} = {v}" for k, v in macros.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
