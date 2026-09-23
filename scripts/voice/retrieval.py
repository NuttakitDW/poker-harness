"""เลือกการ์ดหัวข้อที่ตรงกับคำถามมากที่สุด

ใช้ TF-IDF บน character n-gram เพราะภาษาไทยไม่เว้นวรรคระหว่างคำ
และ n-gram ยังทนต่อข้อความที่ถอดเสียงมาเพี้ยนบางตัวอักษร
"""

from __future__ import annotations

import collections
import dataclasses
import functools
import math
import re
import unicodedata

import corpus

NGRAM = 3
TOP_K = 3
MIN_SCORE = 0.02
WORD_WEIGHT = 4
_KEEP = re.compile(r"[^\w฀-๿]+")
_LATIN = re.compile(r"^[a-z0-9][a-z0-9'-]*$")
# ไพ่ Omaha ที่ถอดจากเสียงมักแยกเป็นก้อน เช่น "KK QJ" หรือ "A A K K" จึงรวมก้อนอันดับไพ่ที่ติดกัน
# ก้อนที่เป็นตัวเลขล้วนต้องเป็นไพ่ใบเดียว ไม่อย่างนั้น "blinds 5 10 25" จะกลายเป็นมือ
_RANK_WORD = re.compile(r"^(?:[akqjt2-9]+|10)$", re.IGNORECASE)
_TEN_THEN_RANK = re.compile(r"^1[2-9]$")
# ตัวถอดเสียงเขียนมือ PLO "AA95" เป็น "AA9500" มีศูนย์ติดท้าย ไพ่ไม่มีเลขศูนย์
# ต้องมีตัวอักษรไพ่อย่างน้อยหนึ่งตัว ไม่งั้นสแตกอย่าง "9500" จะกลายเป็นมือ
_ZERO_TAIL = re.compile(r"^((?=[2-9]*[akqjt])[akqjt2-9]{4})0+$", re.IGNORECASE)
HAND_CARDS = 4
RANK_ORDER = "AKQJT98765432"
# ชื่อไพ่ที่ถอดจากเสียงภาษาไทย "เอ" ต้องเป็นคำโดด ไม่อย่างนั้น "เอา" "เอง" จะกลายเป็นไพ่
# ไม่รับตัวเลขภาษาไทยอย่าง "สอง" เพราะชนกับ "สองใบ" ตัวถอดเสียงเขียนไพ่เลขเป็นตัวเลขอยู่แล้ว
_THAI_RANKS = (
    ("A", ("เอซ", "เอส", "เอ")),
    ("K", ("คิง",)),
    ("Q", ("ควีน",)),
    ("J", ("แจ็ค", "แจ๊ค", "แจ็ก")),
    ("T", ("เท็น", "เทน")),
)
_THAI_RANK = re.compile(
    r"(เอซ|เอส|เอ(?=[\sๆ,\-]|$)|คิง|ควีน|แจ็ค|แจ๊ค|แจ็ก|เท็น|เทน)(\s*ๆ)?")
