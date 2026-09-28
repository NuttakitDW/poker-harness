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

# (พื้นหลัง, ตัวอักษร) ตามรหัส action ในไฟล์ชาร์ต ช่องที่เล่นผสมใช้สีของ action หลักแบบอ่อนลงตามความถี่
# แดงคือ raise เขียวคือ call หรือ check น้ำเงินคือ fold ช่องเทาจาง ๆ คือมือที่ไม่อยู่ในเรนจ์เลย
STYLES = {
    "R": "\033[48;5;124;38;5;231;1m",
    "J": "\033[48;5;130;38;5;231;1m",
    "C": "\033[48;5;28;38;5;231;1m",
    "F": "\033[48;5;25;38;5;231m",
    "-": "\033[38;5;240m",
}
ACTION_CODES = {"raise": "R", "allin": "J", "call": "C", "fold": "F"}
# เฉดของช่องผสม (ความถี่ขั้นต่ำ, พื้นหลัง) ยิ่งเล่นน้อยยิ่งอ่อน สีอ่อนใช้ตัวอักษรดำให้อ่านออก
SHADES = {
    "R": ((0.95, 124), (0.85, 167), (0.7, 174), (0.0, 217)),
    "J": ((0.95, 130), (0.85, 172), (0.7, 179), (0.0, 223)),
    "C": ((0.95, 28), (0.85, 71), (0.7, 108), (0.0, 151)),
    "F": ((0.95, 25), (0.85, 68), (0.7, 110), (0.0, 153)),
}
DARK_TEXT_FROM = 0.85  # ต่ำกว่านี้พื้นอ่อนแล้ว ใช้ตัวอักษรดำ
# ไม่มีสี เช่นส่งออกไปไฟล์ ใช้ตัวอักษรแทน ตัวเล็กคือเล่นผสม
PLAIN = {"R": "R", "J": "J", "C": "C", "F": ".", "-": "-"}
LEGEND = (("R", "raise"), ("J", "all-in"), ("C", "call/check"), ("F", "fold"))
LEGEND_WORDS = {
    "TH": {"none": "ไม่อยู่ในเรนจ์", "mixed": "สีอ่อน = เล่นผสม ยิ่งอ่อนยิ่งเล่นน้อย",
           "lower": "ตัวเล็ก = เล่นผสม"},
    "EN": {"none": "not in range", "mixed": "lighter = mixed, played less often",
           "lower": "lower case = mixed"},
}


def cell_text(hand: str) -> str:
    """ชื่อมือในช่องกว้างสามตัวอักษร คู่ไม่มี s หรือ o จึงเติมช่องว่าง"""
    return hand.ljust(3)


def tone(code: str, shares: dict | None) -> tuple[str, int | None, bool]:
    """(action ที่ใช้สี, สีพื้น xterm-256, ตัวอักษรดำไหม) ของช่องหนึ่ง ใช้ร่วมกันทั้งเทอร์มินัลและรูป

    ช่องผสมใช้สีของ action หลัก ยิ่งเล่นน้อยยิ่งอ่อน ช่องที่ไม่อยู่ในเรนจ์ไม่มีสีพื้น
    """
    if shares:
        action, share = max(shares.items(), key=lambda item: item[1])
        code = ACTION_CODES[action]
    elif code in SHADES:
        share = 1.0
    else:
        return code, None, False
    background = next(bg for floor, bg in SHADES[code] if share >= floor)
    return code, background, share < DARK_TEXT_FROM


def shade(shares: dict) -> tuple[str, str]:
    """(action หลัก, สไตล์) ของช่องผสม เช่น raise 70% เป็นแดงอ่อน เล่นเกือบตลอดเป็นสีเต็ม"""
    code, background, dark = tone("F", shares)
    if background == SHADES[code][0][1]:
        return code, STYLES[code]
    return code, f"\033[48;5;{background};38;5;{'16' if dark else '231;1'}m"


