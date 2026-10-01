"""จัดกลุ่มมือเริ่มต้น PLO สี่ใบตามชนิดมือของ Jeff Hwang บทที่ 4 แล้วให้ระดับ

หนังสือแบ่งมือที่เล่นได้เป็นหกกลุ่ม: Big Cards กับ Ace-High Broadway Wrap, Straight Hands,
Suited Ace Hands, Pair-Plus Hands, Aces และ Marginal Hands แล้วจัดระดับสี่ขั้น
Premium Speculative Marginal Trash ระดับไม่ขึ้นกับตำแหน่ง แต่ขึ้นกับดอก จึงคิดแยกทุกแบบดอก

โค้ดจัดจากรูปร่างของอันดับไพ่ (ช่องว่างระหว่างไพ่ คู่ A) กับดอก ไม่ได้นับ equity
ชุดเฉลยคือแบบฝึกใน harnesses/EN/sources/web/plo-starting-hands-classify-*.md
"""

from __future__ import annotations

import dataclasses
import itertools
import re
import shutil
import textwrap

import plo_hand
import retrieval

RANKS = retrieval.RANK_ORDER
VALUE = plo_hand.VALUE
TEN, NINE, SEVEN, KING = VALUE["T"], VALUE["9"], VALUE["7"], VALUE["K"]
ACE = "A"
TIERS = ("Premium", "Speculative", "Marginal", "Trash")
PREMIUM, SPECULATIVE, MARGINAL, TRASH = TIERS
SHAPES = ("double-suited", "single-suited", "rainbow")
WIDTH = 9  # ความกว้างช่องหัวข้อ ให้ค่าทุกบรรทัดเริ่มตรงกัน
SOURCE = ("Hand tiers: Jeff Hwang, Pot-Limit Omaha Poker ch. 4 (PDF p. 77-89); "
          "play: authored Hwang-framework summary")
# ไพ่สองใบนี้ใน suited Ace ทำ straight เล็กที่แพ้ straight ใหญ่กว่า หนังสือให้เป็น trash
SUCKER_LOWS = ({2, 3}, {2, 4})

_SUIT_SYMBOL = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
_CARD = r"(?:10|[AKQJT2-9])[shdc♠♥♦♣]"
_CARDS = re.compile(rf"(?<![\w])((?:{_CARD}\s*){{4}})(?![\w])", re.IGNORECASE)
_CARD_RUN = re.compile(rf"(?<![A-Za-z0-9])((?:{_CARD}\s*)+)(?![A-Za-z0-9])", re.IGNORECASE)
_ONE_CARD = re.compile(r"(10|[AKQJT2-9])([shdc♠♥♦♣])", re.IGNORECASE)
_RANK_WORD = re.compile(r"(?<![\w])(?=[2-9]*[AKQJT])[AKQJT2-9]{4}(?![\w])", re.IGNORECASE)
_ANY_RANK_WORD = re.compile(r"(?<![A-Za-z0-9])[AKQJT2-9]+(?![A-Za-z0-9])", re.IGNORECASE)
# มือเลขล้วนอย่าง 9753 ต้องมีคำบอกดอกด้วย ไม่งั้นชนกับตัวเลขอื่นในคำถาม
_DIGIT_WORD = re.compile(r"(?<![\w.])[2-9]{4}(?![\w.])")
_PLO_WORD = re.compile(r"(?<![a-z])(plo|omaha)(?![a-z])|โอมาฮา|พีแอลโอ|เพียโล", re.IGNORECASE)
_SAYS_ACE_SUITED = re.compile(r"(?<![A-Za-z])A\s*(suited|ซูต|สูท)|suited ace", re.IGNORECASE)
_SS_PREFIX = re.compile(
    r"(?i)(?<![a-z])(?:ss|single\s*-?\s*suited|ซิงเกิล(?:ซูต|สูท))(?![a-z])")

GROUPS = {
    "big_cards": "Big Cards",
    "broadway_wrap": "Ace-High Broadway Wrap",
    "straight": "Straight Hands",
    "suited_ace": "Suited Ace Hands",
    "pair_plus": "Pair-Plus Hands",
    "aces": "Aces",
    "marginal": "Marginal Hands",
    "other": "Everything else",
}


@dataclasses.dataclass(frozen=True)
class Form:
    """แบบมือหนึ่งแบบในกลุ่ม ระดับคือระดับเมื่อมีดอกคู่ตามที่หนังสือพูดถึง"""

    group: str
    label: str
    cluster: str
    tier: str
    why_en: str
    why_th: str


