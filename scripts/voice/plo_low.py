"""ฝั่ง low ของมือ PLO Hi/Lo (eight-or-better)

โมเดลเคยตอบว่า A-9-9-2 "ไม่มี low potential เลย" ทั้งที่ A-2 คือ low ที่ดีที่สุดในเกม
จึงให้โค้ดบอกข้อเท็จจริงฝั่ง low ว่ามือนี้มีไพ่ต่ำคู่ไหน เป็น nut low ไหม
และบน flop ได้ nut low หรือ nut low draw บ่อยแค่ไหน

low ต้องใช้ไพ่ในมือสองใบพอดีที่อันดับไม่ซ้ำกันและไม่เกิน 8 กับไพ่ board สามใบที่ไม่ซ้ำกัน
low ที่ดีที่สุดจึงขึ้นกับว่าไพ่ต่ำสองใบไหนที่ยังไม่อยู่บน board ถ้า A หรือ 2 ของเราออกบน board
low ของเราโดน counterfeit ไพ่ต่ำใบที่สามในมือคือตัวกันไว้
"""

from __future__ import annotations

import collections
import dataclasses
import functools
import itertools
import math
import re

# ค่าฝั่ง low: A เป็น 1 ไพ่ที่เกิน 8 ใช้ทำ low ไม่ได้
LOW = {"A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8}
LOW_RANKS = tuple(range(1, 9))
LOW_NAME = {value: rank for rank, value in LOW.items()}
RANKS = "AKQJT98765432"
DECK_COPIES = 4
ALL_FLOPS = math.comb(48, 3)
BOARD_LOW_FOR_LOW = 3

# คำที่บอกว่าเป็นเกม Hi/Lo รวมคำที่ถอดเสียงเพี้ยนอย่าง "ไฮโร" และ "Ace of Better"
_HILO = re.compile(
    r"hi\s*/?\s*-?\s*lo|ไฮ\s*-?\s*โ[ลร]|eight\s*-?\s*or\s*-?\s*better|8\s*or\s*better|"
    r"(?:ace|eight|8)\s*of\s*better|plo\s*-?\s*8|omaha\s*8|\bo8\b|split\s*pot",
    re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class LowStudy:
    """ฝั่ง low ของมือหนึ่ง อัตราเป็นสัดส่วนของ flop ทั้งหมด"""

    hand: str
    low_cards: str
    nut_low_cards: bool
    nut_low_rate: float
    nut_low_draw_rate: float
    no_low_rate: float


def is_hilo(text: str) -> bool:
    """คำถามพูดถึงเกม Hi/Lo ไหม"""
    return bool(_HILO.search(text or ""))


def _best_pair(board: set[int]) -> tuple[int, int]:
    """ไพ่ต่ำสองใบที่ดีที่สุดที่คนถือได้ คืออันดับต่ำสุดสองตัวที่ยังไม่อยู่บน board"""
    free = [rank for rank in LOW_RANKS if rank not in board]
    return free[0], free[1]


def _hero_pair(lows: set[int], board: set[int]) -> tuple[int, ...]:
    """ไพ่ต่ำสองใบที่ดีที่สุดของเรา ไพ่ที่ซ้ำกับ board ช่วยทำ low ไม่ได้"""
    return tuple(sorted(rank for rank in lows if rank not in board))[:2]


@functools.lru_cache(maxsize=64)
def study(hand: str) -> LowStudy:
    """นับทุก flop ว่ามือนี้ได้ nut low หรือ nut low draw บ่อยแค่ไหน"""
    lows = {LOW[rank] for rank in hand if rank in LOW}
    ordered = sorted(lows)
    unseen = collections.Counter({rank: DECK_COPIES for rank in RANKS})
    unseen.subtract(hand)
    made = draw = none = 0.0
    for flop in itertools.combinations_with_replacement(RANKS, 3):
        needed = collections.Counter(flop)
        weight = math.prod(math.comb(unseen[rank], count) for rank, count in needed.items())
        if not weight:
            continue
        share = weight / ALL_FLOPS
        board = {LOW[rank] for rank in flop if rank in LOW}
        if len(board) < BOARD_LOW_FOR_LOW - 1:
            none += share
            continue
        is_nut = len(_hero_pair(lows, board)) == 2 and _hero_pair(lows, board) == _best_pair(board)
        if len(board) >= BOARD_LOW_FOR_LOW:
            made += share * is_nut
        else:
            draw += share * is_nut
    low_cards = "-".join(LOW_NAME[rank] for rank in ordered[:2]) if len(ordered) >= 2 else ""
    return LowStudy(hand, low_cards, ordered[:2] == [1, 2], made, draw, none)


def _percent(share: float) -> str:
    return f"{share * 100:.1f}%"


def block_lines(hand: str) -> list[str]:
    """ข้อเท็จจริงฝั่ง low สำหรับส่งให้โมเดล"""
    result = study(hand)
    if not result.low_cards:
        return ["- ฝั่ง low: มีไพ่ A ถึง 8 ไม่ถึงสองใบ ทำ low ไม่ได้เลย เป็นมือ high อย่างเดียว"]
    count = sum(1 for rank in dict.fromkeys(hand) if rank in LOW)
    quality = ("เป็นคู่ low ที่ดีที่สุดในเกม ได้ nut low draw ทุกครั้งที่ board ไม่มี A หรือ 2"
               if result.nut_low_cards else
               "ไม่ใช่ nut low แพ้ A-2 ได้")
    lines = [
        f"- ฝั่ง low: ไพ่ต่ำที่ใช้ทำ low คือ {result.low_cards} {quality}",
        f"- flop ที่ได้ nut low ทันที: {_percent(result.nut_low_rate)}"
        f" และได้ nut low draw: {_percent(result.nut_low_draw_rate)}",
    ]
    if count < BOARD_LOW_FOR_LOW:
        either = " หรือ ".join(result.low_cards.split("-"))
        lines.append(f"- มีไพ่ต่ำแค่สองใบ ถ้า {either} ออกบน board low จะโดน counterfeit ไม่มีใบที่สามกันไว้")
    else:
        lines.append("- มีไพ่ต่ำสามใบขึ้นไป กัน counterfeit ได้เมื่อไพ่ต่ำใบหนึ่งออกบน board")
    high = [rank for rank in dict.fromkeys(hand) if rank not in LOW]
    if high:
        lines.append(f"- ไพ่ {' '.join(high)} ช่วยฝั่ง high อย่างเดียว set หรือ straight บน board ไพ่ต่ำเสี่ยงได้แค่ครึ่ง pot")
    return lines
