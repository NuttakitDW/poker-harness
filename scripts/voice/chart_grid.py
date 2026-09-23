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

# (พื้นหลัง, ตัวอักษร) ตามรหัส action ในไฟล์ชาร์ต ช่องที่เล่นผสมใช้สีอ่อนของ action หลัก
STYLES = {
    "R": "\033[48;5;25;38;5;231;1m",
    "C": "\033[48;5;136;38;5;231;1m",
    "F": "\033[38;5;245m",
    "-": "\033[38;5;240m",
}
MIXED_STYLES = {
    "R": "\033[48;5;110;38;5;16m",
    "C": "\033[48;5;180;38;5;16m",
    "F": "\033[48;5;252;38;5;16m",
}
# ไม่มีสี เช่นส่งออกไปไฟล์ ใช้ตัวอักษรแทน ตัวเล็กคือเล่นผสม
PLAIN = {"R": "R", "C": "C", "F": ".", "-": "-"}
LEGEND = (("R", "raise"), ("C", "call"), ("F", "fold"))


def cell_text(hand: str) -> str:
    """ชื่อมือในช่องกว้างสามตัวอักษร คู่ไม่มี s หรือ o จึงเติมช่องว่าง"""
    return hand.ljust(3)


def _cell(hand: str, code: str, mixed: bool, color: bool, asked: bool = False) -> str:
    # มือที่ผู้ใช้ถามมีลูกศรนำหน้าแทนช่องว่าง ช่องจึงกว้างเท่าเดิม
    lead = ">" if asked else " "
    if not color:
        mark = PLAIN.get(code, "?")
        return f"{lead}{mark.lower() if mixed else mark}  "
    style = MIXED_STYLES.get(code) if mixed else None
    style = (style or STYLES.get(code, "")) + (POINTED if asked else "")
    return f"{style}{lead}{cell_text(hand)}{RESET}"


def rows(book: dict, chart: dict, color: bool = True,
         asked: tuple[str, ...] = ()) -> list[str]:
    """13 แถวของตาราง นำหน้าด้วยชื่อไพ่ใบสูงของแถว"""
    order = book["hand_order"]
    codes = dict(zip(order, chart["actions"]))
    mixed = chart.get("mixed", {})
    lines = []
    for row, high in enumerate(RANKS):
        cells = "".join(_cell(hand, codes.get(hand, "-"), hand in mixed, color, hand in asked)
                        for hand in order[row * SIZE:(row + 1) * SIZE])
        label = f"{DIM}{high}{RESET}" if color else high
        lines.append(f" {label} {cells}")
    return lines


def legend(color: bool = True) -> str:
    """คำอธิบายสี"""
    if not color:
        return "   R raise  C call  . fold  - ไม่อยู่ในเรนจ์  ตัวเล็ก = เล่นผสม"
    parts = [f"{STYLES[code]} {name} {RESET}" for code, name in LEGEND]
    parts.append(f"{STYLES['-']}ไม่อยู่ในเรนจ์{RESET}")
    parts.append(f"{MIXED_STYLES['R']} ผสม {RESET}")
    return "   " + "  ".join(parts)


def render(book: dict, chart: dict, color: bool = True,
           asked: tuple[str, ...] = ()) -> str:
    """ตารางเต็มพร้อมหัวเรื่อง ที่มา คำอธิบายสี และความถี่ของช่องที่เล่นผสม"""
    title = preflop.describe(book, chart)
    source = f"{book['title']} หน้า {chart['page']}"
    header = "   " + "".join(f" {rank}  " for rank in RANKS)
    lines = [
        f"{BOLD}{title}{RESET}" if color else title,
        f"{DIM}{source}{RESET}" if color else source,
        f"{DIM}{header}{RESET}" if color else header,
        *rows(book, chart, color, asked),
        legend(color),
    ]
    for answer in preflop.hand_answers(book, chart, list(asked)):
        lines.append(f"   {BOLD}{answer}{RESET}" if color else f"   {answer}")
    mixed = preflop.mixed_note(chart)
    if mixed:
        lines.append(f"   เล่นผสม: {mixed}")
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