FORMS = {
    "four_broadway": Form("big_cards", "four cards 10 and higher", "K-Q-J-T, A-Q-J-T, A-K-Q-T", PREMIUM,
                          "every card works toward Broadway straights and top two pair",
                          "ไพ่ทุกใบช่วยกันทำ Broadway straight และ top two pair"),
    "ace_broadway": Form("broadway_wrap", "four cards 9 and higher headed by an Ace",
                         "A-K-Q-9, A-K-J-9, A-K-T-9, A-Q-J-9, A-Q-T-9, A-J-T-9", PREMIUM,
                         "16- or 13-card nut wraps, plus the nut flush draw when the Ace is suited",
                         "ติด nut wrap 16 หรือ 13 ใบ ถ้า A มีดอกคู่ได้ nut flush draw ด้วย"),
    "rundown": Form("straight", "sequential rundown", "A-K-Q-J down to 6-5-4-3", PREMIUM,
                    "nut straight with redraws, 13-card wraps, top two pair with an open-ender",
                    "ติด nut straight พร้อม redraw, wrap 13 ใบ, top two pair พร้อม open-ender"),
    "bottom_gap": Form("straight", "rundown with a single bottom gap", "A-K-Q-T down to 6-5-4-2",
                       PREMIUM, "fairly strong and adds wrap potential",
                       "แข็งพอ ๆ กับ rundown และมีทาง wrap เพิ่ม"),
    "middle_gap": Form("straight", "rundown with a middle gap", "A-K-J-T down to 6-5-3-2", PREMIUM,
                       "a little weaker, with a remote 20-card wrap; close enough to premium",
                       "อ่อนลงนิดหน่อย มีทาง wrap 20 ใบ ใกล้พอจะนับเป็น Premium"),
    "two_single_gaps": Form("straight", "two single gaps", "A-K-J-9 down to 7-6-4-2", SPECULATIVE,
                            "16-card nut wrap potential, but it needs two specific flop cards",
                            "มีทาง nut wrap 16 ใบ แต่ต้องได้ไพ่สองใบที่เจาะจงบน flop"),
    "two_gap_bottom": Form("straight", "rundown with a two-gap", "A-K-Q-9 down to 7-6-5-2",
                           SPECULATIVE, "16-card nut wrap potential, needs specific cards",
                           "มีทาง nut wrap 16 ใบ ต้องได้ไพ่ที่เจาะจง"),
    "two_gap_middle": Form("straight", "two-gap between two connectors", "A-K-T-9 down to 7-6-3-2",
                           SPECULATIVE, "20-card wrap potential, but easily dominated by 13-card nut draws",
                           "มีทาง wrap 20 ใบ แต่โดน nut draw 13 ใบ dominate ง่าย"),
    "top_gap": Form("straight", "rundown with a top gap", "Q-T-9-8, J-9-8-7", MARGINAL,
                    "the gap on top makes its straights the low end, dominated by the card above",
                    "ช่องว่างข้างบนทำให้ straight ที่ติดเป็นปลายล่าง แพ้มือที่มีไพ่ใบบน"),
    "top_bottom_gap": Form("straight", "top and bottom gap", "K-J-T-8, J-9-8-6", MARGINAL,
                           "marginal at best", "ดีสุดก็แค่ Marginal"),
    "top_two_gaps": Form("straight", "two single gaps on top", "J-9-7-6, 9-7-5-3", TRASH,
                         "every straight it flops is dominated", "straight ที่ติดโดน dominate ทั้งหมด"),
    "top_double_gap": Form("straight", "two-gap on top", "J-8-7-6 (K-T-9-8 limps late)", TRASH,
                           "ditch it unless it is Ace-high", "ทิ้ง ยกเว้นมี A นำ"),
    "small_rundown": Form("straight", "rundown below 6-5-4-3", "5-4-3-2", TRASH,
                          "too small to flop the big nut wraps", "เล็กเกินจะติด nut wrap ใหญ่"),
    "ace_rundown": Form("suited_ace", "suited Ace with a three-card rundown",
                        "A-J-T-9 down to A-6-5-4", PREMIUM,
                        "top two pair, 13-card nut wraps and the nut flush draw together",
                        "ติด top two pair, nut wrap 13 ใบ และ nut flush draw ได้พร้อมกัน"),
    "ace_gapped": Form("suited_ace", "suited Ace with a gapped three-card rundown",
                       "A-Q-J-9 down to A-6-5-3, A-Q-T-9 down to A-6-4-3", SPECULATIVE,
                       "13-card draws with the nut flush draw, but half of them are non-nut",
                       "ได้ draw 13 ใบพร้อม nut flush draw แต่ครึ่งหนึ่งไม่ใช่ nut"),
    "ace_wrap17": Form("suited_ace", "suited Ace, A-8-7-4 form", "A-J-T-7 down to A-6-5-2",
                       SPECULATIVE, "17-card wrap potential with the nut flush draw",
                       "มีทาง wrap 17 ใบพร้อม nut flush draw"),
    "ace_two_gaps": Form("suited_ace", "suited Ace, A-8-6-4 form", "A-Q-T-8 down to A-6-4-2",
                         MARGINAL, "17-card wrap potential but too many gaps, easily dominated",
                         "มีทาง wrap 17 ใบแต่ช่องว่างเยอะ โดน dominate ง่าย"),
    "ace_sucker": Form("suited_ace", "suited Ace, A-8-5-4 form (double gap on top)", "A-8-5-4",
                       MARGINAL, "its 17-card wraps are sucker wraps", "wrap 17 ใบของมันเป็น sucker wrap"),
    "ace_broadway_dangler": Form("suited_ace", "suited Ace with two Broadway cards and a dangler",
                                 "A-K-Q-5, A-K-J-7", SPECULATIVE,
                                 "13-card Broadway wraps with the nut flush draw; see the flop cheaply",
                                 "ติด Broadway wrap 13 ใบพร้อม nut flush draw ควรดู flop ถูก ๆ"),
    "ace_weak": Form("suited_ace", "weak suited Ace", "A-K-7-2, A-9-6-3", MARGINAL,
                     "mostly a one-way nut flush hand", "เป็นมือทางเดียว หวัง nut flush อย่างเดียว"),
    "ace_sucker_low": Form("suited_ace", "suited Ace with 2-3 or 2-4", "A-9-3-2, A-K-4-2", TRASH,
                           "makes too many sucker straights", "ทำ sucker straight บ่อยเกินไป"),
    "pair_ace_broadway": Form("pair_plus", "big pair with a suited Ace and a Broadway card",
                              "A-J-T-T, A-K-Q-Q", PREMIUM,
                              "top set with the nut flush draw, plus Broadway wraps",
                              "ติด top set พร้อม nut flush draw และ Broadway wrap"),
    "pair_ace": Form("pair_plus", "pair with a suited Ace", "A-9-9-2, A-K-7-7", SPECULATIVE,
                     "top set with the nut flush draw beats the biggest draws; a big-pot hand",
                     "top set พร้อม nut flush draw ชนะ draw ใหญ่สุด เป็นมือทำเงินก้อนใหญ่"),
    "pair_connectors": Form("pair_plus", "pair with connecting cards",
                            "K-K-Q-J, Q-Q-9-8, 9-9-8-7, 7-6-5-5", SPECULATIVE,
                            "a set comes with a straight card; can flop the nut straight with a set",
                            "ติด set แล้วมีไพ่ straight ไปด้วย ติด nut straight พร้อม set ได้"),
    "double_big": Form("pair_plus", "big double pair", "Q-Q-J-J, K-K-T-T", PREMIUM,
                       "flops a set 21% of the time, and top set at that",
                       "ติด set 21% ของ flop และเป็น set ใหญ่"),
    "double_top": Form("pair_plus", "big pair plus small pair", "K-K-3-3", SPECULATIVE,
                       "playable because of the big pair", "เล่นได้เพราะคู่ใหญ่"),
    "double_medium": Form("pair_plus", "medium double pair", "8-8-7-7, Q-Q-9-9", SPECULATIVE,
                          "hits often but makes one-dimensional sets", "ติดบ่อยแต่ได้ set ทางเดียว"),
    "double_small": Form("pair_plus", "small double pair", "4-4-3-3", TRASH,
                         "only makes inferior sets", "ได้แต่ set เล็กที่แพ้ set ใหญ่"),
    "aces_magnum": Form("aces", "Magnum Aces", "A-A-K-K, A-A-J-T, A-A-8-7 double-suited", PREMIUM,
                        "double-suited Aces with Broadway, connectors or a second big pair",
                        "A สองดอก มี Broadway, connector หรือคู่ใหญ่อีกคู่"),
    "aces_premium": Form("aces", "premium Aces", "A-A-x-x double-suited, A-A-J-T or A-A-8-7 suited",
                         PREMIUM, "double-suited, or suited with wraps, connectors or a second pair",
                         "A สองดอก หรือมีดอกพร้อม wrap, connector หรือคู่ที่สอง"),
    "aces_speculative": Form("aces", "speculative Aces", "A-A-8-3, A-A-8-2 rainbow", SPECULATIVE,
                             "one-way Aces: at least a ticket to see the flop",
                             "A คู่ทางเดียว อย่างน้อยก็ได้ดู flop"),
    "three_broadway_dangler": Form("marginal", "three Broadway cards and a dangler", "K-Q-J-4",
                                   MARGINAL, "a three-card hand; late position for the minimum",
                                   "เป็นมือสามใบ เล่นแค่ตำแหน่งหลังลงขั้นต่ำ"),
    "big_pair_danglers": Form("pair_plus", "big pair with danglers", "K-K-7-2, J-J-6-3", MARGINAL,
                              "a one-way hand that needs a set", "เป็นมือทางเดียว ต้องติด set"),
    "small_pair_danglers": Form("pair_plus", "small pair with danglers", "K-9-6-6, 8-8-K-3", TRASH,
                                "can't make top set cleanly, and non-nut flushes cost money",
                                "ติด top set ยาก flush ที่ไม่ใช่ nut มีแต่เสียเงิน"),
    "trips": Form("other", "three or four of a kind", "A-A-A-5, 7-7-7-6", TRASH,
                  "the extra card kills your own set", "ไพ่ใบที่สามทำให้ติด set ยาก"),
    "no_structure": Form("other", "no shared structure", "Q-J-7-6, K-8-4-2", TRASH,
                         "two Hold'em hands that never work together", "เป็น Hold'em สองมือที่ไม่ทำงานร่วมกัน"),
}

