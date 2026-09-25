"""วาดชาร์ตพรีฟล็อปเป็นตาราง 13x13 ในเทอร์มินัล ให้ผู้ใช้เห็นเรนจ์ทั้งหมดในแวบเดียว

เสียงอ่านเรนจ์ยาว ๆ ฟังแล้วจำไม่ได้ ตารางแบบที่คนเล่นคุ้นตาช่วยให้ดูตามได้ทันที
แถวคือไพ่ใบสูง คอลัมน์คือไพ่ใบรอง เหนือเส้นทแยงเป็น suited ใต้เส้นเป็น offsuit

ใช้สีแบบ 256 สี ไม่ใช้ truecolor เพราะ Terminal.app ของ macOS ยังแสดง truecolor ไม่ได้
"""

from __future__ import annotations

import preflop

RANKS = preflop.RANKS
SIZE = len(RANKS)

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
POINTED = "\033[1;4m"

# (พื้นหลัง, ตัวอักษร) ตามรหัส action ในไฟล์ชาร์ต ช่องที่เล่นผสมแบ่งสีตามสัดส่วนของแต่ละ action
# แดงคือ raise เขียวคือ call หรือ check น้ำเงินคือ fold ช่องเทาจาง ๆ คือมือที่ไม่อยู่ในเรนจ์เลย
STYLES = {
    "R": "\033[48;5;124;38;5;231;1m",
    "C": "\033[48;5;28;38;5;231;1m",
    "F": "\033[48;5;25;38;5;231m",
    "-": "\033[38;5;240m",
}
# ลำดับสีในช่องผสม ซ้ายไปขวา raise แล้ว call แล้ว fold
SPLIT_ORDER = (("raise", "R"), ("call", "C"), ("fold", "F"))
CELL_WIDTH = 4
# ไม่มีสี เช่นส่งออกไปไฟล์ ใช้ตัวอักษรแทน ตัวเล็กคือเล่นผสม
PLAIN = {"R": "R", "C": "C", "F": ".", "-": "-"}
LEGEND = (("R", "raise"), ("C", "call/check"), ("F", "fold"))
LEGEND_WORDS = {
    "TH": {"none": "ไม่อยู่ในเรนจ์", "mixed": "เล่นผสม แบ่งสีตาม %", "lower": "ตัวเล็ก = เล่นผสม"},
    "EN": {"none": "not in range", "mixed": "mixed, split by %", "lower": "lower case = mixed"},
}


def cell_text(hand: str) -> str:
    """ชื่อมือในช่องกว้างสามตัวอักษร คู่ไม่มี s หรือ o จึงเติมช่องว่าง"""
    return hand.ljust(3)


def split(shares: dict) -> list[str]:
    """แบ่งช่องกว้าง 4 ตัวอักษรตามสัดส่วนแต่ละ action ช่องละ 25% ส่วนที่ปัดทิ้งมากสุดได้ช่องที่เหลือก่อน

    เศษเท่ากันให้ action ที่ได้ช่องน้อยกว่าก่อน ส่วนน้อยจะได้ไม่หายไปจากสายตา
    """
    exact = [(code, shares.get(action, 0.0) * CELL_WIDTH) for action, code in SPLIT_ORDER]
    counts = [int(size) for _, size in exact]
    leftover = sorted(range(len(exact)),
                      key=lambda i: (round(counts[i] - exact[i][1], 6), counts[i]))
    for i in leftover[:CELL_WIDTH - sum(counts)]:
        counts[i] += 1
    return [code for (code, _), count in zip(exact, counts) for _ in range(count)]


def _cell(hand: str, code: str, shares: dict | None, color: bool, asked: bool = False) -> str:
    # มือที่ผู้ใช้ถามมีลูกศรนำหน้าแทนช่องว่าง ช่องจึงกว้างเท่าเดิม
    lead = ">" if asked else " "
    if not color:
        mark = PLAIN.get(code, "?")
        return f"{lead}{mark.lower() if shares else mark}  "
    pointed = POINTED if asked else ""
    text = lead + cell_text(hand)
    if not shares:
        return f"{STYLES.get(code, '')}{pointed}{text}{RESET}"
    return "".join(f"{RESET}{STYLES[part]}{pointed}{char}" for part, char in zip(split(shares), text)) + RESET


