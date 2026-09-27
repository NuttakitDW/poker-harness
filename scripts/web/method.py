"""หน้า /method: เทียบชาร์ต push/fold ของเรากับชาร์ตของ Jonathan Little (PokerCoaching) มือต่อมือ

แก้ spot เดียวกับชาร์ตของเขา (UTG, chip EV, 9 คน, ante 10% ของ BB ทุกคน) ด้วย solver ของเราเอง
แล้วเขียน public/method.html ใหม่ ตัวเลขทุกตัวบนหน้ามาจากการรันครั้งนี้ ไม่ได้พิมพ์เอง
ตัวเลขชุดเดียวกันเก็บไว้ที่ harnesses/charts/method-summary.json ให้ AI ในแชตตอบคำถามเรื่องความน่าเชื่อถือ
ชาร์ตของเขาเก็บไว้ที่ harnesses/charts/pokercoaching-pushfold-utg.json พร้อมลิงก์และวันที่ดึงมา

ใช้:
    make method        (ใช้เวลาราว 30 วินาที แก้ 12 โต๊ะ)
"""

from __future__ import annotations

import dataclasses
import html
import json
import pathlib
import re
import string
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT))

import preflop  # noqa: E402
import pushfold_chart  # noqa: E402
from pushfold import floor, hands, icm_pricer, pricer  # noqa: E402
from pushfold.spot import position_names  # noqa: E402

REFERENCE = ROOT / "harnesses" / "charts" / "pokercoaching-pushfold-utg.json"
TEMPLATE = pathlib.Path(__file__).resolve().parent / "method_template.html"
PAGE = ROOT / "public" / "method.html"
SUMMARY = ROOT / "harnesses" / "charts" / "method-summary.json"  # assistant.py อ่านไฟล์นี้
RANKS = "AKQJT98765432"
GRID = list(hands.CLASSES)  # แถวละ 13 มือ AA AKs ... ตรงกับตารางของ solver
MAIN_STACK = 10
TABLE_STACKS = (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)
PLAYERS, ANTE, HERO = 9, 0.1, "UTG"
CLOSE_CALL_BB = 0.05  # ต่างกันไม่เกินนี้ถือว่าเกือบเท่ากัน


