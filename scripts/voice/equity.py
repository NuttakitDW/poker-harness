"""equity ของ Hold'em แบบไล่ทุก runout จริง สำหรับเครื่องมือที่ลูกชุบเรียกใช้

รับได้ทั้งมือเจาะจง (KsKc) และ range ตามรูปแบบของ pokerkit (QQ+,AKs) ผู้เล่นสองถึงหกคน
คะแนนมือมาจาก pokerkit ผ่าน equity_eval จึงตรงกับ pokerkit ทุกบอร์ด ไม่ได้สุ่มหรือเดา

คู่มือที่เหมือนกันเมื่อสลับดอก (AcAh-KsKc กับ AdAs-KhKc) ให้ผลเท่ากันเสมอ
จึงจำผลไว้ด้วยรูปมาตรฐานใน tmp/equity.sqlite สคริปต์ build_equity_cache.py
คิดคู่มือ preflop แบบสองคนไว้ล่วงหน้าครบทุกรูป range ใหญ่แค่ไหนก็ตอบได้ทันทีแบบ exact
"""

from __future__ import annotations

import dataclasses
import itertools
import pathlib
import random
import re
import sqlite3
import threading
import time
from typing import Sequence

import numpy as np
from pokerkit import Card, parse_range

import equity_eval as ev

MEMO_FILE = ev.CACHE_DIR / "equity.sqlite"
MAX_PLAYERS = 6
ANY_HAND = {"any", "random", "xx", "any two", "anytwo", "100%"}
# คู่มือที่ยังไม่เคยคิดต้องไล่บอร์ดใหม่ทีละคู่ preflop คู่ละราว 0.06 วินาที
# ถ้างานเกินงบนี้ผู้ฟังรอนานเกินไป จึงสุ่มคู่มือมาคิดแทนและบอกตรง ๆ ว่าเป็นค่าประมาณ
EXACT_BUDGET_SECONDS = 12.0
PREFLOP_SECONDS_PER_PLAYER = 0.03
POSTFLOP_SECONDS_PER_MATCHUP = 0.002
MAX_MULTIWAY_MATCHUPS = 400_000
SAMPLE_SEED = 20260924

# "A7s-A2s" คือไพ่สูงใบเดียวกัน kicker ไล่ลงมา เป็นรูปแบบมาตรฐานที่คนเขียนกัน
# แต่ pokerkit รับแค่ช่วงที่เลื่อนทั้งสองใบพร้อมกันอย่าง "T9s-54s" จึงแตกเป็นทีละมือก่อนส่งต่อ
_KICKER_SPAN = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so]?)-\1([2-9TJQKA])\3$")
_PERMS = np.array(list(itertools.permutations(range(4))), dtype=np.int16)
_LOCK = threading.RLock()


class EquityError(ValueError):
    """ข้อมูลเข้าผิดรูป ข้อความในนี้ส่งกลับให้โมเดลอ่านและแก้เองได้"""


# ---------------------------------------------------------------- ข้อมูลเข้า

def parse_cards(text: str) -> tuple[int, ...]:
    """ไพ่เจาะจงเช่น Td7c2h คืนเป็นเลข 0-51"""
    cleaned = text.replace(" ", "").replace(",", "")
    if not cleaned:
        return ()
    try:
        cards = tuple(ev.card_index(card) for card in Card.parse(cleaned))
    except (ValueError, KeyError) as error:
        raise EquityError(f"อ่านไพ่ '{text}' ไม่ออก ใช้รูปแบบเช่น Td7c2h: {error}") from error
    if len(set(cards)) != len(cards):
        raise EquityError(f"ไพ่ '{text}' มีใบซ้ำกัน")
    return cards


def _expand_kicker_spans(text: str) -> str:
    """แตก "A7s-A4s" เป็น "A7s,A6s,A5s,A4s" ส่วนอื่นส่งให้ pokerkit ตามเดิม"""
    parts = []
    for token in re.split(r"[\s,;]+", text.strip()):
        match = _KICKER_SPAN.match(token)
        if not match:
            parts.append(token)
            continue
        high, first, kind, last = match.groups()
        low, top = sorted((ev.RANKS.index(first), ev.RANKS.index(last)))
        parts.extend(f"{high}{ev.RANKS[rank]}{kind}" for rank in range(low, top + 1)
                     if ev.RANKS[rank] != high)
    return ",".join(part for part in parts if part)


