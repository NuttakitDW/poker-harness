"""แปลงคำถาม spot เป็นชาร์ตพรีฟล็อปใบที่ใกล้ที่สุด พร้อมคะแนนความมั่นใจ

ไม่มีคำอธิบาย ไม่มีโมเดลเขียนคำตอบ มีแค่ตารางกับตัวเลขว่าตารางนี้ตรงกับที่ถามแค่ไหน

ตัวอ่านคำถามคือ preflop.parse ตัวเดียว ไม่เรียกโมเดลหรือ API ภายนอก ตอบได้แม้ไม่มีเน็ต
เคยให้ SystemOne ของ iApp ช่วยเดาตำแหน่งผู้ถาม แต่ตัวอ่านหลักชนะทุกครั้งที่เห็นต่าง
จึงเอาออกเมื่อ 2026-09-25 ถ้าตัวอ่านหาตำแหน่งผู้ถามไม่เจอก็ตอบว่าหา spot ไม่เจอ
"""

from __future__ import annotations

import dataclasses
import re
import preflop

# สแตกที่สมมติเมื่อผู้ถามไม่บอก cash ส่วนใหญ่เล่น 100BB
DEFAULT_STACK = {"cash": 100, "tournament": 30, None: 100}
# ตัวคูณความมั่นใจเมื่อสิ่งที่ถามไม่ตรงกับตารางที่มี
SCENARIO_MISS = 0.5
VILLAIN_MISS = 0.6
# ถามแค่ตำแหน่งเดียว แต่ตารางที่ได้เป็นฝั่งเจอคนเปิด ซึ่งเป็นคนละการตัดสินใจกับการเปิดเอง
# ต้องหนักกว่าพื้นของสแตกที่ห่าง เคยถาม SB เปิด 10BB แล้วได้ SB เจอ UTG 12BB แทน SB เปิด 20BB
EXTRA_VILLAIN = 0.35
STACK_UNSTATED = 0.85
GAME_UNSTATED = 0.95
# ประเภทเกมที่พูดไว้ตาก่อนเป็นแค่ความชอบ ไม่ใช่ตัวกรอง cash มีแค่ 100/200BB
# ถ้ายึดไว้ ถามต่อว่า 40BB ก็ได้ 100BB กลับมาตลอด จึงยอมข้ามไปอีกเกมแต่หักคะแนนเท่านี้
GAME_SWITCH = 0.8
# หักตามระยะห่างแบบอัตราส่วนใน stack_gap ห่างเท่าตัว (10 กับ 20) หักราว 35% แต่ไม่ต่ำกว่าพื้น
STACK_GAP_WEIGHT = 0.5
STACK_GAP_FLOOR = 0.25
# ตำแหน่งยืมมาจากคำถามก่อนหน้า เช่น "ขอเปลี่ยนเป็น 25BB" หรือ "เจอ button ไม่ใช่ UTG"
FROM_MEMORY = 0.95

# "ไม่ใช่ UTG" ตัดตำแหน่งที่ถูกปฏิเสธทิ้งก่อนอ่าน
_NEGATION = re.compile(r"ไม่ใช่|(?<![a-z])not(?![a-z])|isn't")
# ตำแหน่งที่ตามหลังคำพวกนี้คือคู่มือ ไม่ใช่ผู้ถาม
_FACING = re.compile(r"(?:เจอ|โดน|ใส่|vs\.?|versus|against|facing)\s*$")

_THAI = re.compile(r"[฀-๿]")


NOTES = {
    "TH": {
        "confidence": "ความมั่นใจ",
        "stack": "ถาม {asked}BB ใช้ {used}BB",
        "stack_default": "ไม่ได้บอกสแตก ใช้ {used}BB",
        "game_default": "ไม่ได้บอกประเภทเกม ใช้ {game}",
        "game_switch": "{wanted} ไม่มี {stack}BB ใช้ชาร์ต{game}",
        "scenario": "ไม่มีชาร์ต {asked} ใช้ {used}",
        "villain": "ไม่มีชาร์ตเจอ {asked} ใช้เจอ {used}",
        "extra_villain": "ใช้ชาร์ตเจอ {used}",
        "memory": "ต่อจากคำถามก่อน",
        "open": "เปิดก่อน",
    },
    "EN": {
        "confidence": "confidence",
        "stack": "asked {asked}BB, using {used}BB",
        "stack_default": "no stack given, using {used}BB",
        "game_default": "no game type given, using {game}",
        "game_switch": "no {stack}BB {wanted} chart, using {game}",
        "scenario": "no {asked} chart, using {used}",
        "villain": "no chart vs {asked}, using vs {used}",
        "extra_villain": "using chart vs {used}",
        "memory": "carried from the last question",
        "open": "open",
    },
}