# ช่องว่างระหว่างไพ่สี่ใบที่ไม่มีคู่ เรียงจากบนลงล่าง กับไพ่บนสุดที่เล็กที่สุดที่ยังเล่นได้
STRAIGHT_FORMS = {
    (0, 0, 0): ("rundown", 6), (0, 0, 1): ("bottom_gap", 6), (0, 1, 0): ("middle_gap", 6),
    (0, 1, 1): ("two_single_gaps", 7), (0, 0, 2): ("two_gap_bottom", 7),
    (0, 2, 0): ("two_gap_middle", 7), (1, 0, 0): ("top_gap", 0), (1, 0, 1): ("top_bottom_gap", 0),
    (1, 1, 0): ("top_two_gaps", 0), (1, 1, 1): ("top_two_gaps", 0), (2, 0, 0): ("top_double_gap", 0),
}
# ช่องว่างของไพ่สามใบข้าง A ใน suited Ace กับไพ่ล่างสุดที่เล็กที่สุด
ACE_FORMS = {(0, 0): ("ace_rundown", 4), (0, 1): ("ace_gapped", 3), (1, 0): ("ace_gapped", 3),
             (0, 2): ("ace_wrap17", 2), (1, 1): ("ace_two_gaps", 2), (2, 0): ("ace_sucker", 2)}
KT98 = "KT98"  # หนังสือยกเว้นให้ limp ตำแหน่งหลังได้
# miracle flop ที่โชว์กับคำที่แสดง quads และ full house นับเฉพาะที่ใช้คู่ในมือ (6-6 + A-6-6)
# full house จากไพ่เดี่ยวกับ flop ตอง อย่าง A-K + A-A-A ไม่ได้บอกอะไรเกี่ยวกับมือ ใช้เมื่อไม่มีแบบอื่นเท่านั้น
MIRACLE_KINDS = {"straight": "nut straight", "set": "top set", "quads": "quads",
                 "full_house": "nut full house"}
MIRACLE_FALLBACK = {"board_trips": "nut full house or better"}
# ชนิดที่ใช้คู่ในมือ โชว์คู่ละหนึ่ง flop พอ
MIRACLE_ONE_PER_PAIR = ("set", "quads", "full_house")
MIRACLE_PER_KIND = 3
MIRACLE_MAX = 6


@dataclasses.dataclass(frozen=True)
class Suiting:
    suited: bool           # มีไพ่ดอกเดียวกันอย่างน้อยสองใบ
    double: bool           # double-suited
    ace_suited: bool | None  # A อยู่ในดอกที่ซ้ำ; None = ss แต่ไม่บอกว่าไพ่คู่ไหน
    aces_suited: int       # จำนวน A ที่อยู่ในดอกที่ซ้ำ
    suited_ranks: tuple[str, ...] = ()
    suit_groups: tuple[tuple[str, ...], ...] = ()


@dataclasses.dataclass(frozen=True)
class Hand:
    ranks: str                 # เรียงใหญ่ไปเล็ก เช่น KKQJ
    suiting: Suiting | None    # None คือไม่ได้บอกดอก
    cards: str = ""            # ไพ่พร้อมดอกตามที่พิมพ์มา ถ้ามี
    suits_assumed: bool = False  # ไม่ได้บอกดอก จึงถือว่า rainbow


@dataclasses.dataclass(frozen=True)
class Asked:
    hand: Hand | None          # None คือถามภาพรวมกลุ่มมือ
    error: str | None = None


@dataclasses.dataclass(frozen=True)
class Cluster:
    group: str
    form: str
    tier: str
    magnum: bool = False


class PloParseError(ValueError):
    """A hand description cannot name one legal four-card PLO hand."""


def from_shape(ranks: str, shape: str | None, ace_suited: bool | None = True,
               suited_ranks: tuple[str, ...] = ()) -> Hand:
    """Build a rank hand; ``ace_suited=None`` preserves an ambiguous plain ss description."""
    aces = ranks.count(ACE)
    suiting = {
        "double-suited": Suiting(True, True, aces > 0, min(aces, 2)),
        "single-suited": Suiting(True, False, ace_suited if aces else False,
                                  min(aces, 1) if ace_suited else 0, suited_ranks,
                                  (suited_ranks,) if suited_ranks else ()),
        "rainbow": Suiting(False, False, False, 0),
    }.get(shape or "")
    return Hand(ranks, suiting)


def sorted_ranks(ranks: str) -> str:
    return "".join(sorted(ranks.upper(), key=RANKS.index))


def _from_cards(text: str) -> Hand:
    raw = [(rank.upper().replace("10", "T"), suit.lower()) for rank, suit in _ONE_CARD.findall(text)]
    normalized = [(rank, next(key for key, symbol in _SUIT_SYMBOL.items()
                              if suit in (key, symbol))) for rank, suit in raw]
    if len(set(normalized)) != len(normalized):
        raise PloParseError("the same physical card cannot appear twice")
    pairs = sorted(normalized, key=lambda card: RANKS.index(card[0]))
    suits = [suit for _, suit in pairs]
    counts = {suit: suits.count(suit) for suit in suits}
    aces = [suit for (rank, _), suit in zip(pairs, suits) if rank == ACE and counts[suit] >= 2]
    groups = tuple(tuple(rank for rank, there in pairs if there == suit)
                   for suit, count in counts.items() if count >= 2)
    repeated = next((group for group in groups if ACE in group), groups[0] if groups else ())
    suiting = Suiting(any(count >= 2 for count in counts.values()),
                      sum(count == 2 for count in counts.values()) == 2,
                      bool(aces), len(aces), repeated, groups)
    ranks = "".join(rank for rank, _ in pairs)
    return Hand(ranks, suiting, "".join(f"{rank}{_SUIT_SYMBOL[suit]}" for (rank, _), suit in zip(pairs, suits)))