def parse_hand_range(text: str) -> list[tuple[int, int]]:
    """มือเจาะจง (KsKc) หรือ range ตามรูปแบบของ pokerkit (QQ+,AKs,ATo+,JJ-99)"""
    cleaned = text.strip()
    if cleaned.lower() in ANY_HAND:
        return list(itertools.combinations(range(ev.DECK_SIZE), ev.HOLE_SIZE))
    try:
        combos = parse_range(_expand_kicker_spans(cleaned))
    except (ValueError, KeyError) as error:
        raise EquityError(f"อ่าน '{text}' ไม่ออก ใช้รูปแบบเช่น KsKc, QQ+, AKs, ATo+, JJ-99: {error}") from error
    holes = sorted({tuple(sorted(map(ev.card_index, combo))) for combo in combos
                    if len(combo) == ev.HOLE_SIZE})
    if not holes:
        raise EquityError(f"'{text}' ไม่มีมือ Hold'em สองใบเลย")
    return holes


# ---------------------------------------------------------------- ผลของคู่มือหนึ่งชุด

@dataclasses.dataclass(frozen=True)
class Share:
    """ผลของคู่มือหนึ่งชุด ต่อผู้เล่นแต่ละคน เป็นสัดส่วนของบอร์ดทั้งหมด"""

    equity: tuple[float, ...]
    win: tuple[float, ...]
    tie: tuple[float, ...]
    runouts: int


def exact_share(holes: Sequence[tuple[int, int]], board: tuple[int, ...]) -> Share:
    """ไล่ทุกบอร์ดของคู่มือนี้ แบ่ง pot เท่ากันเมื่อเสมอ"""
    boards = ev.runouts(board, ev.bits(itertools.chain.from_iterable(holes)))
    scores = np.stack([ev.strength(hole, boards) for hole in holes])
    top = scores == scores.max(axis=0)
    winners = top.sum(axis=0)
    alone = winners == 1
    return Share(tuple(map(float, (top / winners).mean(axis=1))),
                 tuple(map(float, (top & alone).mean(axis=1))),
                 tuple(map(float, (top & ~alone).mean(axis=1))), len(boards))