@dataclasses.dataclass(frozen=True)
class Spot:
    """ชาร์ตที่เลือกให้คำถามหนึ่ง"""

    book: dict
    chart: dict
    hands: tuple[str, ...]
    confidence: float
    notes: tuple[str, ...]
    lang: str
    # สิ่งที่ผู้ใช้บอกมาแล้วรวมกับตาก่อน ๆ เก็บไว้ต่อคำถามถัดไป ไม่มีค่าที่สมมติเอง
    request: preflop.Request = preflop.Request()

    @property
    def key(self) -> tuple:
        return (self.book["game"], self.chart["page"], self.chart["hero"],
                self.chart.get("villain"), self.chart["scenario"], self.chart["stack"], self.hands)


def language_of(text: str) -> str:
    """มีตัวอักษรไทยถือว่าถามภาษาไทย ป้ายบนจอจะเป็นภาษาเดียวกับที่ถาม"""
    return "TH" if _THAI.search(text) else "EN"


def _looks_like_spot(prompt: str, request: preflop.Request) -> bool:
    """มีมือ สแตก หรือคำขอชาร์ตอยู่ในคำถาม"""
    lowered = prompt.lower()
    return bool(request.stack or preflop.hands_in(prompt)
                or any(word in lowered for word in (*preflop.CHART_WORDS, *preflop.HOLD_WORDS)))


def stack_gap(have: int, wanted: int) -> float:
    """ระยะห่างของสแตกเทียบกับสแตกที่ถาม ถาม 16BB ได้ 12 หรือ 20 ห่างเท่ากันคือ 25%

    หารด้วยสแตกที่ถาม ถาม 10BB ได้ 20BB ห่างเท่าตัว แต่ถาม 100BB ได้ 80BB ห่างแค่ 20%
    """
    return abs(have - wanted) / wanted


def _fit(book: dict, chart: dict, request: preflop.Request, scenario: str,
         lang: str) -> tuple[float, list[str]]:
    """ตารางนี้ตรงกับที่ถามแค่ไหน คืน (ตัวคูณ, หมายเหตุ)

    request.game ตรงนี้คือเกมที่ชอบ ถ้าผู้ใช้พูดในตานี้ lookup กรองเล่มอื่นทิ้งไปก่อนแล้ว
    """
    words = NOTES[lang]
    score = 1.0
    notes: list[str] = []
    if chart["scenario"].upper() != scenario.upper():
        score *= SCENARIO_MISS
        notes.append(words["scenario"].format(asked=scenario, used=chart["scenario"]))
    villain = chart.get("villain")
    if request.villain and villain != request.villain:
        score *= VILLAIN_MISS
        notes.append(words["villain"].format(asked=request.villain,
                                             used=villain or words["open"]))
    elif not request.villain and villain:
        score *= EXTRA_VILLAIN
        notes.append(words["extra_villain"].format(used=villain))
    if request.stack:
        gap = stack_gap(chart["stack"], request.stack)
        if gap:
            score *= max(STACK_GAP_FLOOR, 1 - STACK_GAP_WEIGHT * gap)
            notes.append(words["stack"].format(asked=request.stack, used=chart["stack"]))
    else:
        wanted = DEFAULT_STACK[request.game]
        gap = stack_gap(chart["stack"], wanted)
        score *= STACK_UNSTATED * max(STACK_GAP_FLOOR, 1 - STACK_GAP_WEIGHT * gap)
        notes.append(words["stack_default"].format(used=chart["stack"]))
    game_name = preflop.WORDS[lang][book["game"]]
    if request.game is None:
        score *= GAME_UNSTATED
        notes.append(words["game_default"].format(game=game_name))
    elif book["game"] != request.game:
        score *= GAME_SWITCH
        notes.append(words["game_switch"].format(
            wanted=preflop.WORDS[lang][request.game], stack=request.stack, game=game_name))
    return score, notes


def _drop_negated(text: str) -> str:
    """ตัดตำแหน่งแรกหลังคำปฏิเสธ "เจอ button ไม่ใช่เจอ UTG" เหลือ "เจอ button" """
    negation = _NEGATION.search(text)
    if negation is None:
        return text
    after = [found for found in preflop.seat_mentions(text) if found[0] >= negation.start()]
    if not after:
        return text
    return text[:negation.start()] + text[after[0][1]:]


def read(prompt: str) -> preflop.Request:
    """อ่านคำถามหนึ่งตา ตำแหน่งเดียวที่ตามหลัง "เจอ" ถือเป็นคู่มือ ปล่อยผู้ถามว่างไว้ให้ยืมจากตาก่อน"""
    text = _drop_negated(preflop.normalize_seats(prompt))
    request = preflop.parse(text)
    mentions = preflop.seat_mentions(text)
    seats = {name for _, _, name in mentions}
    if len(seats) == 1 and _FACING.search(text[:mentions[0][0]]):
        return dataclasses.replace(request, hero=None, villain=mentions[0][2])
    return request