# ตัวถอดเสียงบางทีเขียนชื่อไพ่เป็นคำอังกฤษ เช่น "A Jack Ten Ten" ไม่รับ two ถึง nine
# เพราะชนกับ "two pair" "four bet" และตัวถอดเสียงเขียนไพ่เลขเป็นตัวเลขอยู่แล้ว
_ENGLISH_RANKS = {"ace": "A", "king": "K", "queen": "Q", "jack": "J", "ten": "T"}
_ENGLISH_RANK = re.compile(r"(?<![A-Za-z])(" + "|".join(_ENGLISH_RANKS) + r")s?(?![A-Za-z])",
                           re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class Hit:
    """การ์ดหนึ่งใบพร้อมคะแนนความเกี่ยวข้อง"""

    card: corpus.Card
    score: float


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFC", text).lower()
    return _KEEP.sub(" ", folded)


def _ranks(word: str) -> str | None:
    """อันดับไพ่ในคำหนึ่งคำ หรือ None ถ้าคำนั้นไม่ใช่ไพ่"""
    # ตัวถอดเสียงเขียน "เท็น ไนน์" ติดกันเป็น 19 เลข 1 ตามด้วยไพ่อีกใบจึงคือไพ่สิบ
    if _TEN_THEN_RANK.match(word):
        return f"T{word[1]}"
    if not _RANK_WORD.match(word) or (word.isdigit() and word not in "23456789" and word != "10"):
        return None
    return word.upper().replace("10", "T")


def latin_ranks(text: str) -> str:
    """เปลี่ยนชื่อไพ่ภาษาไทยเป็นตัวอักษร เช่น "คิงๆ ควีน" เป็น " K K  Q "

    ไม้ยมกหลังชื่อไพ่คือไพ่ใบนั้นสองใบ เพราะคนพูด "คิงๆ" หมายถึงคิงคู่
    """
    def swap(match: re.Match) -> str:
        rank = next(letter for letter, words in _THAI_RANKS if match.group(1) in words)
        return f" {rank} {rank} " if match.group(2) else f" {rank} "
    english = _ENGLISH_RANK.sub(lambda match: f" {_ENGLISH_RANKS[match.group(1).lower()]} ", text)
    return _THAI_RANK.sub(swap, english)


def hands(text: str) -> tuple[str, ...]:
    """มือ Omaha สี่ใบที่พูดถึงในข้อความ เขียนแบบ KKQJ เรียงใหญ่ไปเล็กให้ตรงกับโน้ตในคลัง"""
    found: list[str] = []
    run = ""
    for word in [*re.split(r"[^\w]+", latin_ranks(text)), ""]:
        word = _ZERO_TAIL.sub(r"\1", word)
        ranks = _ranks(word) if word else None
        # มือที่เขียนติดกันเป็นคำเดียวอย่าง A299 ครบในตัว ไม่ต่อกับไพ่ที่พูดตามหลังเพื่อบอกดอก
        if ranks is not None and len(ranks) == HAND_CARDS and len(word) >= HAND_CARDS:
            if len(run) == HAND_CARDS:
                found.append("".join(sorted(run, key=RANK_ORDER.index)))
            found.append("".join(sorted(ranks, key=RANK_ORDER.index)))
            run = ""
            continue
        if ranks is not None:
            run += ranks
            continue
        if len(run) == HAND_CARDS:
            found.append("".join(sorted(run, key=RANK_ORDER.index)))
        run = ""
    return tuple(dict.fromkeys(found))


def _allowed(card: corpus.Card, query: str) -> bool:
    """การ์ดที่ระบุเกมย่อยไว้จะถูกเลือกเมื่อคำถามพูดถึงเกมนั้นเท่านั้น"""
    if not card.requires:
        return True
    spaced = _normalize(query)
    joined = spaced.replace(" ", "")
    return any(_normalize(term).strip() in spaced or _normalize(term).replace(" ", "") in joined
               for term in card.requires)


def _features(text: str) -> collections.Counter:
    """ลักษณะเด่นของข้อความ: n-gram ของอักษร บวกคำอังกฤษเต็มคำ

    ศัพท์อังกฤษอย่าง ICM หรือ bankroll เป็นสัญญาณแยกแยะที่ชัดกว่า n-gram ไทย
    ที่พบได้ทั่วไป จึงให้น้ำหนักคำเต็มมากกว่า
    """
    counts: collections.Counter = collections.Counter()
    for hand in hands(text):
        counts[f"w:{hand.lower()}"] += WORD_WEIGHT
    for word in _normalize(text).split():
        if _LATIN.match(word):
            counts[f"w:{word}"] += WORD_WEIGHT
        if len(word) <= NGRAM:
            counts[word] += 1
            continue
        for index in range(len(word) - NGRAM + 1):
            counts[word[index:index + NGRAM]] += 1
    return counts


def _weights(counts: collections.Counter, idf: dict[str, float]) -> dict[str, float]:
    """เวกเตอร์ tf-idf ที่ทำให้ยาวเป็นหนึ่งแล้ว"""
    raw = {g: (1 + math.log(n)) * idf.get(g, 0.0) for g, n in counts.items()}
    norm = math.sqrt(sum(v * v for v in raw.values()))
    return {g: v / norm for g, v in raw.items()} if norm else {}


@functools.lru_cache(maxsize=1)
def _index() -> tuple[tuple[tuple[corpus.Card, dict[str, float]], ...], dict[str, float]]:
    """ดัชนีของการ์ดทุกใบพร้อมค่า idf สร้างครั้งเดียวแล้วเก็บไว้"""
    cards = corpus.load_cards()
    features = [_features(card.body) for card in cards]
    document_count: collections.Counter = collections.Counter()
    for counts in features:
        document_count.update(counts.keys())
    total = len(cards)
    idf = {g: math.log((1 + total) / (1 + n)) + 1 for g, n in document_count.items()}
    entries = tuple((card, _weights(counts, idf)) for card, counts in zip(cards, features))
    return entries, idf


def search(query: str, language: str = "TH", top_k: int = TOP_K) -> tuple[Hit, ...]:
    """การ์ดที่เกี่ยวข้องที่สุด เรียงจากคะแนนมากไปน้อย"""
    entries, idf = _index()
    question = _weights(_features(query), idf)
    if not question:
        return ()
    scored = []
    for card, vector in entries:
        if language and card.language != language:
            continue
        if not _allowed(card, query):
            continue
        score = sum(weight * vector.get(gram, 0.0) for gram, weight in question.items())
        if score >= MIN_SCORE:
            scored.append(Hit(card, round(score, 4)))
    scored.sort(key=lambda hit: hit.score, reverse=True)
    return tuple(scored[:top_k])
