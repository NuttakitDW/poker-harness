"""ไข่อีสเตอร์ พิมพ์หรือพูดคำว่า mario ที่ไหนก็ได้ในคำถาม ได้ชาร์ต river ใบนี้แทนชาร์ต push/fold

ชาร์ตคัดลอกมาจากหน้าจอ Desktop Postflop v0.2.7 ของ OOP บน river 6h 9d Td Qc 2s pot 100 stack 500
สีของสี่ action วาดเป็นรูปในตาราง 13x13 ทุกช่องจึงต้องตรงกับหน้าจอต้นฉบับ
เทอร์มินัลวาดเป็นสองบรรทัดต่อแถว ชื่อมือกับ EV ส่วน Discord ได้เป็นรูป PNG
"""

from __future__ import annotations

import io
import re

import chart_grid

RANKS = chart_grid.RANKS
SIZE = chart_grid.SIZE
TRIGGER = re.compile(r"mario", re.IGNORECASE)

TITLE = "RIVER  6h 9d Td Qc 2s  Pot 100  Stack 500  OOP"
SOURCE = "Desktop Postflop v0.2.7"
# (ชื่อ, ความถี่ทั้งเรนจ์, สีพื้น xterm-256, RGB ของรูป) ตามรหัสในตาราง
ACTIONS = {
    "X": ("Check", "23.5%", 68, (74, 134, 232)),
    "B": ("Bet 33", "28.3%", 64, (106, 150, 38)),
    "M": ("Bet 66", "26.3%", 172, (230, 156, 36)),
    "A": ("Allin 500", "21.9%", 124, (180, 40, 30)),
}
LEGEND_ORDER = ("X", "B", "M", "A")

# แถวละ 13 ช่อง เรียงคอลัมน์ A..2 แบบเดียวกับ chart_grid เหนือเส้นทแยงเป็น suited
GRID = (
    "X17.8 X8.6 X18.4 A-33.9 A227.6 A152.8 A-39.8 A-38.9 X13.9 X5.6 X5.5 X5.3 X12.2",
    "X8.6 X19.8 A273.5 A358.0 A223.6 A151.0 A-58.5 A-57.6 A81.0 A-70.1 A-70.5 X2.3 X12.5",
    "X18.4 X18.9 B249.3 B216.3 B240.9 M155.5 M136.3 B208.5 M154.0 X18.7 X18.6 X18.3 X22.4",
    "X8.2 B279.5 B138.7 B185.5 B116.2 M84.6 M173.5 B-72.1 M54.3 M-43.3 M-40.8 X2.0 X13.0",
    "X15.8 B176.7 B157.0 B179.5 B244.9 M147.5 M111.9 M107.1 B224.7 M99.0 M97.9 M98.6 X23.2",
    "X15.0 B128.8 B239.3 M84.5 M147.5 M159.4 M79.7 B112.8 B223.4 B104.9 B101.4 X16.0 X22.7",
    "X6.9 B3.8 X18.4 M173.5 M111.9 M79.7 M64.8 B167.9 M49.2 M-54.3 X1.4 X1.4 X11.6",
    "X5.9 X2.8 A258.8 A-84.5 B165.5 A131.3 A337.9 A80.5 B72.3 X0.5 X0.5 X0.5 X11.6",
    "X13.9 A81.0 A310.5 A76.8 B224.6 A274.4 A56.6 B72.3 A316.2 A50.7 A50.9 X14.6 X22.3",
    "A-51.1 A-70.1 B247.4 A-104.7 B151.9 B104.7 A-93.6 A-111.5 A50.7 A13.4 A-198.2 A-197.9 X12.3",
    "M-10.2 A-26.0 B248.3 A-78.7 M97.8 B101.4 A-90.6 A-64.4 B62.8 A-198.2 M26.5 A-79.9 X12.2",
    "M-10.2 M-26.2 B126.6 B-79.0 B149.6 B102.3 A-91.6 A-110.0 B63.6 A-75.1 M-79.9 M23.1 X12.0",
    "M18.6 M17.3 B234.0 B26.4 B220.6 X22.7 X11.6 X14.1 B218.0 X10.0 M9.3 M9.2 X22.1",
)

CELL_W = 7  # "A5o" กับ "-198.2" ต้องอยู่ในช่องเดียวกันได้


def hand_at(row: int, col: int) -> str:
    """ชื่อมือของช่อง คู่อยู่บนเส้นทแยง suited อยู่ขวาบน offsuit อยู่ซ้ายล่าง"""
    if row == col:
        return RANKS[row] * 2
    high, low = sorted((row, col))
    return f"{RANKS[high]}{RANKS[low]}{'s' if col > row else 'o'}"