def merge(new: preflop.Request, memory: preflop.Request | None) -> preflop.Request:
    """เติมสิ่งที่ตานี้ไม่ได้บอกจากตาก่อน เปลี่ยนผู้ถามเมื่อไรก็ทิ้งคู่มือกับสถานการณ์เดิม"""
    if memory is None:
        return new
    base = memory
    if new.hero and new.hero != memory.hero:
        base = dataclasses.replace(memory, villain=None, scenario=None, shovers=())
    return preflop.Request(game=new.game or base.game, stack=new.stack or base.stack,
                           hero=new.hero or base.hero, villain=new.villain or base.villain,
                           scenario=new.scenario or base.scenario,
                           players=new.players or base.players,
                           pushfold=new.pushfold or base.pushfold,
                           # ante 0 คือบอกว่าไม่มี ante ต้องไม่ถูกแทนด้วยค่าของตาก่อน
                           # เปลี่ยนคนจ่าย ante โดยไม่บอกจำนวน ใช้ค่าเริ่มของแบบใหม่ ไม่ยืมจำนวนเดิม
                           ante=new.ante if new.ante is not None
                           else (None if new.ante_mode else base.ante),
                           ante_mode=new.ante_mode or base.ante_mode,
                           # () คือขอ chip EV ต้องไม่ถูกแทนด้วยรางวัลของตาก่อน
                           # พูด icm หลังขอ chip EV คือกลับไปใช้ ICM แต่รางวัลจริงที่บอกไว้ยังใช้ต่อ
                           payouts=new.payouts if new.payouts is not None
                           else (None if new.icm and base.payouts == () else base.payouts),
                           icm=new.icm or (base.icm and new.payouts is None),
                           # บอกเหลือเป็น % หรือเป็นจำนวนคน อย่างใดอย่างหนึ่ง ของใหม่แทนของเดิม
                           # bubble หรือ final table ใหม่แทนจำนวนคนเหลือเดิม และกลับกัน
                           left_pct=new.left_pct if new.left_pct is not None
                           else (None if new.players_left or new.stage_word else base.left_pct),
                           players_left=new.players_left or (
                               None if new.left_pct is not None or new.stage_word else base.players_left),
                           stage_word=new.stage_word or (
                               None if new.left_pct is not None or new.players_left else base.stage_word),
                           entrants=new.entrants or base.entrants,
                           paid_pct=new.paid_pct or base.paid_pct,
                           field_avg=new.field_avg or base.field_avg,
                           # คู่มือใหม่คนเดียวแทนคนยัดหมดชุดเดิมทั้งหมด
                           shovers=new.shovers or (() if new.villain else base.shovers))


def lookup(prompt: str, lang: str | None = None,
           memory: preflop.Request | None = None) -> Spot | None:
    """ชาร์ตที่ใกล้คำถามที่สุด คืน None ถ้าไม่รู้แม้แต่ว่าผู้ถามนั่งตรงไหน

    memory คือ Spot.request ของตาก่อน ใช้ตอบคำถามต่อเนื่องอย่าง "ขอเปลี่ยนเป็น 25BB"
    """
    lang = lang or language_of(prompt)
    words = NOTES[lang]
    said = read(prompt)
    request = merge(said, memory)
    if said == preflop.Request() and not _looks_like_spot(prompt, said):
        # ไม่ได้พูดอะไรเกี่ยวกับ spot เลย เช่น "ฮัลโหล ได้ยินไหม" อย่าวาดชาร์ตเดิมซ้ำ
        return None
    hero = request.hero
    if hero is None:
        return None
    # ผู้ถามมาจากตาก่อน เช่น "ขอเปลี่ยนเป็น 25BB" ไม่ได้บอกตำแหน่งในตานี้
    from_memory = said.hero is None
    trust = FROM_MEMORY if from_memory else 1.0
    hero_notes = [words["memory"]] if from_memory else []
    request = dataclasses.replace(request, hero=hero)
    scenario = request.scenario or "RFI"

    best = None
    for book in preflop.books():
        # ตัวกรองใช้เฉพาะเกมที่พูดในตานี้ เกมที่จำมาจากตาก่อนไปหักคะแนนใน _fit แทน
        if said.game and book["game"] != said.game:
            continue
        for chart in book["charts"]:
            if chart["hero"] != hero:
                continue
            score, notes = _fit(book, chart, request, scenario, lang)
            # คะแนนเท่ากันเพราะชนพื้น ให้สแตกที่ใกล้กว่าชนะ ห่างเท่ากันเอาสแตกที่สั้นกว่า ไม่ใช่เลขหน้า
            wanted = request.stack or DEFAULT_STACK[request.game]
            rank = (-score, stack_gap(chart["stack"], wanted), chart["stack"], chart["page"])
            if best is None or rank < best[0]:
                best = (rank, book, chart, score, notes)
    if best is None:
        return None
    _, book, chart, score, notes = best
    confidence = round(trust * score, 2)
    return Spot(book, chart, tuple(preflop.hands_in(prompt)), confidence,
                tuple(hero_notes + notes), lang, request)


def confidence_line(spot: Spot) -> str:
    """บรรทัดคะแนนความมั่นใจใต้ตาราง พร้อมเหตุที่หักคะแนน"""
    words = NOTES[spot.lang]
    reasons = f"  ({'; '.join(spot.notes)})" if spot.notes else ""
    return f"{words['confidence']} {spot.confidence * 100:.0f}%{reasons}"