def _shape(text: str) -> str | None:
    lowered = text.lower()
    mentioned = set()
    # Consume the complete English phrase first.  Otherwise ``double-suited``
    # leaves ``suited`` behind and looks like two contradictory shapes.
    full_double = re.compile(r"(?<![a-z])double\s*-?\s*suited(?![a-z])")
    if full_double.search(lowered):
        mentioned.add("double-suited")
        lowered = full_double.sub(" ", lowered)
    double_words = plo_hand.SHAPES[0][1]
    for word in double_words:
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered):
            mentioned.add("double-suited")
            lowered = re.sub(rf"(?<![a-z]){re.escape(word)}(?![a-z])", " ", lowered)
    for name, words in plo_hand.SHAPES[1:]:
        checked = tuple(word for word in words
                        if not ("double-suited" in mentioned and word in ("ซูต", "สูท", "suited")))
        if any(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered) for word in checked):
            mentioned.add(name)
    named = plo_hand._named_suits(text)
    if named:
        mentioned.add(named)
    if len(mentioned) > 1:
        raise PloParseError("suit descriptions contradict each other")
    return next(iter(mentioned), None)


def _suited_group(text: str, ranks: str) -> tuple[str, ...] | None:
    """Ranks explicitly named after ``ss`` as sharing one physical suit.

    The suffix may contain two, three, or four ranks. It is parsed in full so ``ss AK7``
    cannot silently become ``ss AK``.
    """
    prefix = _SS_PREFIX.search(text)
    if prefix is None:
        return None
    made = re.match(r"\s*([AKQJT2-9](?:\s*[-/]?\s*[AKQJT2-9])*)", text[prefix.end():], re.IGNORECASE)
    if made is None:
        return None
    end = prefix.end() + made.end()
    if end < len(text) and text[end].isascii() and text[end].isalnum():
        raise PloParseError("invalid rank in single-suited suffix")
    group = tuple(re.findall(r"[AKQJT2-9]", made.group(1).upper()))
    if len(group) < 2:
        return None
    if len(group) > 4:
        raise PloParseError("single-suited suffix can name at most four cards")
    if len(set(group)) != len(group):
        raise PloParseError("two copies of one rank cannot be the same physical suit")
    available = list(ranks)
    for rank in group:
        if rank not in available:
            raise PloParseError(f"suited card {rank} is not in {ranks}")
        available.remove(rank)
    return group


def read(text: str) -> Hand | None:
    """มือ PLO ในข้อความ บอกดอกทีละใบ (As Ks Qd Jd) หรือบอกรูปดอก (AAKK ds) ก็ได้"""
    exact_cards = [card for run in _CARD_RUN.findall(text) for card in _ONE_CARD.findall(run)]
    if exact_cards and len(exact_cards) != 4:
        raise PloParseError("name exactly four physical cards")
    cards = _CARDS.search(text)
    if cards:
        return _from_cards(cards.group(1))
    # retrieval ไม่รับคำที่เป็นเลขล้วนอย่าง 9753 เพราะชนกับตัวเลขในคำถามทั่วไป ที่นี่มีคำบอกดอกกำกับแล้ว
    digits = _DIGIT_WORD.search(text)
    found = retrieval.hands(text) or ((sorted_ranks(digits.group(0)),) if digits else ())
    if not found:
        if _PLO_WORD.search(text) and _ANY_RANK_WORD.search(retrieval.latin_ranks(text)):
            raise PloParseError("name exactly four card ranks, for example A234")
        return None
    if len(found) != 1:
        raise PloParseError("name one four-card hand at a time")
    shape = _shape(text)
    ranks = found[0]
    group = _suited_group(text, ranks) if shape == "single-suited" else None
    if shape == "single-suited":
        said = plo_hand.suited_ace(text) or bool(_SAYS_ACE_SUITED.search(text))
        ace_suited = ((ACE in group) if group else True if said else None) if ACE in ranks else False
        return from_shape(ranks, shape, ace_suited=ace_suited, suited_ranks=group or ())
    if shape is None:  # ไม่ได้บอกดอก ถือว่า rainbow
        return dataclasses.replace(from_shape(ranks, "rainbow"), suits_assumed=True)
    return from_shape(ranks, shape)


def lookup(text: str) -> Asked | None:
    """คำถามนี้ถามมือ PLO ไหม ต้องมีคำว่า plo/omaha หรือเขียนไพ่สี่ใบติดกันเป็นคำเดียว

    ชาร์ต push/fold ไม่มีมือสี่ใบ คำอย่าง AAKK หรือ JT98 จึงไม่ชนกับคำถาม push/fold
    """
    digits_with_suits = _DIGIT_WORD.search(text) and plo_hand.shape(text)
    if _CARDS.search(text) or _RANK_WORD.search(text) or digits_with_suits:
        try:
            return Asked(read(text))
        except PloParseError as error:
            return Asked(None, str(error))
    if _PLO_WORD.search(text):
        try:
            return Asked(read(text))
        except PloParseError as error:
            return Asked(None, str(error))
    return None


def _gaps(values: list[int]) -> tuple[int, ...]:
    return tuple(high - low - 1 for high, low in zip(values, values[1:]))


def _step_down(tier: str, steps: int = 1) -> str:
    return TIERS[min(TIERS.index(tier) + steps, len(TIERS) - 1)]


def _rainbow(tier: str) -> str:
    """มือ straight ไม่มีดอก หนังสือว่า unsuited rundown เป็น Marginal ที่ต่ำกว่านั้นทิ้ง"""
    return MARGINAL if tier == PREMIUM else TRASH


def _by_suits(form: str, suiting: Suiting, needs_ace: bool = False) -> Cluster:
    tier = FORMS[form].tier
    if not suiting.suited:
        tier = _rainbow(tier)
    elif needs_ace and not suiting.ace_suited:
        tier = _step_down(tier)
    return Cluster(FORMS[form].group, form, tier)


def _aces(sides: list[int], suiting: Suiting) -> Cluster:
    broadway = min(sides) >= TEN
    connectors = sides[0] - sides[1] == 1
    second_pair = sides[0] == sides[1]
    multiway = broadway or connectors or (second_pair and sides[0] >= TEN)
    if suiting.aces_suited >= 2 and multiway:
        return Cluster("aces", "aces_magnum", PREMIUM, magnum=True)
    if suiting.aces_suited >= 2 or (suiting.aces_suited == 1 and (multiway or second_pair)):
        return Cluster("aces", "aces_premium", PREMIUM)
    return Cluster("aces", "aces_speculative", SPECULATIVE)


def _double_pair(high: int, low: int) -> str:
    if low >= TEN:
        return "double_big"
    if high >= KING:
        return "double_top"
    return "double_medium" if low >= SEVEN else "double_small"


def _one_pair(ranks: str, pair: int, suiting: Suiting) -> Cluster:
    sides = [VALUE[rank] for rank in ranks if VALUE[rank] != pair]
    if ACE in ranks and suiting.ace_suited:
        form = "pair_ace_broadway" if pair >= TEN and min(sides) >= TEN else "pair_ace"
        return Cluster("pair_plus", form, FORMS[form].tier)
    if plo_hand._linked(ranks) >= 3:
        tier = PREMIUM if pair >= TEN else SPECULATIVE
        return Cluster("pair_plus", "pair_connectors", tier if suiting.suited else _step_down(tier))
    form = "big_pair_danglers" if pair >= TEN else "small_pair_danglers"
    return Cluster(FORMS[form].group, form, FORMS[form].tier)