def load_reference(path: pathlib.Path = REFERENCE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pair(rank: str) -> str:
    return rank * 2


def expand(text: str) -> set[str]:
    """ช่วงมือแบบที่ชาร์ตทั่วไปเขียน เช่น 44+, A8s+, A5s-A4s, KQo, Ax, 9x+ เป็นเซตของมือ"""
    found: set[str] = set()
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        if m := re.fullmatch(r"([AKQJT2-9])x(\+?)", part):
            high = RANKS.index(m[1])
            tops = range(high + 1) if m[2] else (high,)
            for top in tops:
                found |= {h for h in GRID if h[0] == RANKS[top]}
        elif m := re.fullmatch(r"([AKQJT2-9])\1\+", part):
            found |= {_pair(RANKS[k]) for k in range(RANKS.index(m[1]) + 1)}
        elif m := re.fullmatch(r"([AKQJT2-9])([AKQJT2-9])([so])\+", part):
            found |= {m[1] + RANKS[k] + m[3] for k in range(RANKS.index(m[1]) + 1, RANKS.index(m[2]) + 1)}
        elif m := re.fullmatch(r"([AKQJT2-9])([AKQJT2-9])([so])-\1([AKQJT2-9])\3", part):
            found |= {m[1] + RANKS[k] + m[3] for k in range(RANKS.index(m[2]), RANKS.index(m[4]) + 1)}
        elif part in GRID:
            found.add(part)
        else:
            raise ValueError(f"อ่านช่วงมือไม่ออก: {part}")
    return found


def combos(hand: str) -> int:
    return 6 if len(hand) == 2 else 4 if hand[2] == "s" else 12


def percent(chosen: set[str]) -> float:
    return 100 * sum(combos(hand) for hand in chosen) / 1326


@dataclasses.dataclass(frozen=True)
class Comparison:
    stack: float
    ours: dict[str, float]      # ความถี่ shove ของเราต่อมือ
    theirs: set[str]            # มือที่ชาร์ตของเขา shove
    gaps: dict[str, float]      # EV(shove) - EV(fold) เป็น bb เมื่อทุกคนเล่นตามทางแก้ของเรา
    theirs_percent: float
    exploitability: float
    seconds: float

    def ours_shoves(self, hand: str) -> bool:
        """ตัดสินมือที่ solver ผสมด้วย action หลัก ครึ่งต่อครึ่งนับเป็น shove"""
        return self.ours[hand] >= 0.5

    @property
    def differ(self) -> list[str]:
        return [hand for hand in GRID if self.ours_shoves(hand) != (hand in self.theirs)]

    @property
    def matched(self) -> int:
        return len(GRID) - len(self.differ)

    @property
    def ours_percent(self) -> float:
        return 100 * sum(combos(hand) * self.ours[hand] for hand in GRID) / 1326


def solve(stack: float, reference: dict) -> Comparison:
    """แก้ UTG first-in ด้วย solver ของเรา แล้วอ่าน EV ของ shove กับ fold ทีละมือจาก pricer"""
    request = preflop.Request(game="tournament", stack=stack, hero=HERO, scenario="RFI", players=PLAYERS,
                              pushfold=True, ante=ANTE, ante_mode="each", payouts=())
    result = pushfold_chart.solve_table(request)
    seat = position_names(PLAYERS).index(HERO)
    node = result.node(seat)
    plan = next(p for p in icm_pricer.plans_for(result.tree, None) if p.seat == seat)
    cfv, _ = plan.price(pricer.columns(result.strategy))
    values = cfv[list(plan.nodes).index(node.index)]
    shove = result.strategy[node.index][:, floor.JAM]
    row = reference["ranges"][str(round(stack))]
    return Comparison(stack=stack, ours={hand: float(shove[i]) for i, hand in enumerate(GRID)},
                      theirs=expand(row["range"]),
                      gaps={hand: float(values[i, floor.JAM] - values[i, floor.FOLD]) for i, hand in enumerate(GRID)},
                      theirs_percent=row["percent"], exploitability=result.exploitability, seconds=result.seconds)


# ---------- page ----------

def _cells(comparison: Comparison, ours: bool) -> str:
    out = []
    for hand in GRID:
        share = comparison.ours[hand] if ours else float(hand in comparison.theirs)
        state = "shove" if share >= 0.99 else "fold" if share <= 0.01 else "mix"
        differ = " differ" if hand in comparison.differ else ""
        who = f"เรา shove {share:.0%}" if ours else ("Jonathan: shove" if share else "Jonathan: fold")
        out.append(f'<div class="cell {state}{differ}" style="--p:{share * 100:.0f}%" title="{hand} · {who}">'
                   f"<span>{hand}</span></div>")
    return "\n".join(out)


def _reading(gap: float) -> str:
    if abs(gap) <= CLOSE_CALL_BB:
        return "เกือบเท่ากัน shove หรือ fold ก็ได้ผลแทบไม่ต่าง"
    return "fold ดีกว่าชัดเจน" if gap < 0 else "shove ดีกว่าชัดเจน"


def _diff_rows(comparison: Comparison) -> str:
    rows = []
    for hand in comparison.differ:
        gap = comparison.gaps[hand]
        theirs = "shove" if hand in comparison.theirs else "fold"
        rows.append(f"<tr><th scope=\"row\" class=\"mono\">{hand}</th>"
                    f"<td class=\"mono\">shove {comparison.ours[hand]:.0%}</td><td class=\"mono\">{theirs}</td>"
                    f"<td class=\"mono num\">{gap:+.3f}</td><td>{_reading(gap)}</td></tr>")
    return "\n".join(rows)


def _stack_rows(rows: list[Comparison]) -> str:
    out = []
    for c in rows:
        mark = ' class="now"' if c.stack == MAIN_STACK else ""
        out.append(f"<tr{mark}><th scope=\"row\" class=\"mono\">{c.stack:g}bb</th>"
                   f"<td class=\"mono num\">{c.ours_percent:.1f}%</td><td class=\"mono num\">{c.theirs_percent:.1f}%</td>"
                   f"<td class=\"mono num\">{c.matched}/169</td><td class=\"mono num\">{c.exploitability:.4f}</td></tr>")
    return "\n".join(out)


def render(main: Comparison, table: list[Comparison], reference: dict, before_ante_matched: int) -> str:
    widest = max(main.differ, key=lambda hand: abs(main.gaps[hand])) if main.differ else None
    close = sum(abs(main.gaps[hand]) <= CLOSE_CALL_BB for hand in main.differ)
    widest_text = "สองชาร์ตตรงกันทุกมือ" if widest is None else (
        f'มือที่ต่างกันมากที่สุดคือ <span class="mono">{widest}</span> ตามทางแก้ของเรา '
        f'{"fold ดีกว่า shove" if main.gaps[widest] < 0 else "shove ดีกว่า fold"} '
        f'<span class="mono">{abs(main.gaps[widest]):.2f}</span> bb ต่อครั้ง มือที่เหลือต่างกันแค่เศษเสี้ยวของ bb')
    values = {
        "matched": f"{main.matched}/169", "matched_count": str(main.matched),
        "match_pct": f"{100 * main.matched / 169:.1f}%",
        "ours_pct": f"{main.ours_percent:.1f}%", "theirs_pct": f"{main.theirs_percent:.1f}%",
        "exploit": f"{main.exploitability:.4f}", "exploit_100": f"{100 * main.exploitability:.2f}",
        "seconds": f"{main.seconds:.1f}", "differ_count": str(len(main.differ)),
        "close_count": str(close), "widest_text": widest_text,
        "theirs_range": html.escape(reference["ranges"][str(MAIN_STACK)]["range"]),
        "before_ante_matched": f"{before_ante_matched}/169",
        "ours_cells": _cells(main, ours=True), "theirs_cells": _cells(main, ours=False),
        "diff_rows": _diff_rows(main), "stack_rows": _stack_rows(table),
        "source_url": html.escape(reference["url"]), "retrieved_on": html.escape(reference["retrieved_on"]),
        "close_bb": f"{CLOSE_CALL_BB:.2f}",
    }
    return string.Template(TEMPLATE.read_text(encoding="utf-8")).substitute(values)


def summary(main: Comparison, table: list[Comparison], reference: dict) -> dict:
    """ตัวเลขบนหน้าในรูปที่ AI อ่านได้ ชื่อ field ต้องตรงกับที่ assistant.method_facts ใช้"""
    widest = max(main.differ, key=lambda hand: abs(main.gaps[hand])) if main.differ else None
    matched = [c.matched for c in table]
    return {
        # ไม่ใส่ .com เพราะ assistant.safe_text ตัดทุกอย่างที่หน้าตาเหมือนโดเมนออกจากคำตอบของโมเดล
        "reference": f"Jonathan Little's PokerCoaching push/fold chart (10% ante table, retrieved {reference['retrieved_on']})",
        "spot": f"{HERO} first in, {MAIN_STACK}bb, {PLAYERS}-handed, ante 10% of the big blind per player, chip EV",
        "matched": main.matched, "total": len(GRID),
        "ours_percent": round(main.ours_percent, 1), "theirs_percent": main.theirs_percent,
        "exploitability_bb": round(main.exploitability, 4), "differ": main.differ,
        "close_calls": sum(abs(main.gaps[hand]) <= CLOSE_CALL_BB for hand in main.differ),
        "close_bb": CLOSE_CALL_BB,
        "widest": {"hand": widest, "gap_bb": round(main.gaps[widest], 3)} if widest else None,
        "stacks": {"from": min(c.stack for c in table), "to": max(c.stack for c in table),
                   "matched_min": min(matched), "matched_max": max(matched)},
    }


def build() -> tuple[str, dict]:
    reference = load_reference()
    table = [solve(stack, reference) for stack in TABLE_STACKS]
    main = next(c for c in table if c.stack == MAIN_STACK)
    # ชาร์ตส่วนใหญ่นับ 10bb ก่อนจ่าย ante ของเรานับหลังจ่าย ลองแบบเขาด้วยว่ายังตรงกันเท่าเดิมไหม
    before_ante = solve(MAIN_STACK - ANTE, reference)
    return render(main, table, reference, before_ante.matched), summary(main, table, reference)


def main() -> int:
    page, facts = build()
    PAGE.write_text(page, encoding="utf-8")
    SUMMARY.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"เขียน {PAGE.relative_to(ROOT)} กับ {SUMMARY.relative_to(ROOT)} แล้ว")
    return 0


if __name__ == "__main__":
    sys.exit(main())
