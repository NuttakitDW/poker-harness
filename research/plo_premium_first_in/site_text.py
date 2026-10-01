"""Thai and English wording for the 40bb MTT site pages built by build_site_mtt40.py.

TABLE holds the labels the table builders use. RANGE fills the {{t:key}} tokens in
site_range_template.html. The summary page has one template per language because it is mostly prose.
"""

from __future__ import annotations

LANGS = ("th", "en")
# Page names under public/ (Vercel serves them without .html)
SUMMARY = {"th": "research-mtt40", "en": "research-mtt40-en"}
RANGE_PAGE = {"th": "research-mtt40-range", "en": "research-mtt40-range-en"}

TABLE = {
    "th": {
        "seat": "ตำแหน่ง", "mix": "สัดส่วน", "played": "เล่นรวม", "plays": "เล่น", "hwang_tier": "Tier ของ Hwang",
        "measure": "ตัวชี้วัด (40bb MTT)", "agree": "การตัดสินใจเล่น/ทิ้งที่ตรงกับ Hwang",
        "r2_tiers": "R² ของ 4 tier ของ Hwang", "r2_forms": "R² ของรูปแบบมือ 62 แบบของ Hwang",
        "r2_arch": "R² ของ archetype ใหม่ 11 กลุ่ม",
        "feature": "ลักษณะ", "value": "ค่า", "share": "สัดส่วนมือ",
        "hwang_plays": "Hwang ให้เล่นจาก {seat} แต่ solver ทิ้งเป็นส่วนใหญ่",
        "hwang_folds": "Hwang ให้ทิ้งจาก {seat} แต่ solver เล่นเป็นส่วนใหญ่",
        "group": "{title} · {total} คอมโบ ({share} ของมือทั้งหมด)",
        "form_suits": "รูปแบบ, ดอก", "combos": "คอมโบ", "solver_does": "สิ่งที่ solver ทำ",
        "rundown_head": "Rundown (Premium) · % fold ที่ UTG",
        "arch_head": "Archetype (ตรวจตามลำดับ ข้อแรกที่ตรงใช้ข้อนั้น)",
    },
    "en": {
        "seat": "Position", "mix": "Mix", "played": "Played", "plays": "played", "hwang_tier": "Hwang tier",
        "measure": "Measure (40bb MTT)", "agree": "Play/fold decisions that match Hwang",
        "r2_tiers": "R² of Hwang's 4 tiers", "r2_forms": "R² of Hwang's 62 hand forms",
        "r2_arch": "R² of the 11 new archetypes",
        "feature": "Feature", "value": "Value", "share": "Share of hands",
        "hwang_plays": "Hwang plays these from {seat}, the solver mostly folds them",
        "hwang_folds": "Hwang folds these from {seat}, the solver mostly plays them",
        "group": "{title} · {total} combos ({share} of all hands)",
        "form_suits": "Form, suits", "combos": "Combos", "solver_does": "What the solver does",
        "rundown_head": "Rundown (Premium) · UTG fold %",
        "arch_head": "Archetype (checked in order, the first match applies)",
    },
}

DRIVER = {
    "th": {"Big cards (T+)": "ไพ่ใหญ่ (T ขึ้นไป)", "Suits": "ดอก", "Best suit": "ดอกที่ดีที่สุด", "Pair": "คู่",
           "Straight window": "ไพ่เรียง"},
    "en": {"Best suit": "Suit led by"},
}
VALUE = {
    "th": {"Ace": "A มีดอก", "T-K": "T-K มีดอก", "9 or lower": "9 ลงไป", "none": "ไม่มีดอกคู่", "unpaired": "ไม่มีคู่",
           "trips": "ตอง", "rundown (4 in 5)": "4 ใบในช่วง 5", "3 in 5": "3 ใบในช่วง 5", "2 or fewer": "น้อยกว่านั้น"},
    "en": {"none": "no two suited", "rundown (4 in 5)": "4 cards within 5 ranks", "3 in 5": "3 cards within 5 ranks",
           "2 or fewer": "fewer"},
}
FORM = {
    "th": {
        "pair_connectors": "คู่กับไพ่ต่อ", "pair_ace": "คู่กับ A มีดอก", "middle_gap": "rundown ช่องกลาง",
        "bottom_gap": "rundown ช่องล่าง", "rundown": "rundown", "two_gap_middle": "straight ช่องสองกลาง",
        "two_single_gaps": "straight สองช่อง", "two_gap_bottom": "straight ช่องสองล่าง",
        "big_pair_danglers": "คู่ใหญ่กับไพ่ห้อย", "ace_weak": "A มีดอกอ่อน",
        "three_broadway_dangler": "Broadway สามใบกับไพ่ห้อย", "ace_broadway_dangler": "A มีดอก Broadway กับไพ่ห้อย",
        "double_small": "คู่เล็กสองคู่", "top_two_gaps": "straight ช่องบน", "no_structure": "ไม่มีโครงสร้าง",
        "small_pair_danglers": "คู่เล็กกับไพ่ห้อย", "ace_sucker_low": "A มีดอกกับ 2-3/2-4", "top_gap": "rundown ช่องบน",
        "top_bottom_gap": "rundown ช่องบนและล่าง",
    },
    "en": {
        "pair_connectors": "pair with connectors", "pair_ace": "pair with suited Ace", "middle_gap": "middle-gap rundown",
        "bottom_gap": "bottom-gap rundown", "rundown": "rundown", "two_gap_middle": "straight, two-card middle gap",
        "two_single_gaps": "straight, two single gaps", "two_gap_bottom": "straight, two-card bottom gap",
        "big_pair_danglers": "big pair with danglers", "ace_weak": "weak suited Ace",
        "three_broadway_dangler": "three Broadway with a dangler", "ace_broadway_dangler": "suited Ace Broadway with a dangler",
        "double_small": "two small pairs", "top_two_gaps": "straight, top gap", "no_structure": "no structure",
        "small_pair_danglers": "small pair with danglers", "ace_sucker_low": "suited Ace with 2-3/2-4",
        "top_gap": "top-gap rundown", "top_bottom_gap": "top- and bottom-gap rundown",
    },
}

