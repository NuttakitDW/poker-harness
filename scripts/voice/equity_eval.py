"""ประเมินมือ Hold'em เจ็ดใบทีละหลายล้านบอร์ด โดยใช้คะแนนมือจาก pokerkit

pokerkit ประเมินมือทีละมือราว 140 ไมโครวินาที ไล่ 1.7 ล้านบอร์ดของ preflop ใช้เวลาหลายนาที
ที่นี่จึงดึงคะแนนมือห้าใบจาก StandardLookup ของ pokerkit มาทำตารางเจ็ดใบครั้งเดียว
แล้วประเมินทุกบอร์ดพร้อมกันด้วย numpy คะแนนที่ได้คือ Entry.index ของ pokerkit ตัวเดียวกัน
"""

from __future__ import annotations

import dataclasses
import functools
import itertools
import pathlib
import threading
from typing import Iterable

import numpy as np
from pokerkit import Card, StandardHighHand

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "tmp"
TABLE_FILE = CACHE_DIR / "equity-tables.npz"

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK_SIZE = 52
BOARD_SIZE = 5
HOLE_SIZE = 2
ALL_BOARDS = 2_598_960

_PRIMES = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41], dtype=np.int64)
_LOCK = threading.RLock()
_HOLE_INDEX = {pair: index for index, pair in
               enumerate(itertools.combinations_with_replacement(range(13), HOLE_SIZE))}


def card_text(cards: Iterable[int]) -> str:
    """เลข 0-51 กลับเป็นข้อความแบบ pokerkit เช่น Ah"""
    return "".join(f"{RANKS[card // 4]}{SUITS[card % 4]}" for card in cards)


def card_index(card: Card) -> int:
    return RANKS.index(card.rank.value) * 4 + SUITS.index(card.suit.value)


def bits(cards: Iterable[int]) -> int:
    return sum(1 << card for card in cards)


# ---------------------------------------------------------------- ตารางจาก pokerkit

def _card(rank: int, suit: int) -> Card:
    return next(iter(Card.parse(f"{RANKS[rank]}{SUITS[suit]}")))


def _best(cards: list[Card]) -> int:
    lookup = StandardHighHand.lookup
    return max(lookup.get_entry(five).index for five in itertools.combinations(cards, 5))


def _build_tables() -> dict[str, np.ndarray]:
    """ตารางมือไม่มีฟลัช (แต้มบอร์ดห้าใบ x แต้มในมือ) กับตารางฟลัช (bitmask แต้มของดอกเดียว)

    มือไม่มีฟลัชจัดดอกวนไปจนไม่มีห้าใบไหนดอกเดียวกัน ถ้าจริง ๆ มีฟลัช ตารางฟลัชให้ค่าสูงกว่าอยู่แล้ว
    เพราะไพ่ชุดเดียวกันถ้าเป็นดอกเดียวย่อมดีกว่าตอนไม่เป็นดอกเดียว การเอาค่ามากสุดของสองตารางจึงแม่นเสมอ
    """
    boards = [combo for combo in itertools.combinations_with_replacement(range(13), BOARD_SIZE)
              if max(combo.count(rank) for rank in combo) <= 4]
    keys = np.array([int(np.prod(_PRIMES[list(board)])) for board in boards], dtype=np.int64)
    order = np.argsort(keys)
    boards = [boards[index] for index in order]
    seen: dict[tuple[int, ...], int] = {}
    unsuited = np.full((len(boards), len(_HOLE_INDEX)), -1, dtype=np.int16)
    for row, board in enumerate(boards):
        for hole, column in _HOLE_INDEX.items():
            seven = tuple(sorted(board + hole))
            if max(seven.count(rank) for rank in hole) > 4:
                continue
            if seven not in seen:
                seen[seven] = _best([_card(rank, index % 4) for index, rank in enumerate(seven)])
            unsuited[row, column] = seen[seven]
    flush = np.full(1 << 13, -1, dtype=np.int16)
    for mask in range(1 << 13):
        if mask.bit_count() >= 5:
            flush[mask] = _best([_card(rank, 0) for rank in range(13) if mask >> rank & 1])
    return {"board_keys": keys[order], "unsuited": unsuited, "flush": flush}