def _cells() -> tuple[tuple[str, str, float], ...]:
    return tuple((hand_at(row, col), cell[0], float(cell[1:]))
                 for row, line in enumerate(GRID)
                 for col, cell in enumerate(line.split()))


CELLS = _cells()


def asked(text: str) -> bool:
    """คำถามมีคำว่า mario อยู่ตรงไหนก็ได้ ตัวเล็กตัวใหญ่ไม่สำคัญ"""
    return bool(TRIGGER.search(text or ""))


def _style(code: str) -> str:
    return f"\033[48;5;{ACTIONS[code][2]};38;5;231;1m"


def _legend(color: bool) -> list[str]:
    lines = []
    for code in LEGEND_ORDER:
        name, share, _, _ = ACTIONS[code]
        swatch = f"{_style(code)}  {chart_grid.RESET}" if color else f"[{code}]"
        lines.append(f"   {swatch} {name:<10} [{share}]")
    return lines


def _row_lines(row: int, color: bool) -> tuple[str, str]:
    cells = CELLS[row * SIZE:(row + 1) * SIZE]
    if not color:
        top = "".join(f"{code} {hand:<{CELL_W - 2}}" for hand, code, _ in cells)
        bottom = "".join(f"{ev:>{CELL_W - 1}.1f} " for _, _, ev in cells)
        return top, bottom
    reset = chart_grid.RESET
    top = "".join(f"{_style(code)}{hand:<{CELL_W}}{reset}" for hand, code, _ in cells)
    bottom = "".join(f"{_style(code)}{ev:>{CELL_W}.1f}{reset}" for _, code, ev in cells)
    return top, bottom


def render(color: bool = True) -> str:
    """ชาร์ตเต็มในเทอร์มินัล หัวเรื่อง คำอธิบายสี แล้วตารางสองบรรทัดต่อแถว"""
    bold, dim, reset = (chart_grid.BOLD, chart_grid.DIM, chart_grid.RESET) if color else ("", "", "")
    lines = [f"{bold}{TITLE}{reset}", f"{dim}{SOURCE}{reset}", *_legend(color), ""]
    for row in range(SIZE):
        lines.extend(f"   {line}" for line in _row_lines(row, color))
    lines.append(f"\n   {dim}it's-a me, Mario!{reset}")
    return "\n".join(lines)


PNG_CELL_W, PNG_CELL_H, PNG_GAP, PNG_MARGIN = 70, 48, 2, 24
PNG_HEADER_H = 170


def png() -> bytes:
    """รูปของชาร์ตเดียวกันสำหรับ Discord ชื่อมือมุมซ้ายบน EV มุมขวาล่างเหมือนหน้าจอต้นฉบับ"""
    from PIL import Image, ImageDraw

    import chart_image

    title_font, text_font = chart_image._font(24), chart_image._font(18)
    hand_font, ev_font = chart_image._font(18), chart_image._font(15)
    step_x, step_y = PNG_CELL_W + PNG_GAP, PNG_CELL_H + PNG_GAP
    width = PNG_MARGIN * 2 + SIZE * step_x
    height = PNG_MARGIN + PNG_HEADER_H + SIZE * step_y + PNG_MARGIN
    picture = Image.new("RGB", (width, height), chart_image.BACKGROUND)
    draw = ImageDraw.Draw(picture)

    draw.text((PNG_MARGIN, PNG_MARGIN), TITLE, font=title_font, fill=chart_image.TEXT)
    draw.text((PNG_MARGIN, PNG_MARGIN + 32), SOURCE, font=text_font, fill=chart_image.DIM)
    for index, code in enumerate(LEGEND_ORDER):
        name, share, _, fill = ACTIONS[code]
        y = PNG_MARGIN + 66 + index * 24
        draw.rectangle((PNG_MARGIN, y + 3, PNG_MARGIN + 14, y + 17), fill=fill)
        draw.text((PNG_MARGIN + 24, y), f"{name:<10} [{share}]", font=text_font,
                  fill=chart_image.TEXT)

    top = PNG_MARGIN + PNG_HEADER_H
    for index, (hand, code, ev) in enumerate(CELLS):
        row, col = divmod(index, SIZE)
        x, y = PNG_MARGIN + col * step_x, top + row * step_y
        draw.rectangle((x, y, x + PNG_CELL_W - 1, y + PNG_CELL_H - 1), fill=ACTIONS[code][3])
        draw.text((x + 4, y + 2), hand, font=hand_font, fill=chart_image.TEXT)
        draw.text((x + PNG_CELL_W - 4, y + PNG_CELL_H - 2), f"{ev:.1f}", font=ev_font,
                  fill=chart_image.TEXT, anchor="rd")

    out = io.BytesIO()
    picture.save(out, format="PNG")
    return out.getvalue()
