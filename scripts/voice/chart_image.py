"""วาดชาร์ตพรีฟล็อปเป็นรูป PNG สำหรับส่งใน Discord

Discord แสดงสีในข้อความได้แค่ 8 สีพื้นฐาน เฉดอ่อนของช่องผสมจะหายหมด จึงส่งเป็นรูปแทน
สีทุกช่องมาจาก chart_grid.tone ตัวเดียวกับเทอร์มินัล รูปกับจอจึงตรงกันเสมอ
ฟอนต์ Ayuthaya ของ macOS กว้างเท่ากันทุกตัวและมีภาษาไทย ใช้ได้ทั้งหัวเรื่องและชื่อมือ
"""

from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

import chart_grid
import preflop

FONT_PATH = "/System/Library/Fonts/Supplemental/Ayuthaya.ttf"
TITLE_SIZE, CELL_SIZE, TEXT_SIZE, NOTE_SIZE = 24, 17, 18, 14
NOTE_H = 20
CELL_W, CELL_H, GAP = 50, 32, 2
MARGIN, LABEL_W, LINE_H = 24, 26, 30
SIZE = chart_grid.SIZE
BACKGROUND = (24, 26, 31)
TEXT, DIM, OUT_OF_RANGE = (236, 238, 242), (140, 146, 158), (48, 52, 60)
DARK_TEXT = (0, 0, 0)
LEVELS = (0, 95, 135, 175, 215, 255)  # ขั้นสีของลูกบาศก์ xterm-256


def rgb(index: int) -> tuple[int, int, int]:
    """สี xterm-256 ช่อง 16-231 เป็น RGB"""
    cube = index - 16
    return LEVELS[cube // 36], LEVELS[cube // 6 % 6], LEVELS[cube % 6]


def font_path(env=os.environ) -> str:
    """ฟอนต์ที่ใช้วาด เครื่อง Linux ไม่มี Ayuthaya ให้ชี้ฟอนต์ไทยของตัวเองด้วย CHART_FONT"""
    return env.get("CHART_FONT") or FONT_PATH


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path(), size)


def _grid_top() -> int:
    return MARGIN + 2 * LINE_H + LINE_H  # หัวเรื่อง ที่มา แล้วแถวชื่อคอลัมน์


def cell_origin(row: int, col: int) -> tuple[int, int]:
    """มุมซ้ายบนของช่องในตาราง"""
    return (MARGIN + LABEL_W + col * (CELL_W + GAP), _grid_top() + row * (CELL_H + GAP))


def _answer_lines(book: dict, chart: dict, asked: tuple[str, ...]) -> list[tuple[str, list]]:
    names = chart.get("names", {})
    return [(hand, [(chart_grid.ACTION_CODES.get(name, "F"),
                     f"{names.get(name, name)} {round(share * 100)}%")
                    for name, share in preflop.hand_shares(book, chart, hand)])
            for hand in asked]


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """ตัดบรรทัดยาวตรงจุลภาค ให้ไม่เกินความกว้างของรูป"""
    lines, current = [], ""
    for part in text.split(", "):
        candidate = f"{current}, {part}" if current else part
        if current and font.getlength(candidate) > width:
            lines.append(current + ",")
            current = part
        else:
            current = candidate
    return lines + [current] if current else lines


def render(book: dict, chart: dict, asked: tuple[str, ...] = (), lang: str = "TH",
           notes: tuple[str, ...] = ()) -> bytes:
    """รูป PNG ของชาร์ต มือที่ถามเป็นป้ายสี % ใต้ตาราง notes ต่อท้ายเป็นตัวจาง"""
    title_font, cell_font, text_font = _font(TITLE_SIZE), _font(CELL_SIZE), _font(TEXT_SIZE)
    note_font = _font(NOTE_SIZE)
    answers = _answer_lines(book, chart, asked)
    grid_w = LABEL_W + SIZE * (CELL_W + GAP)
    note_lines = [line for note in notes for line in _wrap(note, note_font, grid_w)]
    grid_bottom = cell_origin(SIZE - 1, 0)[1] + CELL_H
    height = (grid_bottom + LINE_H // 2 + len(answers) * LINE_H + len(note_lines) * NOTE_H
              + MARGIN)
    picture = Image.new("RGB", (MARGIN * 2 + grid_w, height), BACKGROUND)
    draw = ImageDraw.Draw(picture)

    source = book["title"] if chart.get("page") is None else f"{book['title']} p.{chart['page']}"
    draw.text((MARGIN, MARGIN), preflop.describe(book, chart, lang), font=title_font, fill=TEXT)
    draw.text((MARGIN, MARGIN + LINE_H), source, font=text_font, fill=DIM)
    for col, rank in enumerate(chart_grid.RANKS):
        x, _ = cell_origin(0, col)
        draw.text((x + CELL_W // 2, _grid_top() - LINE_H // 2), rank, font=text_font, fill=DIM,
                  anchor="mm")

    codes = dict(zip(book["hand_order"], chart["actions"]))
    mixed = chart.get("mixed", {})
    for index, hand in enumerate(book["hand_order"]):
        row, col = divmod(index, SIZE)
        x, y = cell_origin(row, col)
        _, background, dark = chart_grid.tone(codes.get(hand, "-"), mixed.get(hand))
        fill = rgb(background) if background is not None else OUT_OF_RANGE
        draw.rectangle((x, y, x + CELL_W - 1, y + CELL_H - 1), fill=fill)
        ink = DARK_TEXT if dark else (DIM if background is None else TEXT)
        draw.text((x + CELL_W // 2, y + CELL_H // 2), hand, font=cell_font, fill=ink, anchor="mm")
        if col == 0:
            draw.text((MARGIN, y + CELL_H // 2), chart_grid.RANKS[row], font=text_font, fill=DIM,
                      anchor="lm")

    y = grid_bottom + LINE_H // 2
    for hand, badges in answers:
        x = MARGIN
        draw.text((x, y), hand, font=title_font, fill=TEXT)
        x += int(draw.textlength(hand, font=title_font)) + 16
        for code, label in badges or [("-", preflop.WORDS[lang]["none"])]:
            width = int(draw.textlength(label, font=text_font)) + 16
            _, background, _ = chart_grid.tone(code, None)
            draw.rectangle((x, y, x + width, y + LINE_H - 4),
                           fill=rgb(background) if background is not None else OUT_OF_RANGE)
            draw.text((x + 8, y + (LINE_H - 4) // 2), label, font=text_font, fill=TEXT, anchor="lm")
            x += width + 8
        y += LINE_H
    for line in note_lines:
        draw.text((MARGIN, y), line, font=note_font, fill=DIM)
        y += NOTE_H

    out = io.BytesIO()
    picture.save(out, format="PNG")
    return out.getvalue()