def _suited_ace(ranks: str, sides: list[int], suiting: Suiting) -> Cluster:
    form, lowest = ACE_FORMS.get(_gaps(sides), (None, 0))
    if form is None or sides[-1] < lowest:
        broadway = sum(value >= TEN for value in sides) >= 2
        values = {VALUE[rank] for rank in ranks}
        low = any(pair <= values for pair in SUCKER_LOWS)
        form = "ace_broadway_dangler" if broadway else ("ace_sucker_low" if low else "ace_weak")
    return _by_suits(form, suiting, needs_ace=True)


def _unpaired(ranks: str, suiting: Suiting) -> Cluster:
    values = [VALUE[rank] for rank in ranks]
    if min(values) >= TEN:
        return _by_suits("four_broadway", suiting)
    if ranks[0] == ACE and min(values) >= NINE:
        return _by_suits("ace_broadway", suiting, needs_ace=True)
    # A นำที่ยังไม่ใช่ Broadway ต้องดูแบบ suited Ace ก่อน ไม่งั้น A-Q-T-8 จะเข้ารูป straight ที่ช่องว่างบน
    if ranks[0] == ACE:
        return _suited_ace(ranks, values[1:], suiting)
    form, lowest = STRAIGHT_FORMS.get(_gaps(values), (None, 0))
    if form == "top_double_gap" and ranks == KT98:
        return Cluster("straight", form, MARGINAL if suiting.suited else TRASH)
    if form is not None:
        return _by_suits(form if values[0] >= lowest else "small_rundown", suiting)
    if sum(value >= TEN for value in values) == 3:
        return Cluster("marginal", "three_broadway_dangler", MARGINAL if suiting.suited else TRASH)
    return Cluster("other", "no_structure", TRASH)


def classify(hand: Hand) -> Cluster:
    """Classify one concrete suit description using Hwang's hand types."""
    if hand.suiting and hand.suiting.ace_suited is None and ACE in hand.ranks:
        raise PloParseError("identify which two cards share the suit before choosing one tier")
    suiting = hand.suiting or from_shape(hand.ranks, "single-suited").suiting
    ranks = hand.ranks
    counts = sorted((ranks.count(rank) for rank in set(ranks)), reverse=True)
    if counts[0] >= 3:
        return Cluster("other", "trips", TRASH)
    if ranks.count(ACE) == 2:
        return _aces([VALUE[rank] for rank in ranks if rank != ACE], suiting)
    pairs = sorted({VALUE[rank] for rank in ranks if ranks.count(rank) == 2}, reverse=True)
    if len(pairs) == 2:
        form = _double_pair(*pairs)
        return Cluster("pair_plus", form, FORMS[form].tier)
    if pairs:
        return _one_pair(ranks, pairs[0], suiting)
    return _unpaired(ranks, suiting)


LABELS = {
    "EN": {"type": "Type", "tier": "Tier", "play": "How to play", "why": "Why",
           "miracle": "Miracle flops",
           "assumptions": "Assumptions",
           "source": "Source", "magnum": "Magnum",
           "assumed": "rainbow (no suits given, assumed)",
           "example": "suits shown are an example",
           "overview": "PLO starting-hand types (Jeff Hwang ch. 4), tier when suited",
           "ask": "Ask about a hand, e.g. plo A234 ss A2 or plo As 2s 3d 4c"},
    "TH": {"type": "กลุ่ม", "tier": "ระดับ", "play": "วิธีเล่น", "why": "เหตุผล",
           "miracle": "miracle flop",
           "assumptions": "สมมติฐาน",
           "source": "ที่มา", "magnum": "Magnum",
           "assumed": "rainbow (ไม่ได้บอกดอก ถือว่า rainbow)",
           "example": "ดอกที่แสดงเป็นตัวอย่าง",
           "overview": "ชนิดมือเริ่มต้น PLO ตาม Jeff Hwang บทที่ 4 ระดับเมื่อมีดอกคู่",
           "ask": "ถามมือได้ เช่น plo A234 ss A2 หรือ plo As 2s 3d 4c"},
}


def _shape_of(suiting: Suiting | None) -> str | None:
    if suiting is None:
        return None
    return SHAPES[0] if suiting.double else (SHAPES[1] if suiting.suited else SHAPES[2])


def _tier_text(cluster: Cluster, words: dict) -> str:
    return f"{cluster.tier} ({words['magnum']})" if cluster.magnum else cluster.tier


def _how_to_play(tier: str, lang: str) -> str:
    """General deep-stack guidance; a tier never replaces the actual preflop context."""
    if lang == "TH":
        return {
            PREMIUM: "มองหา value raise เมื่อตำแหน่งและ action ก่อนหน้ารองรับ; ระดับอย่างเดียวไม่ตัดสิน raise หรือ 3-bet",
            SPECULATIVE: "พยายามดู flop ราคาถูก โดยเฉพาะเมื่อมีตำแหน่ง; มือใหญ่บางแบบค่อย raise ตำแหน่งหลัง และอย่าปั้น pot ใหญ่ด้วย AA อ่อน",
            MARGINAL: "ส่วนใหญ่ fold; เล่นเฉพาะราคาถูกจากตำแหน่งหลังเมื่อสถานการณ์ดี",
            TRASH: "ส่วนใหญ่ fold; อย่าจ่ายเพื่อไล่ draw ที่ถูก dominate, straight ต่ำ หรือ set เล็ก",
        }[tier]
    return {
        PREMIUM: "Look for a value raise when position and prior action permit; the tier alone does not decide a raise or 3-bet.",
        SPECULATIVE: "See a flop cheaply, preferably in position; stronger examples can raise late. Avoid bloating pots with weak AA.",
        MARGINAL: "Usually fold; continue only cheaply from late position when the pot and action are favorable.",
        TRASH: "Usually fold; avoid paying to chase dominated draws, low straights or small sets.",
    }[tier]