def canonical_keys(matchups: np.ndarray, board: tuple[int, ...]) -> list[str]:
    """รูปมาตรฐานของแต่ละคู่มือเมื่อสลับดอกได้อิสระ ลำดับผู้เล่นคงเดิม

    ลองสลับดอกครบ 24 แบบแล้วเลือกแถวที่น้อยที่สุดแบบพจนานุกรม ทำพร้อมกันทุกคู่ด้วย numpy
    matchups มีรูป (คู่, ผู้เล่น, 2)
    """
    count = len(matchups)
    cards = matchups.astype(np.int16)
    board_cards = np.array(board, dtype=np.int16)
    picked = np.arange(count)
    best = None
    for perm in _PERMS:
        hands = np.sort(cards // 4 * 4 + perm[cards % 4], axis=2).reshape(count, -1)
        shown = np.sort(board_cards // 4 * 4 + perm[board_cards % 4])
        rows = np.concatenate([hands, np.broadcast_to(shown, (count, len(board)))], axis=1)
        if best is None:
            best = rows.copy()
            continue
        differ = rows != best
        first = differ.argmax(axis=1)
        smaller = differ.any(axis=1) & (rows[picked, first] < best[picked, first])
        best[smaller] = rows[smaller]
    return [row.tobytes().hex() for row in best.astype(np.uint8)]


class Memo:
    """จำผลคู่มือที่เคยคิดแล้ว ข้ามรอบการรันด้วย sqlite ใน tmp"""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.known: dict[str, Share] | None = None

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("create table if not exists share (key text primary key, value text)")
        return connection

    def load(self) -> dict[str, Share]:
        if self.known is None:
            with self._connect() as connection:
                rows = connection.execute("select key, value from share").fetchall()
            self.known = {key: _decode(value) for key, value in rows}
        return self.known

    def save(self, fresh: dict[str, Share]) -> None:
        if not fresh:
            return
        self.load().update(fresh)
        try:
            with self._connect() as connection:
                connection.executemany("insert or replace into share values (?, ?)",
                                       [(key, _encode(share)) for key, share in fresh.items()])
        except (sqlite3.OperationalError, OSError):
            pass  # read-only disk (Vercel): the results stay in memory for this instance


def _encode(share: Share) -> str:
    return ";".join([",".join(map(repr, share.equity)), ",".join(map(repr, share.win)),
                     ",".join(map(repr, share.tie)), str(share.runouts)])


def _decode(text: str) -> Share:
    parts = text.split(";")
    equity, win, tie = (tuple(map(float, part.split(","))) for part in parts[:3])
    return Share(equity, win, tie, int(parts[3]))


MEMO = Memo(MEMO_FILE)


# ---------------------------------------------------------------- ผลรวม

@dataclasses.dataclass(frozen=True)
class Player:
    label: str
    combos: int
    equity: float
    win: float
    tie: float
    made_hand: str = ""  # มือที่ทำได้แล้วบนบอร์ดตอนนี้ ใส่เฉพาะมือเจาะจงหลัง flop


@dataclasses.dataclass(frozen=True)
class Result:
    players: tuple[Player, ...]
    board: str
    exact: bool
    matchups: int
    matchups_used: int
    runouts: int
    seconds: float
    margin: float  # ราวสองเท่าของ standard error ถ้าเป็นค่าประมาณ ไม่งั้นเป็นศูนย์

    def as_dict(self) -> dict:
        return {
            "board": self.board or "(preflop)",
            "method": "exact enumeration" if self.exact else "sampled matchups (approximate)",
            "exact": self.exact,
            "players": [{"hand": p.label, "combos": p.combos,
                         "equity_pct": round(p.equity * 100, 2),
                         "win_pct": round(p.win * 100, 2),
                         "tie_pct": round(p.tie * 100, 2),
                         **({"made_hand_now": p.made_hand} if p.made_hand else {})}
                        for p in self.players],
            "matchups": self.matchups,
            "matchups_computed": self.matchups_used,
            "runouts_per_matchup": self.runouts,
            "margin_pct": round(self.margin * 100, 2),
            "seconds": round(self.seconds, 2),
        }


@dataclasses.dataclass(frozen=True)
class _Totals:
    equity: np.ndarray
    win: np.ndarray
    tie: np.ndarray
    exact: bool
    used: int
    runouts: int
    margin: float = 0.0


# ---------------------------------------------------------------- วิธีคิด

def pair_matchups(first: list, second: list) -> np.ndarray:
    """ทุกคู่มือของสองคนที่ไม่ชนกัน ทำด้วย numpy เพราะ any vs any มีเป็นล้านคู่"""
    a = np.array(first, dtype=np.int16)
    b = np.array(second, dtype=np.int16)
    a_bits = (np.int64(1) << a.astype(np.int64)).sum(axis=1)
    b_bits = (np.int64(1) << b.astype(np.int64)).sum(axis=1)
    left, right = np.nonzero((a_bits[:, None] & b_bits[None, :]) == 0)
    return np.stack([a[left], b[right]], axis=1)


def _multiway_matchups(ranges: Sequence[list]) -> np.ndarray:
    found = []
    for holes in itertools.product(*ranges):
        flat = [card for hole in holes for card in hole]
        if len(set(flat)) == len(flat):
            found.append(holes)
            if len(found) > MAX_MULTIWAY_MATCHUPS:
                raise EquityError("range ใหญ่เกินไปสำหรับหลายทาง ลองแคบ range ลงหรือลดจำนวนผู้เล่น")
    return np.array(found, dtype=np.int16).reshape(len(found), len(ranges), ev.HOLE_SIZE)


def _heads_up_postflop(first: list, second: list, board: tuple[int, ...]) -> _Totals:
    """หลัง flop บอร์ดมีไม่เกินพันกว่าแบบ จึงคิดคะแนนทุกมือบนทุกบอร์ดครั้งเดียวแล้วเทียบกันทั้งแผง

    แต่ละคู่มือมีจำนวนบอร์ดที่เป็นไปได้เท่ากัน ค่าเฉลี่ยของทุกคู่จึงเป็น equity ของ range ตรง ๆ
    """
    boards = ev.runouts(board)
    union = sorted(set(first) | set(second))
    row = {hole: index for index, hole in enumerate(union)}
    scores = np.stack([ev.strength(hole, boards) for hole in union])
    hole_bits = np.array([ev.bits(hole) for hole in union], dtype=np.int64)
    rivals = np.array([row[hole] for hole in second])
    sums = np.zeros((3, 2))
    pairs = 0
    per_pair = 0
    for hole in first:
        mine = row[hole]
        others = rivals[(hole_bits[rivals] & hole_bits[mine]) == 0]
        if not len(others):
            continue
        valid = (boards.card_bits[None, :] & (hole_bits[others] | hole_bits[mine])[:, None]) == 0
        ahead = ((scores[mine][None, :] > scores[others]) & valid).sum(axis=1)
        level = ((scores[mine][None, :] == scores[others]) & valid).sum(axis=1)
        total = valid.sum(axis=1)
        behind = total - ahead - level
        sums[0] += [((ahead + level / 2) / total).sum(), ((behind + level / 2) / total).sum()]
        sums[1] += [(ahead / total).sum(), (behind / total).sum()]
        sums[2] += [(level / total).sum()] * 2
        pairs += len(others)
        per_pair = int(total[0])
    if not pairs:
        raise EquityError("มือของผู้เล่นชนกันเองทุกชุด ไม่มีทางเกิดขึ้นพร้อมกัน")
    return _Totals(sums[0] / pairs, sums[1] / pairs, sums[2] / pairs, True, pairs, per_pair)


def _sample(order: list[int], keys: list[str], known: dict, budget: int) -> list[int]:
    """ตัดช่วงต้นของลำดับสุ่มจนคู่มือที่ต้องคิดใหม่ครบงบ ช่วงต้นของลำดับสุ่มคือตัวอย่างที่ไม่เอนเอียง"""
    taken, fresh = [], set()
    for index in order:
        key = keys[index]
        if key not in known and key not in fresh:
            if len(fresh) >= budget:
                break
            fresh.add(key)
        taken.append(index)
    return taken


def _by_matchup(matchups: np.ndarray, board: tuple[int, ...]) -> _Totals:
    """คิดทีละคู่มือแล้วจำผลไว้ ใช้กับ preflop และหลายทาง"""
    players = matchups.shape[1]
    per_matchup = (POSTFLOP_SECONDS_PER_MATCHUP if board
                   else PREFLOP_SECONDS_PER_PLAYER * players)
    keys = canonical_keys(matchups, board)
    with _LOCK:
        known = MEMO.load()
        missing = {key for key in keys if key not in known}
        exact = len(missing) * per_matchup <= EXACT_BUDGET_SECONDS
        chosen = list(range(len(keys)))
        if not exact:
            order = random.Random(SAMPLE_SEED).sample(chosen, len(chosen))
            chosen = _sample(order, keys, known, max(1, int(EXACT_BUDGET_SECONDS / per_matchup)))
        fresh: dict[str, Share] = {}
        for index in chosen:
            key = keys[index]
            if key not in known and key not in fresh:
                fresh[key] = exact_share([tuple(map(int, hole)) for hole in matchups[index]], board)
        MEMO.save(fresh)
        shares = [known[keys[index]] for index in chosen]
    equity = np.array([share.equity for share in shares])
    margin = 0.0
    if not exact and len(shares) > 1:
        margin = float(2 * equity[:, 0].std(ddof=1) / np.sqrt(len(shares)))
    return _Totals(equity.mean(axis=0), np.array([share.win for share in shares]).mean(axis=0),
                   np.array([share.tie for share in shares]).mean(axis=0),
                   exact, len(shares), shares[0].runouts, margin)


def calculate(players: Sequence[str], board: str = "") -> Result:
    """equity ของผู้เล่นสองถึงหกคน แต่ละคนเป็นมือเจาะจงหรือ range"""
    started = time.perf_counter()
    if not 2 <= len(players) <= MAX_PLAYERS:
        raise EquityError(f"ต้องมีผู้เล่น 2 ถึง {MAX_PLAYERS} คน")
    board_cards = parse_cards(board)
    if len(board_cards) not in (0, 3, 4, 5):
        raise EquityError("บอร์ดต้องมี 0, 3, 4 หรือ 5 ใบ")
    board_bits = ev.bits(board_cards)
    ranges = [[hole for hole in parse_hand_range(text) if not board_bits & ev.bits(hole)]
              for text in players]
    for text, combos in zip(players, ranges):
        if not combos:
            raise EquityError(f"ทุกมือใน '{text}' ชนกับไพ่บนบอร์ด")

    if len(ranges) == 2 and board_cards:
        totals = _heads_up_postflop(ranges[0], ranges[1], board_cards)
        matchups = totals.used
    else:
        found = (pair_matchups(ranges[0], ranges[1]) if len(ranges) == 2
                 else _multiway_matchups(ranges))
        if not len(found):
            raise EquityError("มือของผู้เล่นชนกันเองทุกชุด ไม่มีทางเกิดขึ้นพร้อมกัน")
        totals = _by_matchup(found, board_cards)
        matchups = len(found)

    result = tuple(
        Player(text.strip(), len(combos), float(totals.equity[i]), float(totals.win[i]),
               float(totals.tie[i]),
               ev.made_hand(combos[0], board_cards) if len(combos) == 1 else "")
        for i, (text, combos) in enumerate(zip(players, ranges)))
    return Result(result, ev.card_text(board_cards), totals.exact, matchups, totals.used,
                  totals.runouts, time.perf_counter() - started, totals.margin)


def warm() -> None:
    """โหลดตาราง บอร์ดทั้งหมด และผลที่จำไว้ล่วงหน้า"""
    ev.all_boards()
    MEMO.load()