def _cell(hand: str, code: str, shares: dict | None, color: bool, asked: bool = False) -> str:
    # มือที่ผู้ใช้ถามมีลูกศรนำหน้าแทนช่องว่าง ช่องจึงกว้างเท่าเดิม
    lead = ">" if asked else " "
    if not color:
        mark = PLAIN.get(code, "?")
        return f"{lead}{mark.lower() if shares else mark}  "
    pointed = POINTED if asked else ""
    text = lead + cell_text(hand)
    style = shade(shares)[1] if shares else STYLES.get(code, "")
    return f"{style}{pointed}{text}{RESET}"


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


def legend_entries(chart: dict | None = None, lang: str = "TH") -> tuple[tuple[str, str], ...]:
    """(รหัส, ชื่อ) ของสีที่มีในชาร์ตจริง ตามลำดับ raise call fold แล้วช่องนอกเรนจ์ปิดท้าย

    ชื่อตาม chart["names"] เช่นชาร์ต push/fold เรียก raise ว่า shove ไม่มีชาร์ตก็แสดงครบทุกสี
    """
    if chart is None:
        return (*LEGEND, ("-", LEGEND_WORDS[lang]["none"]))
    used = set(chart["actions"])
    used.update(ACTION_CODES[action] for shares in chart.get("mixed", {}).values()
                for action in shares if action in ACTION_CODES)
    names = chart.get("names", {})
    actions = {code: action for action, code in ACTION_CODES.items()}
    entries = tuple((code, names.get(actions[code], name)) for code, name in LEGEND if code in used)
    return entries + ((("-", LEGEND_WORDS[lang]["none"]),) if "-" in used else ())


def legend(color: bool = True, lang: str = "TH", chart: dict | None = None) -> str:
    """คำอธิบายสี เฉพาะ action ที่มีในชาร์ต"""
    words = LEGEND_WORDS[lang]
    entries = legend_entries(chart, lang)
    if not color:
        keys = "  ".join(f"{PLAIN[code]} {name}" for code, name in entries)
        return f"   {keys}  {words['lower']}"
    # แต่ละสีตามด้วยเฉดที่อ่อนลง เช่น ฟ้าอ่อนคือ fold เป็นส่วนใหญ่แต่บางครั้งก็เล่น
    parts = [f"{STYLES[code]} {name} {_ramp(code)}{RESET}" if code in SHADES
             else f"{STYLES[code]}{name}{RESET}" for code, name in entries]
    parts.append(words["mixed"])
    return "   " + "  ".join(parts)


def _ramp(code: str) -> str:
    action = next(name for name, value in ACTION_CODES.items() if value == code)
    return "".join(f"{shade({action: floor or 0.55, 'other': 1 - (floor or 0.55)})[1]}  "
                   for floor, _ in SHADES[code][1:])


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
        legend(color, lang, chart),
    ]
    if asked:
        # คำตอบของมือที่ถามต้องเด่น เว้นบรรทัด แล้วแต่ละ action เป็นป้ายสีเดียวกับตาราง
        lines.append("")
        answers = ([_answer(book, chart, hand, lang) for hand in asked] if color
                   else [f"   {answer}" for answer in preflop.hand_answers(book, chart, list(asked), lang)])
        lines.extend(answers)
    mixed = preflop.mixed_note(chart) if show_mixed else ""
    if mixed:
        lines.append(f"   {words['mixed']}: {mixed}")
    lines.extend(f"   {note}" for note in notes)
    return "\n".join(lines)


def _answer(book: dict, chart: dict, hand: str, lang: str) -> str:
    shares = preflop.hand_shares(book, chart, hand)
    if not shares:
        return f"   {BOLD}{hand}{RESET}  {STYLES['-']}{preflop.WORDS[lang]['none']}{RESET}"
    names = chart.get("names", {})
    badges = " ".join(f"{STYLES[ACTION_CODES[name]]} {names.get(name, name)} "
                      f"{round(share * 100)}% {RESET}" for name, share in shares)
    return f"   {BOLD}{hand}{RESET}  {badges}"


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
