"""Hand-review episode: one content file -> the video's slides and the website's hand-review data.

    .venv/bin/python scripts/hand_review.py --content tmp/plo5/handreview/<tag>/content.json \
        --hh <session.txt> --review <review dir> --entries 57 --finish 11 --payouts 113.80,... \
        --slides tmp/plo5/handreview/<tag>/slides.json --site public/static/hand-review/<tag>.json

content.json (written per episode, Thai):
  {"engine": "gemini", "voice": "Charon", "session": {...facts...},
   "intro": [{"html": "...", "narration": "..."}], "outro": [...],
   "hands": [{"time": "10:26", "position": "BB", "title": "...", "theme": "ICM", "summary": "(site)",
              "setup": ["bullet", ...], "setup_narration": "...",
              "decisions": [{"index": 2, "comment": "(site)", "narration": "..."}],
              "lesson": "(site + slide)", "lesson_narration": "..."}]}
Decision indexes point into the hand's rated decisions (plo5_dashboard.collect order). Numbers on the
slides and the site come from the solves, never from the script.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plo5_dashboard import collect  # noqa: E402
from session_grades import grade  # noqa: E402
from plo5_progress import trusted  # noqa: E402

STREETS = ("Preflop", "Flop", "Turn", "River")
GLYPH = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
RANKS = "AKQJT98765432"
COLOR = {"raise": "#C6322A", "call": "#B98A45", "fold": "#3E5C9A"}


def label(option: str, street: int, to_call: float, pot: float) -> str:
    """English action names: a first-in call of the big blind preflop is a limp."""
    if option == "Call" and street == 0 and abs(to_call - 1.0) < 1e-9 and pot <= 3.2:
        return "Limp"
    return option


def kind(option: str) -> str:
    return "raise" if option.startswith(("Raise", "Bet")) else "call" if option.startswith(("Call", "Check", "Limp")) else "fold"


def cards_html(text: str) -> str:
    return '<span class="cards">' + "".join(f'<span class="card s-{text[i + 1]}">{text[i]}{GLYPH[text[i + 1]]}</span>'
                                            for i in range(0, len(text), 2)) + "</span>"


def cell_name(key: int) -> str:
    row, col = divmod(key, 13)
    if row == col:
        return RANKS[row] * 2
    return RANKS[row] + RANKS[col] + "s" if row < col else RANKS[col] + RANKS[row] + "o"


def chart_html(d: dict, options: list[str]) -> str:
    order = sorted(range(len(options)), key=lambda i: "rcf".index(kind(options[i])[0]))
    mine = set(d["chart"]["hero_cells"]) if d.get("chart") else set()
    cells = []
    for key, c in enumerate(d["chart"]["cells"] if d.get("chart") else []):
        bars = "" if c[0] <= 0 else "".join(f'<i style="width:{c[1 + i] * 100:.1f}%;background:{COLOR[kind(options[i])]}"></i>'
                                             for i in order if c[1 + i] > 0.001)
        cls = ("faint " if 0 < c[0] < 0.05 else "") + ("mine" if key in mine else "")
        cells.append(f'<div class="{cls.strip()}">{bars}<b>{cell_name(key)}</b></div>')
    legend = "".join(f'<span><i style="background:{COLOR[kind(options[i])]}"></i>{options[i]}</span>' for i in order)
    return f'<div><div class="chart13">{"".join(cells)}</div><div class="legend13">{legend}<span>กรอบขาว = มือเรา</span></div></div>'


def decision_view(h: dict, d: dict) -> dict:
    options = [label(o, d["street"], d["to_call"], d["pot"]) for o in d["options"]]
    return {"street": STREETS[d["street"]], "board": d["board"], "pot": d["pot"], "to_call": d["to_call"],
            "options": options, "mix": [round(m, 3) for m in d["mix"]], "values": d["values"], "took": d["took"],
            "best": d["best"], "loss": d["loss"], "grade": grade(d) if trusted(h, d) else "?",
            "real": d["real"], "real_bb": d["real_bb"], "all_in": d["all_in"], "chart": d.get("chart")}


def decision_slide(n: int, hand: dict, h: dict, view: dict) -> str:
    rows = []
    for i, option in enumerate(view["options"]):
        you = " you" if i == view["took"] else ""
        rows.append(f'<div class="opt{you}"><span>{option}</span><span class="barbox"><i style="width:{view["mix"][i] * 100:.1f}%;'
                    f'background:{COLOR[kind(option)]}"></i></span><span class="p">{view["mix"][i] * 100:.0f}%</span>'
                    f'<span class="v">${view["values"][i]:.2f}</span></div>')
    grade_tag = {"A": ("A", "A game"), "B": ("B", "B game"), "C": ("C", "C game")}.get(view["grade"], ("B", "?"))
    board = f'{view["street"]} {cards_html(view["board"])}' if view["board"] else "Preflop"
    to_call = f'call {view["to_call"]:.1f}bb' if view["to_call"] else "ไม่มี bet ให้ call"
    return (f'<p class="eyebrow">มือที่ {n} · {html.escape(hand["title"])}</p>'
            f'<div class="split"><div style="display:grid;gap:26px">'
            f'<h2 style="font-size:52px">{board}</h2>'
            f'<p class="board">{h["position"]} {cards_html(h["cards"])} · pot {view["pot"]:.1f}bb · {to_call}</p><p style="font:500 24px IBM Plex Sans Thai Looped;color:var(--muted)">pot ตามเกม solver ที่ bet ขนาด pot</p>'
            f'<div class="panel opts"><p style="font:600 26px IBM Plex Sans Thai Looped;color:#636A7A">solver เลือกกี่ % · equity ในทัวร์ ($)</p>{"".join(rows)}</div>'
            f'<span class="tag {grade_tag[0]}" style="justify-self:start;font-size:30px">{grade_tag[1]}</span></div>'
            f'{chart_html(view, view["options"])}</div>')


def build(content: dict, data: dict) -> tuple[dict, dict]:
    hands_data = {(h["time"], h["position"]): h for h in data["hands"]}
    slides = list(content.get("intro", []))
    site_hands = []
    for n, hand in enumerate(content["hands"], 1):
        h = hands_data[(hand["time"], hand["position"])]
        views = [decision_view(h, h["decisions"][d["index"]]) for d in hand["decisions"]]
        setup = "".join(f"<li>{item}</li>" for item in hand["setup"])
        slides.append({"html": f'<p class="eyebrow">มือที่ {n} · {html.escape(hand["theme"])}</p><h2><span class="hoof"></span>{html.escape(hand["title"])}</h2>'
                               f'<div class="row" style="align-items:center;gap:40px"><div class="panel" style="font-size:40px">{cards_html(h["cards"])}</div>'
                               f'<p class="board">{h["position"]} · {h["players"]} คนบนโต๊ะ · สแตก {h["stack_bb"]:g}bb · เหลือในทัวร์ราว {h.get("left") or "?"} คน · Level {h["level"]} ({h["blinds"]})</p></div>'
                               f'<ul class="lede">{setup}</ul>',
                       "narration": hand["setup_narration"]})
        for d, view in zip(hand["decisions"], views):
            slides.append({"html": decision_slide(n, hand, h, view), "narration": d["narration"]})
        slides.append({"html": f'<p class="eyebrow">มือที่ {n} · บทเรียน</p><h2><span class="hoof"></span>{html.escape(hand["title"])}</h2>'
                               f'<div class="panel" style="font-size:40px;line-height:1.5">{hand["lesson"]}</div>',
                       "narration": hand["lesson_narration"]})
        site_hands.append({"n": n, "title": hand["title"], "theme": hand["theme"], "summary": hand["summary"],
                           "lesson": hand["lesson"], "position": h["position"], "players": h["players"],
                           "stack_bb": h["stack_bb"], "left": h.get("left"), "level": h["level"], "blinds": h["blinds"],
                           "cards": h["cards"], "board": h["board"], "line": h["line"],
                           "decisions": [{**v, "comment": d["comment"]} for d, v in zip(hand["decisions"], views)]})
    slides += content.get("outro", [])
    spec = {"engine": content.get("engine", "gemini"), "voice": content.get("voice", "Charon"),
            "speed": content.get("speed", 1.0), "brand": content.get("brand", "รีวิวมือ"), "slides": slides}
    site = {"session": content["session"], "hands": site_hands}
    return spec, site


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--hh", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--entries", type=int, required=True)
    parser.add_argument("--finish", type=int, required=True)
    parser.add_argument("--payouts", required=True)
    parser.add_argument("--slides", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    args = parser.parse_args()
    content = json.loads(args.content.read_text())
    data = collect(args.hh, args.review, "", args.entries, args.finish, tuple(float(x) for x in args.payouts.split(",")))
    spec, site = build(content, data)
    args.slides.parent.mkdir(parents=True, exist_ok=True)
    args.slides.write_text(json.dumps(spec, ensure_ascii=False, indent=1))
    args.site.parent.mkdir(parents=True, exist_ok=True)
    args.site.write_text(json.dumps(site, ensure_ascii=False, separators=(",", ":")))
    chars = sum(len(s["narration"]) for s in spec["slides"])
    print(f"{len(spec['slides'])} slides, {chars} narration characters (~{chars / 13.5 / 60 + len(spec["slides"]) * 0.7 / 60:.0f} min with Gemini Charon), {len(site['hands'])} hands")


if __name__ == "__main__":
    main()
