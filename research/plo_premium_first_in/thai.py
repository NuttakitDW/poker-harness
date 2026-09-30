"""Thai strings for the Thai edition of the paper (tables, figures, archetypes).

Poker terms that Thai players use in English (raise, limp, fold, UTG, rundown,
double-suited, Premium, ...) are kept in English on purpose.
"""

from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / "fonts"

ARCHETYPES = {
    "aces": ("เอซคู่ (AAxx)", "มี A ตั้งแต่สองใบขึ้นไป"),
    "nut_big": ("ไพ่ใหญ่ดอก nut",
                "ไพ่ใหญ่ตั้งแต่สามใบพร้อม A มีดอกหรือ double-suited หรือ double-suited ที่มี A มีดอกกับไพ่ใหญ่อีกหนึ่งใบ"),
    "strong_pair": ("คู่ใหญ่แข็ง", "KK ที่ไม่ใช่ rainbow, QQ กับไพ่ใหญ่อีกหนึ่งใบ หรือ JJ/TT กับไพ่ใหญ่อีกสองใบ"),
    "broadway_rundown": ("Rundown ไพ่ใหญ่", "rundown ที่ไม่มีคู่ มีดอก และมีไพ่ใหญ่อย่างน้อยสองใบ"),
    "medium_pair": ("คู่ใหญ่ระดับกลาง", "QQ มีดอก, JJ/TT มีดอกกับไพ่ใหญ่อีกหนึ่งใบ หรือ KK แบบ rainbow"),
    "big_one_suit": ("ไพ่ใหญ่ ดอกเดียว",
                     "ไม่มีคู่ ไพ่ใหญ่สามใบแบบ single-suited หรือไพ่ใหญ่สองใบแบบ double-suited โดยไม่มี A มีดอก"),
    "ace_suited": ("A มีดอก", "A มีดอกกับไพ่ใหญ่อีกหนึ่งใบ หรือมือ double-suited ที่นำด้วย A"),
    "late_big": ("ไพ่ใหญ่ ดอกไม่ดี",
                 "มือที่เหลือซึ่งมีไพ่ใหญ่สามใบหรือคู่ TT-QQ ส่วนใหญ่เป็น rainbow หรือ three-flush "
                 "และ TT-JJ ที่ไม่มีไพ่ใหญ่ใบที่สอง"),
    "low_ds_rundown": ("Rundown ต่ำ double-suited", "rundown แบบ double-suited ที่มีไพ่ใหญ่ไม่เกินหนึ่งใบ"),
    "small_pair_ace": ("คู่เล็กกับ A มีดอก", "คู่ 99 ลงไปกับ A มีดอก"),
    "rest": ("มืออื่นทั้งหมด", "มืออื่นทั้งหมด รวมถึง rundown แบบ single-suited ทุกมือที่ต่ำกว่า T"),
}

# Exact phrases in the generated LaTeX tables; applied longest first so shorter
# phrases never break a longer one.
TABLE_PHRASES = {
    "Feature & Value & Hands & UTG play & BTN play & UTG entry EV & BTN entry EV":
        "ลักษณะ & ค่า & สัดส่วนมือ & เล่นที่ UTG & เล่นที่ BTN & EV เข้าเล่น UTG & EV เข้าเล่น BTN",
    "Big cards (T+)": "ไพ่ใหญ่ (T ขึ้นไป)",
    "Suits & ds": "ดอก & ds",
    "Best suit & Ace": "ดอกที่ดีที่สุด & A",
    "& 9 or lower &": "& 9 ลงไป &",
    "& none &": "& ไม่มี &",
    "Pair & AA": "คู่ & AA",
    "& unpaired &": "& ไม่มีคู่ &",
    "& trips &": "& ตอง &",
    "Straight window & rundown (4 in 5)": "ไพ่เรียง & rundown (4 ใน 5)",
    "& 3 in 5 &": "& 3 ใน 5 &",
    "& 2 or fewer &": "& 2 หรือน้อยกว่า &",
    "Tier & UTG & HJ & CO & BTN & SB": "Tier ของ Hwang & UTG & HJ & CO & BTN & SB",
    r"\textit{All hands}": r"\textit{ทุกมือ}",
    "Rule & UTG & HJ & CO & BTN & SB": "กฎ & UTG & HJ & CO & BTN & SB",
    r"\textit{EV lost per first-in decision (bb), held-out hands}":
        r"\textit{EV ที่เสียต่อการตัดสินใจแรก (bb) วัดบนมือที่แยกไว้}",
    "Hwang's advice (raise P, limp S, M late, fold T)": "คำแนะนำของ Hwang (raise P, limp S, M ตำแหน่งหลัง, fold T)",
    "Hwang tiers, best action per tier": "Tier ของ Hwang เลือก action ดีสุดต่อ tier",
    "Hwang forms, best action per form": "รูปแบบมือของ Hwang เลือก action ดีสุดต่อรูปแบบ",
    "New archetypes (11 groups)": "Archetype ใหม่ (11 กลุ่ม)",
    "New archetypes": "Archetype ใหม่",
    "Solver's own bucket strategy (most likely action)": "กลยุทธ์ bucket ของ solver เอง (action ที่น่าจะเลือกที่สุด)",
    r"\textit{Share of variation in the solver's fold rate explained}":
        r"\textit{สัดส่วนความแปรปรวนของอัตรา fold ของ solver ที่อธิบายได้ ($R^2$)}",
    "Hwang tiers (4 groups)": "Tier ของ Hwang (4 กลุ่ม)",
    "Hwang forms (62 groups)": "รูปแบบมือของ Hwang (62 กลุ่ม)",
    "Archetype & Hands & Hwang tiers inside & UTG": "Archetype & สัดส่วนมือ & Tier ของ Hwang ในกลุ่ม & UTG",
    "Archetype & Rule (first match wins) & UTG entry EV": "Archetype & กฎ (ใช้ข้อแรกที่ตรง) & EV เข้าเล่น UTG",
    "Hwang tier & Form & Suits & Combos & Solver UTG play & Solver BTN play & UTG entry EV":
        "Tier ของ Hwang & รูปแบบ & ดอก & คอมโบ & solver เล่นที่ UTG & solver เล่นที่ BTN & EV เข้าเล่น UTG",
    r"\textit{Hwang enters from UTG; the solver mostly folds}":
        r"\textit{Hwang ให้เข้าเล่นจาก UTG แต่ solver ส่วนใหญ่ fold}",
    r"\textit{Hwang folds from UTG; the solver mostly enters}":
        r"\textit{Hwang ให้ fold จาก UTG แต่ solver ส่วนใหญ่เข้าเล่น}",
    "mixed": "ก้ำกึ่ง",
}

FIGURE = {
    "verdict_legend": ["เข้าเล่นดีกว่าชัดเจน", "ก้ำกึ่ง", "fold ดีกว่าชัดเจน"],
    "share_of_hands": "ของมือ",
    "rundown_bar": "UTG: EV เข้าเล่นที่ดีที่สุด ลบ fold (bb)",
}


def localize_table(tex: str) -> str:
    for english in sorted(TABLE_PHRASES, key=len, reverse=True):
        tex = tex.replace(english, TABLE_PHRASES[english])
    return tex