def rows(book: dict, chart: dict, color: bool = True,
         asked: tuple[str, ...] = ()) -> list[str]:
    """13 แถวของตาราง นำหน้าด้วยชื่อไพ่ใบสูงของแถว"""
    order = book["hand_order"]
    codes = dict(zip(order, chart["actions"]))
    mixed = chart.get("mixed", {})
    lines = []
    for row, high in enumerate(RANKS):
        cells = "".join(_cell(hand, codes.get(hand, "-"), mixed.get(hand), color, hand in asked)
                        for hand in order[row * SIZE:(row + 1) * SIZE])
        label = f"{DIM}{high}{RESET}" if color else high
        lines.append(f" {label} {cells}")
    return lines


def legend(color: bool = True, lang: str = "TH") -> str:
    """คำอธิบายสี"""
    words = LEGEND_WORDS[lang]
    if not color:
        return f"   R raise  C call/check  . fold  - {words['none']}  {words['lower']}"
    parts = [f"{STYLES[code]} {name} {RESET}" for code, name in LEGEND]
    parts.append(f"{STYLES['-']}{words['none']}{RESET}")
    parts.append(f"{STYLES['R']}  {STYLES['F']}  {RESET} {words['mixed']}")
    return "   " + "  ".join(parts)


def render(book: dict, chart: dict, color: bool = True,
           asked: tuple[str, ...] = (), lang: str = "TH",
           notes: tuple[str, ...] = (), show_mixed: bool = True) -> str:
    """ตารางเต็มพร้อมหัวเรื่อง ที่มา คำอธิบายสี และความถี่ของช่องที่เล่นผสม

    เป็นแม่แบบกลางของทุกโหมดที่โชว์ชาร์ต notes คือบรรทัดเสริมท้ายตาราง เช่นคะแนนความมั่นใจ
    show_mixed ปิดรายการความถี่ได้ สำหรับโหมดที่ต้องการแค่ตาราง ช่องผสมยังแบ่งสีตามสัดส่วนอยู่
    """
    words = preflop.WORDS[lang]
    title = preflop.describe(book, chart, lang)
    # ชาร์ตที่ solver แก้สดไม่มีเลขหน้า
    source = book["title"] if chart.get("page") is None else f"{book['title']} {words['page']} {chart['page']}"
    header = "   " + "".join(f" {rank}  " for rank in RANKS)
    lines = [
        f"{BOLD}{title}{RESET}" if color else title,
        f"{DIM}{source}{RESET}" if color else source,
        f"{DIM}{header}{RESET}" if color else header,
        *rows(book, chart, color, asked),
        legend(color, lang),
    ]
    for answer in preflop.hand_answers(book, chart, list(asked), lang):
        lines.append(f"   {BOLD}{answer}{RESET}" if color else f"   {answer}")
    mixed = preflop.mixed_note(chart) if show_mixed else ""
    if mixed:
        lines.append(f"   {words['mixed']}: {mixed}")
    lines.extend(f"   {note}" for note in notes)
    return "\n".join(lines)


def chart_key(book: dict, chart: dict) -> tuple:
    """ใช้เทียบว่าเป็นชาร์ตใบเดิมที่เพิ่งโชว์ไปหรือไม่ ถามมือใหม่ในชาร์ตเดิมจะวาดใหม่"""
    return (book["game"], chart["page"], chart["hero"], chart.get("villain"),
            chart["scenario"], chart["stack"])


def for_question(question: str, color: bool = True) -> tuple[tuple, str] | None:
    """ตารางของชาร์ตที่ตรงกับคำถาม ใบเดียวกับที่ส่งเข้าโมเดล คืน None ถ้าไม่มี"""
    found = preflop.find(question)
    if found is None:
        return None
    book, chart, _ = found
    asked = tuple(preflop.hands_in(question))
    return chart_key(book, chart) + asked, render(book, chart, color, asked)