RANGE = {
    "th": {
        "lang": "th", "title": "ตามควาย Range 40bb",
        "description": "ความถี่ raise, limp, fold ของทุกมือ PLO4 เมื่อได้เป็นคนแรก ทัวร์นาเมนต์ 6 คน 40bb มี ante",
        "nav_ask": "ถามชาร์ต", "nav_method": "วิธีคำนวณ", "nav_research": "งานวิจัย",
        "eyebrow": "งานวิจัย · range ทุกมือ · MTT 40bb", "h1": "ได้เป็นคนแรก ทุกมือควรทำอะไร",
        "lede": "สัดส่วน raise, limp และ fold ของมือ PLO4 ทั้ง 16,432 แบบ (270,725 มือ) ในแต่ละตำแหน่ง "
                "จาก solver สอง seed เฉลี่ยกัน เกม 6 คน stack 40bb ante 0.116bb ทุกคน",
        "back": "อ่านบทสรุปงานวิจัยนี้", "seats": "ตำแหน่ง", "filters": "ตัวกรอง",
        "ranks": "อันดับไพ่", "example": "เช่น AA, JT98", "suits": "ดอก", "all": "ทั้งหมด",
        "tier": "Tier ของ Hwang", "action": "ทางหลัก", "any": "ทุกแบบ", "mixed": "ผสม",
        "sort": "เรียงตาม", "by_play": "% เล่น (มากไปน้อย)", "hand": "มือ", "rank_col": "อันดับ",
        "combos": "คอมโบ", "mix": "สัดส่วน", "more": "แสดงเพิ่มอีก 200 มือ",
        "note": "ดอกที่แสดงเป็นตัวแทนของแต่ละแบบ มือที่สลับดอกกันเล่นเหมือนกัน solver เลือกกลยุทธ์ทีละกลุ่มมือที่คล้ายกัน "
                "(780 กลุ่มที่ไม่ปน tier ของ Hwang) มือในกลุ่มเดียวกันจึงได้สัดส่วนเดียวกัน ทางหลักคือทางที่ใช้ตั้งแต่ 60% "
                "ขึ้นไป ไม่อย่างนั้นถือว่าผสม ante อยู่ใน pot แต่ไม่นับในขนาด pot-limit ก่อน flop เป็น chip EV ยังไม่ได้คิด ICM",
        "csv": "ดาวน์โหลดข้อมูลทั้งหมดเป็น CSV", "footer": "งานวิจัยจาก solver ของตามควาย",
        "played": "เล่น", "all_raise": "ของมือทั้งหมด raise", "by_tier": "แยกตาม tier ของ Hwang",
        "types": "แบบ", "combos_word": "คอมโบ", "of_hands": "ของมือ", "this_set": "ชุดนี้",
    },
    "en": {
        "lang": "en", "title": "TamKwai Range 40bb",
        "description": "Raise, limp and fold frequencies for every PLO4 hand when first in: six-handed tournament, "
                       "40bb with antes",
        "nav_ask": "Ask a chart", "nav_method": "Method", "nav_research": "Research",
        "eyebrow": "Research · every hand · MTT 40bb", "h1": "First in: what to do with every hand",
        "lede": "The raise, limp and fold mix for all 16,432 PLO4 hand types (270,725 hands) at each position, "
                "averaged over two solver seeds. Six-handed, 40bb stacks, 0.116bb ante from everyone.",
        "back": "Read the summary of this study", "seats": "Position", "filters": "Filters",
        "ranks": "Ranks", "example": "e.g. AA, JT98", "suits": "Suits", "all": "All",
        "tier": "Hwang tier", "action": "Main action", "any": "Any", "mixed": "mixed",
        "sort": "Sort by", "by_play": "% played (high to low)", "hand": "Hand", "rank_col": "Ranks",
        "combos": "Combos", "mix": "Mix", "more": "Show 200 more hands",
        "note": "Suits shown are one example of each type; hands that differ only by which suits they hold play the "
                "same. The solver picks one strategy per group of similar hands (780 groups, none mixing Hwang tiers), "
                "so hands in the same group share a mix. The main action is the one used 60% of the time or more, "
                "otherwise the hand counts as mixed. The ante is in the pot but not counted when sizing a preflop "
                "pot-limit raise. Chip EV, no ICM.",
        "csv": "Download all the data as CSV", "footer": "Research from the TamKwai solver",
        "played": "played", "all_raise": "of all hands raised", "by_tier": "By Hwang tier",
        "types": "types", "combos_word": "combos", "of_hands": "of hands", "this_set": "this set:",
    },
}


def switch(lang: str, pages: dict[str, str]) -> str:
    """Nav link to the same page in the other language."""
    other = "en" if lang == "th" else "th"
    label = "EN" if other == "en" else "ไทย"
    return f'<a href="/{pages[other]}" hreflang="{other}" lang="{other}">{label}</a>'


def alternates(pages: dict[str, str]) -> str:
    """hreflang links for the head of both language versions."""
    return "\n".join(f'<link rel="alternate" hreflang="{lang}" href="https://tamkwai.com/{pages[lang]}">'
                     for lang in LANGS)