@functools.lru_cache(maxsize=1)
def tables() -> dict[str, np.ndarray]:
    """อ่านตารางจากไฟล์ถ้ามี ไม่มีก็สร้างจาก pokerkit ราวสี่วินาทีแล้วเก็บไว้"""
    with _LOCK:
        if TABLE_FILE.exists():
            with np.load(TABLE_FILE) as saved:
                return {key: saved[key] for key in saved.files}
        built = _build_tables()
        CACHE_DIR.mkdir(exist_ok=True)
        np.savez_compressed(TABLE_FILE, **built)
        return built


# ---------------------------------------------------------------- บอร์ด

@dataclasses.dataclass(frozen=True)
class Boards:
    """บอร์ดห้าใบหลายบอร์ด เก็บเฉพาะสิ่งที่ต้องใช้ประเมินมือ"""

    rank_row: np.ndarray    # แถวในตาราง unsuited ของแต้มห้าใบบนบอร์ด
    suit_bits: np.ndarray   # (บอร์ด, 4) bitmask แต้มของแต่ละดอก
    card_bits: np.ndarray   # bitmask ไพ่ทั้งห้าใบ ใช้กรองบอร์ดที่ชนไพ่ในมือ

    def where(self, keep: np.ndarray) -> "Boards":
        return Boards(self.rank_row[keep], self.suit_bits[keep], self.card_bits[keep])

    def __len__(self) -> int:
        return len(self.rank_row)


def boards_of(cards: np.ndarray) -> Boards:
    """อาร์เรย์ไพ่ (บอร์ด, 5) ที่เก็บเป็นเลข 0-51 ให้พร้อมประเมิน"""
    ranks = cards // 4
    suits = cards % 4
    keys = np.prod(_PRIMES[ranks], axis=1)
    rows = np.searchsorted(tables()["board_keys"], keys).astype(np.int32)
    rank_bits = np.int64(1) << ranks.astype(np.int64)
    suit_bits = np.stack([np.where(suits == suit, rank_bits, 0).sum(axis=1)
                          for suit in range(4)], axis=1).astype(np.int32)
    card_bits = (np.int64(1) << cards.astype(np.int64)).sum(axis=1)
    return Boards(rows, suit_bits, card_bits)


@functools.lru_cache(maxsize=1)
def all_boards() -> Boards:
    """ทุกบอร์ด preflop 2,598,960 แบบ สร้างครั้งเดียวแล้วกรองตามไพ่ที่ถูกใช้ไป"""
    flat = np.fromiter(itertools.chain.from_iterable(
        itertools.combinations(range(DECK_SIZE), BOARD_SIZE)), dtype=np.int8,
        count=ALL_BOARDS * BOARD_SIZE)
    return boards_of(flat.reshape(ALL_BOARDS, BOARD_SIZE))


def runouts(board: tuple[int, ...], dead: int = 0) -> Boards:
    """ทุกบอร์ดที่เป็นไปได้ต่อจากไพ่กลางที่เปิดแล้ว โดยไม่ใช้ไพ่ใน dead"""
    if not board:
        every = all_boards()
        return every if not dead else every.where((every.card_bits & dead) == 0)
    used = dead | bits(board)
    left = [card for card in range(DECK_SIZE) if not used >> card & 1]
    rest = list(itertools.combinations(left, BOARD_SIZE - len(board)))
    cards = np.array([board + extra for extra in rest], dtype=np.int8)
    return boards_of(cards.reshape(len(rest), BOARD_SIZE))


def strength(hole: tuple[int, int], boards: Boards) -> np.ndarray:
    """คะแนนมือเจ็ดใบบนทุกบอร์ด ค่ามากคือมือดีกว่า ตรงกับ Entry.index ของ pokerkit"""
    table = tables()
    ranks = tuple(sorted(card // 4 for card in hole))
    best = table["unsuited"][boards.rank_row, _HOLE_INDEX[ranks]]
    for suit in range(4):
        extra = sum(1 << (card // 4) for card in hole if card % 4 == suit)
        best = np.maximum(best, table["flush"][boards.suit_bits[:, suit] | extra])
    return best


def made_hand(hole: tuple[int, int], board: tuple[int, ...]) -> str:
    """ชื่อมือที่ทำได้แล้วตามที่ pokerkit จัด เช่น One pair ต้องมีบอร์ดอย่างน้อยสามใบ"""
    if len(board) < 3:
        return ""
    return StandardHighHand.from_game(card_text(hole), card_text(board)).entry.label.value