# แผนหลัง flop ตามกลุ่มมือ ใช้ต่อจากคำแนะนำ preflop ของระดับ
POSTFLOP = {
    "big_cards": ("After the flop: play for Broadway straights and top two pair with a draw; "
                  "slow down on low, connected boards that miss you.",
                  "หลัง flop: เล่นหา Broadway straight และ top two pair ที่มี draw; "
                  "บอร์ดต่ำต่อกันที่ไม่โดนให้ชะลอ"),
    "broadway_wrap": ("After the flop: drive the nut wraps and nut draws on high boards; "
                      "low boards your cards cannot reach are folds.",
                      "หลัง flop: เดินหน้ากับ nut wrap และ nut draw บนบอร์ดสูง; "
                      "บอร์ดต่ำที่ไพ่เราไปไม่ถึงให้ fold"),
    "straight": ("After the flop: continue with the nut straight, 13+ out wraps, or two pair plus a draw; "
                 "fold non-nut straights and the low end of a wrap.",
                 "หลัง flop: ไปต่อเมื่อได้ nut straight, wrap 13 outs ขึ้นไป หรือ two pair พร้อม draw; "
                 "straight ที่ไม่ใช่ nuts และปลายล่างของ wrap ให้ fold"),
    "suited_ace": ("After the flop: play hard with the nut flush or the nut flush draw plus a wrap; "
                   "give up when the flop misses both your suit and your straight cards.",
                   "หลัง flop: เล่นแรงเมื่อได้ nut flush หรือ nut flush draw พร้อม wrap; "
                   "flop ที่ไม่โดนทั้งดอกและไพ่ straight ให้ทิ้ง"),
    "ace_offsuit": ("After the flop: there is no nut flush draw, so continue only with the nut straight "
                    "or a nut wrap.",
                    "หลัง flop: ไม่มี nut flush draw ไปต่อเฉพาะเมื่อได้ nut straight หรือ nut wrap"),
    "pair_plus": ("After the flop: mostly set mining; continue with a set (ideally top set) or a set plus "
                  "a straight draw, otherwise fold to action.",
                  "หลัง flop: ส่วนใหญ่คือหวัง set; ไปต่อเมื่อติด set (ดีที่สุดคือ top set) หรือ set "
                  "พร้อม straight draw ไม่งั้นโดน bet ให้ fold"),
    "aces": ("After the flop: unimproved Aces win small pots; build the pot preflop, then commit only "
             "with a set, a nut draw or a safe board, especially multiway.",
             "หลัง flop: AA ที่ไม่ติดอะไรชนะ pot เล็ก; ปั้น pot ตั้งแต่ preflop แล้วค่อยทุ่มเมื่อได้ set "
             "nut draw หรือบอร์ดปลอดภัย โดยเฉพาะตอนหลายคน"),
    "marginal": ("After the flop: continue only with the nuts or a nut draw; one pair and dominated draws "
                 "are folds.",
                 "หลัง flop: ไปต่อเฉพาะ nuts หรือ nut draw; one pair และ draw ที่ถูก dominate ให้ fold"),
    "other": ("After the flop: if you do play it, only the nuts continues; everything else is a fold.",
              "หลัง flop: ถ้าเล่นไปแล้ว ไปต่อเฉพาะ nuts นอกนั้น fold"),
}


def _postflop(cluster: Cluster, hand: Hand, lang: str) -> str:
    key = cluster.group
    if cluster.tier == TRASH:
        key = "other"
    elif key == "suited_ace" and not (hand.suiting and hand.suiting.ace_suited):
        key = "ace_offsuit"
    english, thai = POSTFLOP.get(key, POSTFLOP["other"])
    return thai if lang == "TH" else english


def _play(cluster: Cluster, hand: Hand, lang: str) -> str:
    return f"{_how_to_play(cluster.tier, lang)}\n{_postflop(cluster, hand, lang)}"


def _conditional_play(yes: Cluster, no: Cluster, lang: str) -> str:
    if yes.tier == no.tier:
        return _how_to_play(yes.tier, lang)
    if lang == "TH":
        short = {PREMIUM: "มองหา value raise ตามสถานการณ์", SPECULATIVE: "ดู flop ราคาถูกเมื่อมีตำแหน่ง",
                 MARGINAL: "ส่วนใหญ่ fold เล่นถูกๆ เฉพาะตำแหน่งหลัง", TRASH: "fold"}
        return (f"ถ้า A มีดอกคู่: {yes.tier} — {short[yes.tier]}; ถ้าไม่ใช่: {no.tier} — "
                f"{short[no.tier]} บอกไพ่ดอกคู่แบบ ss A2 ก่อนตัดสินใจ")
    short = {PREMIUM: "look for a context-supported value raise",
             SPECULATIVE: "prefer a cheap flop in position",
             MARGINAL: "usually fold; continue cheaply only late",
             TRASH: "fold"}
    return (f"Ace suited: {yes.tier} — {short[yes.tier]}; otherwise: {no.tier} — "
            f"{short[no.tier]}. Specify the pair like ss A2 before acting.")


def _concrete(hand: Hand, ace_suited: bool) -> Hand:
    return dataclasses.replace(
        hand, suiting=dataclasses.replace(hand.suiting, ace_suited=ace_suited,
                                          aces_suited=min(hand.ranks.count(ACE), 1) if ace_suited else 0))


def _display(cluster: Cluster, hand: Hand, lang: str) -> tuple[str, str]:
    form = FORMS[cluster.form]
    if (hand.suiting and hand.suiting.ace_suited is False
            and ACE in hand.ranks and cluster.group in ("suited_ace", "broadway_wrap")):
        kind = ("Ace-high connected hand" if lang == "EN" else "มือ A-high ที่เชื่อมกัน")
        if not hand.suiting.suited:
            why = ("Rainbow: the straight and wrap structure remains, but there is no flush draw"
                   if lang == "EN" else "rainbow โครงสร้าง straight และ wrap ยังอยู่ แต่ไม่มี flush draw")
            return kind, why
        why = ("The Ace is outside the suited pair: the straight and wrap structure remains, "
               "but its flush draw is not the nut flush draw" if lang == "EN" else
               "A อยู่นอกไพ่ดอกคู่ โครงสร้าง straight และ wrap ยังอยู่ แต่ flush draw ไม่ใช่ nut flush draw")
        return kind, why
    why = form.why_th if lang == "TH" else form.why_en
    return f"{GROUPS[form.group]} / {form.label}", why


def _known_suit_pair(hand: Hand) -> str:
    pair = hand.suiting.suited_ranks if hand.suiting else ()
    return "".join(pair[:2])


def _ace_suit_group(hand: Hand) -> tuple[tuple[str, ...], str | None]:
    """Return the real/declared repeated-suit group containing an Ace."""
    if not hand.suiting or not hand.suiting.ace_suited:
        return (), None
    if hand.cards:
        cards = [(rank.upper().replace("10", "T"), suit)
                 for rank, suit in _ONE_CARD.findall(hand.cards)]
        for suit in dict.fromkeys(suit for _, suit in cards):
            ranks = tuple(rank for rank, there in cards if there == suit)
            if ACE in ranks and len(ranks) >= 2:
                return ranks, suit
        return (), None
    group = next((group for group in hand.suiting.suit_groups if ACE in group), ())
    if not group:
        group = hand.suiting.suited_ranks
    if not group and hand.suiting.double:
        partners = tuple(dict.fromkeys(rank for rank in hand.ranks if rank != ACE))
        if len(partners) == 1:
            group = (ACE, partners[0])
    return tuple(group), None


def _flush_board(group: tuple[str, ...]) -> tuple[str, str, str] | None:
    """Choose a legal monotone board that does not turn the example into a straight flush."""
    available = [rank for rank in RANKS if rank not in group]
    preferred = ("K", "9", "5", "Q", "8", "4", "J", "7", "3", "T", "6", "2")
    ordered = [rank for rank in preferred if rank in available]
    ordered.extend(rank for rank in available if rank not in ordered)
    for board in itertools.combinations(ordered, 3):
        board_values = frozenset(VALUE[rank] for rank in board)
        opponent_can_make_straight_flush = any(
            board_values <= window for window in plo_hand.STRAIGHT_WINDOWS)
        if (not opponent_can_make_straight_flush
                and all(plo_hand._score(tuple(VALUE[rank] for rank in holes + board))[0]
                        != plo_hand.STRAIGHT for holes in itertools.combinations(group, 2))):
            return board
    return None


