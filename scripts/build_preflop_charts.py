#!/usr/bin/env python3
"""อ่านชาร์ตพรีฟล็อปจาก PDF ของ Jonathan Little ออกมาเป็นตารางที่โปรแกรมค้นได้

ตารางในไฟล์เป็นภาพ ไม่ใช่ข้อความ จึงอ่านหัวข้อด้วย pdftotext แล้วถอด action
จากสีของแต่ละช่องในภาพ แดงคือ raise เขียวคือ call น้ำเงินคือ fold
ช่องที่มีสองสีคือความถี่ผสม เก็บสัดส่วนไว้ตามที่วัดได้

ใช้:
    python3 scripts/build_preflop_charts.py --game tournament
    python3 scripts/build_preflop_charts.py --game cash --pages 8-12
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "harnesses" / "charts"

SEARCH_DIRS = (ROOT / "sources" / "pdf", ROOT)


def locate(filename: str) -> pathlib.Path:
    """หาไฟล์ PDF ในที่ที่เก็บต้นฉบับก่อน แล้วค่อยมองที่รากโปรเจกต์"""
    for folder in SEARCH_DIRS:
        candidate = folder / filename
        if candidate.exists():
            return candidate
    return SEARCH_DIRS[-1] / filename


GUIDES = {
    "cash": {
        "pdf": locate("The_Ultimate_Cash_Game_Preflop_Guide_LT.pdf"),
        "title": "Jonathan Little's Ultimate Cash Game Preflop Guide (2026)",
        "author": "Jonathan Little",
        "publisher": "PokerCoaching.com",
        "edition": "Cash Game Edition 2026",
    },
    "tournament": {
        "pdf": locate("The_Ultimate_Tournament_Preflop_Guide_LT.pdf"),
        "title": "Jonathan Little's Ultimate Tournament Preflop Guide (2026)",
        "author": "Jonathan Little",
        "publisher": "PokerCoaching.com",
        "edition": "Tournament Edition 2026",
    },
}

# ต้นฉบับ PDF ใหญ่เกินกว่าจะเก็บในที่เก็บโค้ด จึงเก็บแค่ลายนิ้วมือไว้ยืนยันว่าถอดจากไฟล์เดียวกัน
REBUILD_NOTE = ("ต้นฉบับ PDF ไม่ได้เก็บไว้ในที่เก็บโค้ดเพราะไฟล์ใหญ่เกินขีดของ GitHub "
                "ถ้าต้องถอดใหม่ ให้ดาวน์โหลดไฟล์ชื่อเดิมจาก PokerCoaching แล้วตรวจ sha256 ให้ตรง "
                "วางไว้ที่ sources/pdf/ แล้วรัน scripts/build_preflop_charts.py")

RANKS = "AKQJT98765432"
# ช่องสีดำในชาร์ต vs 3-bet ขึ้นไปคือมือที่ไม่ได้อยู่ในเรนจ์ที่เราเปิดมาตั้งแต่ต้น
# ไม่ใช่มือที่ fold ในสถานการณ์นั้น จึงต้องแยกออกจากกัน
ACTIONS = {"raise": (240, 60, 60), "call": (72, 168, 96), "fold": (61, 124, 184),
           "none": (0, 0, 0)}
CODES = {"raise": "R", "call": "C", "fold": "F", "none": "-"}
TOLERANCE = {"none": 40}
DEFAULT_TOLERANCE = 60
MIN_FREQUENCY = 0.05

_HEADER = re.compile(r"^\s*(\d+)\s*BB\s{2,}(.+?)\s*$", re.MULTILINE)
_TITLE = re.compile(
    r"^\s*([A-Z0-9+]+)(?:\s+vs\s+([A-Z0-9+]+))?\s*·\s*"
    r"([A-Za-z0-9-]+(?:\s+[A-Za-z0-9-]+)*)\s*$")


def hands() -> tuple[str, ...]:
    """ชื่อมือ 169 แบบตามลำดับช่องในตาราง ซ้ายไปขวา บนลงล่าง"""
    names = []
    for row, high in enumerate(RANKS):
        for col, low in enumerate(RANKS):
            if row == col:
                names.append(high * 2)
            elif row < col:
                names.append(f"{high}{low}s")
            else:
                names.append(f"{low}{high}o")
    return tuple(names)


HANDS = hands()


def read_ppm(path: pathlib.Path):
    """อ่านไฟล์ PPM เป็นอาร์เรย์ (สูง, กว้าง, 3) โดยไม่ต้องมีไลบรารีรูปภาพ"""
    import numpy

    data = path.read_bytes()
    fields: list[bytes] = []
    index = 0
    while len(fields) < 4:
        while data[index:index + 1].isspace():
            index += 1
        if data[index:index + 1] == b"#":
            while data[index:index + 1] != b"\n":
                index += 1
            continue
        start = index
        while not data[index:index + 1].isspace():
            index += 1
        fields.append(data[start:index])
    index += 1
    width, height = int(fields[1]), int(fields[2])
    pixels = numpy.frombuffer(data[index:index + width * height * 3], dtype=numpy.uint8)
    return pixels.reshape(height, width, 3)


def _lines(dark) -> list[int]:
    """ตำแหน่งเส้นตารางจากแถวหรือคอลัมน์ที่มืดเกินครึ่ง รวมเส้นหนาให้เหลือตำแหน่งเดียว"""
    import numpy

    hits = [int(value) for value in numpy.where(dark.mean(axis=1) > 0.5)[0]]
    if not hits:
        return []
    runs: list[list[int]] = [[hits[0]]]
    for position in hits[1:]:
        # เส้นหนาให้เป็นกลุ่มเดียว แล้วใช้จุดกลางของกลุ่มเป็นตำแหน่งเส้น
        if position - runs[-1][-1] <= 3:
            runs[-1].append(position)
            continue
        runs.append([position])
    return [round((run[0] + run[-1]) / 2) for run in runs]


def _edges(lines: list[int], extent: int) -> list[float]:
    """ขอบของ 13 ช่องจากตำแหน่งเส้นที่ตรวจได้ เติมขอบนอกให้ครบเมื่อจำเป็น

    เส้นที่ตรวจได้คือเส้นคั่นภายใน ขอบซ้ายสุดกับขวาสุดของตารางมักไม่มีเส้นวาดไว้
    จึงเติมเพิ่มหนึ่งช่วงเฉพาะด้านที่เหลือที่ว่างพอดีกับหนึ่งช่อง ด้านที่ว่างมากกว่านั้น
    คือหัวข้อหรือแถบความถี่ ไม่ใช่ช่องของตาราง
    """
    import statistics

    if len(lines) < 8:
        raise ValueError("เส้นตารางน้อยเกินกว่าจะวัดขนาดช่องได้")
    gap = statistics.median(second - first for first, second in zip(lines, lines[1:]))
    edges = [float(position) for position in lines]
    if extent - edges[-1] <= gap * 1.2:
        edges.append(edges[-1] + gap)
    if edges[0] <= gap * 1.2:
        edges.insert(0, edges[0] - gap)
    if len(edges) != 14:
        raise ValueError(f"ได้ขอบ {len(edges)} เส้น ต้องการ 14 เส้น")
    return edges


def _lines(dark) -> list[int]:
    """ตำแหน่งเส้นตารางจากแถวที่มืดเกินครึ่ง รวมเส้นหนาให้เหลือตำแหน่งเดียว"""
    import numpy

    hits = [int(value) for value in numpy.where(dark.mean(axis=1) > 0.5)[0]]
    if not hits:
        return []
    runs: list[list[int]] = [[hits[0]]]
    for position in hits[1:]:
        # เส้นหนาให้เป็นกลุ่มเดียว แล้วใช้จุดกลางของกลุ่มเป็นตำแหน่งเส้น
        if position - runs[-1][-1] <= 3:
            runs[-1].append(position)
            continue
        runs.append([position])
    return [round((run[0] + run[-1]) / 2) for run in runs]


def grid_edges(image) -> tuple[list[float], list[float]]:
    """ขอบแนวนอนและแนวตั้งของตาราง 13x13 ในภาพ"""
    dark = image.astype(int).sum(axis=2) < 150
    height, width = dark.shape
    return _edges(_lines(dark), height), _edges(_lines(dark.T), width)


def cell_actions(patch) -> dict[str, float]:
    """สัดส่วนของแต่ละ action ในหนึ่งช่อง ตัดสีที่น้อยกว่าเกณฑ์ทิ้ง"""
    import numpy

    flat = patch.reshape(-1, 3).astype(int)
    references = numpy.array([ACTIONS[name] for name in ACTIONS])
    limits = numpy.array([TOLERANCE.get(name, DEFAULT_TOLERANCE) for name in ACTIONS])
    distance = numpy.linalg.norm(flat[:, None, :] - references[None, :, :], axis=2)
    nearest = distance.argmin(axis=1)
    close = distance[numpy.arange(len(flat)), nearest] < limits[nearest]
    counted = nearest[close]
    if not len(counted):
        return {}
    shares = {}
    for position, name in enumerate(ACTIONS):
        share = float((counted == position).mean())
        if share >= MIN_FREQUENCY:
            shares[name] = round(share, 2)
    return shares


HEADER_RATIO = 0.115
MIN_COVERAGE = 0.7


def _patch(image, rows: list[float], columns: list[float], row: int, col: int):
    """ส่วนกลางของหนึ่งช่อง เว้นขอบไว้กันเส้นตารางกับตัวอักษรชื่อมือ"""
    top, bottom = rows[row], rows[row + 1]
    left, right = columns[col], columns[col + 1]
    # เว้นแค่พอเลี่ยงเส้นตาราง ถ้าเว้นกว้างจะวัดความถี่ของช่องที่แบ่งสีผิด
    inset_y = (bottom - top) * 0.08
    inset_x = (right - left) * 0.08
    return image[max(0, int(top + inset_y)):int(bottom - inset_y),
                 max(0, int(left + inset_x)):int(right - inset_x)]


def _coverage(image, rows: list[float], columns: list[float]) -> float:
    """สัดส่วนพิกเซลที่เป็นสี action จริง ใช้ตัดสินว่าวางตารางตรงช่องหรือไม่"""
    scores = [sum(cell_actions(_patch(image, rows, columns, row, col)).values())
              for row in range(13) for col in range(13)]
    return sum(scores) / len(scores)


def _geometries(image) -> list[tuple[list[float], list[float]]]:
    """ตารางที่เป็นไปได้ จากการวัดเส้น และจากสัดส่วนที่คาลิเบรตไว้

    การวัดเส้นพลาดได้เมื่อชาร์ตเกือบทั้งใบเป็นสีเดียว หรือมีเส้นแบ่งความถี่ในช่อง
    จึงมีสัดส่วนสำรองที่วัดจากชาร์ตที่ถอดถูกแล้วเป็นตัวเทียบ
    """
    height, width = image.shape[:2]
    found = []
    try:
        found.append(grid_edges(image))
    except ValueError:
        pass
    top = height * HEADER_RATIO
    found.append(([top + (height - top) * index / 13 for index in range(14)],
                  [width * index / 13 for index in range(14)]))
    return found


def decode(image) -> tuple[str, dict[str, dict[str, float]]]:
    """ถอดภาพหนึ่งใบเป็นรหัส action 169 ตัว กับสัดส่วนของช่องที่ผสมกัน"""
    best = max(_geometries(image), key=lambda edges: _coverage(image, *edges))
    if _coverage(image, *best) < MIN_COVERAGE:
        raise ValueError("วางตารางไม่ลงช่อง ภาพนี้อาจไม่ใช่ตารางเรนจ์")
    rows, columns = best
    codes: list[str] = []
    mixed: dict[str, dict[str, float]] = {}
    for row in range(13):
        for col in range(13):
            shares = cell_actions(_patch(image, rows, columns, row, col))
            if not shares:
                codes.append("?")
                continue
            best = max(shares, key=shares.get)
            codes.append(CODES[best])
            if len(shares) > 1:
                mixed[HANDS[row * 13 + col]] = shares
    return "".join(codes), mixed


MIN_CHART_WIDTH = 400


def is_chart(path: pathlib.Path) -> bool:
    """ภาพนี้เป็นตารางจริงไหม

    pdfimages คายทั้งภาพจริงและหน้ากากโปร่งใสของมันออกมาเป็น ppm เหมือนกัน
    หน้ากากเป็นภาพสีเทาล้วน จึงคัดออกด้วยการดูว่าสามช่องสีเท่ากันหมดหรือไม่
    และคัดโลโก้เล็ก ๆ ออกด้วยขนาด
    """
    image = read_ppm(path)
    if image.shape[1] < MIN_CHART_WIDTH:
        return False
    sample = image[::7, ::7].astype(int)
    return bool((sample[:, :, 0] != sample[:, :, 1]).any())


def page_titles(pdf: pathlib.Path, page: int) -> tuple[int | None, str, list[dict]]:
    """สแตก หัวข้อหมวด และชื่อชาร์ตทุกใบในหน้านั้น ตามลำดับที่วางบนหน้า"""
    text = subprocess.run(
        ["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(pdf), "-"],
        capture_output=True, text=True, check=True).stdout
    header = _HEADER.search(text)
    stack = int(header.group(1)) if header else None
    section = header.group(2).strip() if header else ""

    found: list[dict] = []
    for line in text.splitlines():
        for part in re.split(r"\s{3,}", line.strip()):
            match = _TITLE.match(part.strip())
            if not match:
                continue
            hero, villain, scenario = match.groups()
            found.append({"hero": hero, "villain": villain, "scenario": scenario})
    return stack, section, found


def page_charts(pdf: pathlib.Path, page: int) -> list[dict]:
    """ชาร์ตทุกใบในหนึ่งหน้า พร้อมตารางที่ถอดแล้ว"""
    stack, section, titles = page_titles(pdf, page)
    if stack is None or not titles:
        return []
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(["pdfimages", "-f", str(page), "-l", str(page), str(pdf),
                        f"{folder}/chart"], check=True)
        images = [path for path in sorted(pathlib.Path(folder).glob("chart-*.ppm"))
                  if is_chart(path)]
        if len(images) != len(titles):
            print(f"  หน้า {page}: ภาพ {len(images)} ใบ แต่หัวข้อ {len(titles)} อัน ข้ามหน้านี้",
                  file=sys.stderr)
            return []
        charts = []
        for path, title in zip(images, titles):
            # หน้าอธิบายกับหน้าปิดเล่มมีภาพที่ไม่ใช่ตาราง ข้ามไปโดยไม่ล้มทั้งงาน
            try:
                codes, mixed = decode(read_ppm(path))
            except ValueError as error:
                print(f"  หน้า {page}: ถอด {title} ไม่ได้ ({error})", file=sys.stderr)
                continue
            charts.append({
                "stack": stack,
                "section": section,
                "page": page,
                **title,
                "actions": codes,
                "mixed": mixed,
            })
    return charts


def build(game: str, pages: range | None) -> dict:
    """ถอดทั้งเล่มออกมาเป็นโครงสร้างเดียว"""
    guide = GUIDES[game]
    pdf = guide["pdf"]
    if not pdf.exists():
        raise SystemExit(f"ไม่พบไฟล์ {pdf}")
    total = int(subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True,
                               check=True).stdout.split("Pages:")[1].split()[0])
    charts: list[dict] = []
    for page in (pages or range(1, total + 1)):
        found = page_charts(pdf, page)
        if found:
            print(f"  หน้า {page}: {len(found)} ชาร์ต", file=sys.stderr)
        charts.extend(found)
    return {
        "game": game,
        "title": guide["title"],
        "author": guide["author"],
        "publisher": guide["publisher"],
        "edition": guide["edition"],
        "file": pdf.name,
        "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "bytes": pdf.stat().st_size,
        "pages": total,
        "retrieved_on": datetime.date.today().isoformat(),
        "note": REBUILD_NOTE,
        "hand_order": list(HANDS),
        "charts": charts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ถอดชาร์ตพรีฟล็อปจาก PDF")
    parser.add_argument("--game", choices=sorted(GUIDES), required=True)
    parser.add_argument("--pages", help="ช่วงหน้า เช่น 8-12 ไม่ใส่คือทั้งเล่ม")
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()

    pages = None
    if args.pages:
        first, _, last = args.pages.partition("-")
        pages = range(int(first), int(last or first) + 1)

    data = build(args.game, pages)
    out = args.out or (OUT_DIR / f"preflop-{args.game}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    print(f"เขียน {len(data['charts'])} ชาร์ตลง {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
