"""แก้ชาร์ต GGPoker All-in or Fold ทุกที่นั่งทุกสถานการณ์ล่วงหน้า แล้วรวมเป็น PDF เล่มเดียว

สเตกต่ำสุด Hold'em $0.05/$0.10 ซื้อเข้า $1 = 10bb ไม่มี ante ค่าธรรมเนียม 0.2bb ต่อคนที่ถึง showdown
โต๊ะ 4 คนเป็นหลัก แต่ที่นั่งว่างบ่อย จึงแก้ 3 คนกับ heads-up ด้วย ตัวเลขทั้งหมดมาจาก pushfold_chart

ใช้:
    .venv/bin/python scripts/export_aof_charts.py
    .venv/bin/python scripts/export_aof_charts.py --stacks 10 9 8 --out tmp/aof/aof-holdem-nl10.pdf
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))

from PIL import Image, ImageDraw  # noqa: E402

import chart_image  # noqa: E402
import preflop  # noqa: E402
import pushfold_chart  # noqa: E402
from pushfold import floor  # noqa: E402

TABLE_SIZES = (4, 3, 2)
DEFAULT_STACKS = (10,)
DEFAULT_OUT = ROOT / "tmp" / "aof" / "aof-holdem-nl10.pdf"
SOURCE_URL = "https://ggpoker.com/poker-games/all-in-or-fold/"
COPYRIGHT = "© 2026 Nuttakit Kundum. All rights reserved."
COVER_LINES = (
    ("GGPoker All-in or Fold · Hold'em $0.05/$0.10", "title"),
    ("Push/fold Nash charts, chip EV, solved with the fee", "dim"),
    ("", "text"),
    ("Table     4-max (3-handed and heads-up when seats are empty)", "text"),
    ("Blinds    SB $0.05 = 0.5bb, BB $0.10 = 1bb, no ante", "text"),
    ("Stacks    buy-in $1 = 10bb, everyone the same", "text"),
    ("Fee       rake 0.06bb + jackpot 0.07bb + All-In Fortune $0.007 (0.07bb)", "text"),
    ("          = {fee:g}bb per player in a showdown, taken outside the pot", "text"),
    ("          (the hand history never shows it: collected = total pot)", "dim"),
    ("Assumed   folds and uncontested shoves pay no fee", "dim"),
    ("", "text"),
    ("Colours   red shove · green call · blue fold · lighter = mixed", "text"),
    ("", "text"),
    ("Source    " + SOURCE_URL + " (checked 2026-09-26)", "dim"),
    ("", "text"),
    (COPYRIGHT, "dim"),
)


def request_for(players: int, stack: float) -> preflop.Request:
    return preflop.Request(game="cash", stack=stack, players=players, aof=True)


def charts(players: int, stack: float) -> list[pushfold_chart.Solved]:
    """ทุกจุดตัดสินใจของโต๊ะนี้ เปิดก่อนเรียงตามที่นั่ง แล้วตามด้วยเจอคน shove"""
    request = request_for(players, stack)
    result = pushfold_chart.solve_table(request)
    names = result.spot.names
    nodes = sorted(result.tree.nodes, key=lambda n: (n.facing, n.seat, n.history))
    return [pushfold_chart.chart_for(request, result, names[n.seat], n.history) for n in nodes]


def _page(solved: pushfold_chart.Solved) -> Image.Image:
    png = chart_image.render(solved.book, solved.chart, lang="EN", notes=(solved.note,))
    return Image.open(io.BytesIO(png)).convert("RGB")


def _cover(width: int, height: int) -> Image.Image:
    page = Image.new("RGB", (width, height), chart_image.BACKGROUND)
    draw = ImageDraw.Draw(page)
    fonts = {"title": chart_image._font(chart_image.TITLE_SIZE),
             "text": chart_image._font(chart_image.NOTE_SIZE),
             "dim": chart_image._font(chart_image.NOTE_SIZE)}
    colours = {"title": chart_image.TEXT, "text": chart_image.TEXT, "dim": chart_image.DIM}
    y = chart_image.MARGIN
    for line, style in COVER_LINES:
        draw.text((chart_image.MARGIN, y), line.format(fee=pushfold_chart.AOF_FEE),
                  font=fonts[style], fill=colours[style])
        y += chart_image.LINE_H if style == "title" else chart_image.NOTE_H + 4
    return page


def _uniform(pages: list[Image.Image]) -> list[Image.Image]:
    """ทุกหน้าขนาดเท่ากัน PDF จะได้ไม่กระโดดเวลาเลื่อน"""
    width = max(p.width for p in pages)
    height = max(p.height for p in pages)
    out = []
    for p in pages:
        sheet = Image.new("RGB", (width, height), chart_image.BACKGROUND)
        sheet.paste(p, (0, 0))
        out.append(sheet)
    return out


def export(stacks: tuple[float, ...], out: pathlib.Path) -> dict:
    """แก้ทุกโต๊ะ เขียน PDF กับ JSON ของชาร์ตไว้ข้างกัน คืนสรุปจำนวนหน้าและเวลา"""
    began = time.perf_counter()
    solved = [s for stack in stacks for players in TABLE_SIZES for s in charts(players, stack)]
    pages = _uniform([_page(s) for s in solved])
    cover = _cover(pages[0].width, pages[0].height)
    out.parent.mkdir(parents=True, exist_ok=True)
    cover.save(out, format="PDF", save_all=True, append_images=pages, resolution=110)
    data = [{"book": s.book, "chart": s.chart, "note": s.note} for s in solved]
    out.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    return {"charts": len(solved), "pages": len(pages) + 1,
            "seconds": round(time.perf_counter() - began, 1), "pdf": str(out)}


def main() -> int:
    parser = argparse.ArgumentParser(description="ส่งออกชาร์ต GGPoker All-in or Fold เป็น PDF")
    parser.add_argument("--stacks", type=float, nargs="+", default=list(DEFAULT_STACKS),
                        help="สแตกเป็น bb ค่าเริ่ม 10 (ซื้อเข้าเต็ม $1)")
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    stacks = tuple(int(s) if float(s).is_integer() else s for s in args.stacks)
    print(json.dumps(export(stacks, args.out), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