def _flush_line(hand: Hand) -> str | None:
    group, suit = _ace_suit_group(hand)
    board = _flush_board(group) if ACE in group and len(group) >= 2 else None
    if not board:
        return None
    mate = next(rank for rank in group if rank != ACE)
    board = tuple(sorted(board, key=RANKS.index))
    if suit:
        cards_text = f"A{suit} {mate}{suit} + " + " ".join(f"{rank}{suit}" for rank in board)
    else:
        cards_text = f"A-{mate} + {'-'.join(board)}, all in the A{mate} suit"
    return f"{cards_text} → nut flush"


def _miracle_kind(kind: str, board: str, pair: str) -> str:
    """แยก full house ขึ้นไปจาก plo_hand เป็น quads / full house ด้วยคู่ในมือ หรือ flop ตอง"""
    if kind != "full house ขึ้นไป":
        return kind
    high, low = pair.split("-")
    if high != low:
        return "board_trips"
    return "quads" if board.split("-").count(high) == 2 else "full_house"


def _nut_flops(ranks: str) -> list[str]:
    """flop ที่ติด nuts ทันทีจากอันดับไพ่ ไพ่คู่ที่ยังไม่โชว์ขึ้นก่อน แต่ละชนิดไม่เกิน MIRACLE_PER_KIND"""
    found = [(_miracle_kind(*board), board[1], board[2]) for board in plo_hand.study(ranks).nut_boards]
    names = MIRACLE_KINDS if any(kind in MIRACLE_KINDS for kind, _, _ in found) else MIRACLE_FALLBACK
    boards = [board for board in found if board[0] in names]
    picked: list[tuple[str, str, str]] = []
    for fresh_only in (True, False):
        for board in boards:
            kind, _, pair = board
            same_kind = [shown for shown in picked if shown[0] == kind]
            repeated = any(shown[2] == pair for shown in same_kind)
            if (len(picked) >= MIRACLE_MAX or board in picked or len(same_kind) >= MIRACLE_PER_KIND
                    or (repeated and (fresh_only or kind in MIRACLE_ONE_PER_PAIR))):
                continue
            picked.append(board)
    order = list(names)
    picked.sort(key=lambda board: (order.index(board[0]), boards.index(board)))
    return [(names[kind], board, pair) for kind, board, pair in picked]


def _held_cards(hand: Hand) -> list[tuple[str, str]]:
    return [(rank.upper().replace("10", "T"), next(symbol for key, symbol in _SUIT_SYMBOL.items()
                                                   if suit.lower() in (key, symbol)))
            for rank, suit in _ONE_CARD.findall(hand.cards)]


def _suited_flop(held: list[tuple[str, str]], pair: str, board: str, made: str) -> str | None:
    """เขียน flop จากอันดับไพ่เป็นไพ่จริง ไพ่ในมือตามดอกที่ถือ flop สามดอกไม่ซ้ำกันและไม่ชนไพ่ในมือ"""
    left = list(held)
    holes = []
    for rank in pair.split("-"):
        card = next((card for card in left if card[0] == rank), None)
        if card is None:
            return None
        left.remove(card)
        holes.append(card)
    ranks = board.split("-")
    for suits in itertools.permutations(_SUIT_SYMBOL.values(), len(ranks)):
        flop = list(zip(ranks, suits))
        if not any(card in held for card in flop):
            shown = " ".join(rank + suit for rank, suit in holes)
            return f"{shown} + {' '.join(rank + suit for rank, suit in flop)} rainbow → {made}"
    return None


def _miracle(hand: Hand, lang: str) -> str:
    """รายการ miracle flop หนึ่งบรรทัดต่อ flop: nut flush ก่อนถ้า A มีดอกคู่ แล้วตามด้วย nuts จากอันดับไพ่"""
    held = _held_cards(hand) if hand.cards else []
    lines = [line for line in (_flush_line(hand),) if line]
    for made, board, pair in _nut_flops(hand.ranks):
        suited = _suited_flop(held, pair, board, made) if held else None
        lines.append(suited or f"{pair} + {board} rainbow → {made}")
    if not lines:
        return ("No flop gives this hand the nuts by rank alone; its value is structural" if lang == "EN" else
                "ไม่มี flop ไหนทำให้มือนี้ติด nuts จากอันดับไพ่ คุณค่าอยู่ที่โครงสร้างของมือ")
    return "\n".join(lines[:MIRACLE_MAX])


def _example_groups(hand: Hand) -> list[list[int]] | None:
    """ตำแหน่งไพ่ที่ดอกเดียวกันในตัวอย่างดอก None คือบอกไม่ได้ (ss ที่ไม่รู้ว่า A มีดอกคู่ไหม)"""
    suiting, ranks = hand.suiting, hand.ranks
    if suiting is None or not suiting.suited:
        return []
    if suiting.double:
        for first, second in (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))):
            if all(ranks[a] != ranks[b] for a, b in (first, second)):
                return [list(first), list(second)]
        return None
    if suiting.suited_ranks:
        wanted, group = list(suiting.suited_ranks), []
        for index, rank in enumerate(ranks):
            if rank in wanted:
                wanted.remove(rank)
                group.append(index)
        return [group]
    if ACE in ranks and suiting.ace_suited is None:
        return None
    start = 0 if (ACE not in ranks or suiting.ace_suited) else ranks.count(ACE)
    first = start
    second = next((index for index in range(first + 1, 4) if ranks[index] != ranks[first]), None)
    return None if second is None else [[first, second]]


def _with_example_suits(hand: Hand) -> tuple[Hand, bool]:
    """มือที่บอกแค่รูปดอก (ds ss rb หรือไม่บอก) ใส่ดอกตัวอย่างให้เห็นไพ่จริง คืนมือกับว่าใส่ให้ไหม"""
    if hand.cards:
        return hand, False
    if hand.suiting is None:
        hand = dataclasses.replace(from_shape(hand.ranks, "rainbow"), suits_assumed=True)
    groups = _example_groups(hand)
    if groups is None:
        return hand, False
    symbols = list(_SUIT_SYMBOL.values())
    suits: list[str | None] = [None] * len(hand.ranks)
    for group, symbol in zip(groups, symbols):
        for index in group:
            suits[index] = symbol
    spare = iter(symbol for symbol in symbols if symbol not in suits)
    cards = "".join(rank + (suit or next(spare)) for rank, suit in zip(hand.ranks, suits))
    return dataclasses.replace(hand, cards=cards), True


def _plain_lines(hand: Hand, lang: str) -> list[tuple[str, str]]:
    words = LABELS.get(lang, LABELS["EN"])
    if hand.suiting is None and not hand.cards:
        hand = dataclasses.replace(from_shape(hand.ranks, "rainbow"), suits_assumed=True)
    hand, example = _with_example_suits(hand)
    shown = hand.cards or "-".join(hand.ranks)
    suit_detail = words["assumed"] if hand.suits_assumed else _shape_of(hand.suiting)
    if hand.suiting and hand.suiting.suited_ranks:
        suit_detail += f" ({_known_suit_pair(hand)} share a suit)"
    title = f"PLO {shown} · {suit_detail}" + (f" · {words['example']}" if example else "")
    if hand.suiting.ace_suited is None and ACE in hand.ranks:
        yes, no = classify(_concrete(hand, True)), classify(_concrete(hand, False))
        yes_type, _ = _display(yes, _concrete(hand, True), lang)
        no_type, _ = _display(no, _concrete(hand, False), lang)
        kind = yes_type if yes_type == no_type else (
            "Ace-high connected hand; suited pair not identified" if lang == "EN" else
            "มือ A-high ที่เชื่อมกัน; ยังไม่รู้ว่าไพ่คู่ไหนดอกเดียวกัน")
        yes_tier, no_tier = _tier_text(yes, words), _tier_text(no, words)
        tier = yes_tier if yes_tier == no_tier else (
            f"{yes_tier} if Ace shares the suit; {no_tier} otherwise" if lang == "EN" else
            f"{yes_tier} ถ้า A มีดอกคู่; ถ้าไม่ใช่ {no_tier}")
        play = _conditional_play(yes, no, lang)
        why = ("The suited pair was not identified, so its nut-flush value is conditional; "
               "specify it like ss A2." if lang == "EN" else
               "ยังไม่รู้ว่าไพ่คู่ไหนดอกเดียวกัน จึงยังตัดสินคุณค่า nut flush ไม่ได้; บอกเพิ่มแบบ ss A2")
    else:
        cluster = classify(hand)
        kind, why = _display(cluster, hand, lang)
        tier = _tier_text(cluster, words)
        play = _play(cluster, hand, lang)
    assumptions = ("4-card PLO high; general deep-stack cash guidance. Position, effective stack, "
                   "rake and prior action are unspecified; tournament payouts are not applied."
                   if lang == "EN" else
                   "PLO high 4 ใบ; คำแนะนำ cash game deep-stack ทั่วไป ยังไม่รู้ตำแหน่ง effective stack "
                   "rake และ action ก่อนหน้า และไม่ใช้รางวัลทัวร์นาเมนต์")
    return [("", title), (words["tier"], tier), (words["play"], play),
            (words["type"], kind), (words["why"], why),
            (words["miracle"], _miracle(hand, lang)), (words["assumptions"], assumptions),
            (words["source"], SOURCE)]


def _wrap(value: str, width: int) -> list[str]:
    """ตัดบรรทัดทีละรายการ ค่าที่มีหลายรายการคั่นด้วย newline"""
    return [part for item in value.split("\n")
            for part in (textwrap.wrap(item, width=width) or [""])] or [""]


def render(hand: Hand, lang: str) -> str:
    """Compact ANSI-free answer for web and Discord."""
    lines = []
    for label, value in _plain_lines(hand, lang):
        if not label:
            lines.append(value)
            continue
        field = max(WIDTH, len(label))
        wrapped = _wrap(value, max(20, 64 - field - 1))
        lines.append(f"{label:<{field}} {wrapped[0]}")
        lines.extend(f"{'':<{field}} {part}" for part in wrapped[1:])
    return "\n".join(lines)


def presentation(hand: Hand, lang: str) -> dict:
    """JSON-safe sections for clients that can present more than plain text."""
    rows = _plain_lines(hand, lang)
    values = dict(rows[1:])
    words = LABELS.get(lang, LABELS["EN"])
    shown, _ = _with_example_suits(hand)
    if shown.cards:
        cards = [{"rank": rank, "suit": suit} for rank, suit in _held_cards(shown)]
    else:
        cards = [{"rank": rank, "suit": ""} for rank in hand.ranks]
    keys = ("tier", "play", "type", "why", "miracle", "assumptions", "source")
    return {"title": rows[0][1], "cards": cards,
            "labels": {key: words[key] for key in keys},
            **{key: values[words[key]] for key in keys}}


def _tier_box(label: str, value: str, width: int, bold: str, reset: str) -> list[str]:
    box_width = min(width, 60)
    inside = box_width - 4
    parts = textwrap.wrap(f"{label.upper()} · {value}", width=inside) or [""]
    return [bold + "╔" + "═" * (box_width - 2) + "╗" + reset,
            *(bold + f"║ {part:<{inside}} ║" + reset for part in parts),
            bold + "╚" + "═" * (box_width - 2) + "╝" + reset]


def terminal(hand: Hand, lang: str, color: bool = True, width: int | None = None) -> str:
    """Spacious terminal presentation without changing the terminal's global font size."""
    width = max(48, min(width or shutil.get_terminal_size((64, 24)).columns, 88))
    bold, dim, reset = ("\033[1m", "\033[2m", "\033[0m") if color else ("", "", "")
    shown, _ = _with_example_suits(hand)
    cards = _held_cards(shown) if shown.cards else [(rank, "") for rank in hand.ranks]
    faces = ["  ".join("┌─────┐" for _ in cards),
             "  ".join(f"│  {rank}  │" for rank, _ in cards),
             "  ".join(f"│  {suit or ' '}  │" for _, suit in cards),
             "  ".join("└─────┘" for _ in cards)]
    rows = _plain_lines(hand, lang)
    lines = [bold + line + reset for line in faces]
    lines += [""] + textwrap.wrap(rows[0][1], width=width) + [""]
    values = dict(rows[1:])
    words = LABELS.get(lang, LABELS["EN"])
    lines += _tier_box(words["tier"], values[words["tier"]], width, bold, reset) + [""]
    ordered = (words["play"], words["type"], words["why"], words["miracle"],
               words["assumptions"], words["source"])
    for label in ordered:
        value = values[label]
        heading = label.upper()
        wrapped = _wrap(value, max(24, width - 2))
        lines.append(f"{bold}{heading}{reset}")
        lines.extend(f"  {part}" for part in wrapped)
        if label != words["source"]:
            lines.append("")
    if lines:
        lines[-1] = dim + lines[-1] + reset
    return "\n".join(lines)


def overview(lang: str) -> str:
    """ภาพรวมทุกกลุ่มและทุกแบบมือ เรียงตามกลุ่มในหนังสือ"""
    words = LABELS.get(lang, LABELS["EN"])
    lines = [words["overview"]]
    for key, name in GROUPS.items():
        lines.append(f"\n{name}")
        lines.extend(f"  {form.tier:<12} {form.label}: {form.cluster}"
                     for form in FORMS.values() if form.group == key)
    lines += ["", words["ask"], f"{words['source']}: {SOURCE}"]
    return "\n".join(lines)


def answer(asked: Asked, lang: str) -> str:
    if asked.error:
        prefix = "Invalid PLO hand" if lang == "EN" else "มือ PLO ไม่ถูกต้อง"
        return f"{prefix}: {asked.error}"
    return render(asked.hand, lang) if asked.hand else overview(lang)
