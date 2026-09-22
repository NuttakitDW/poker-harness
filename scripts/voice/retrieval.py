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


@dataclasses.dataclass(frozen=True)
class Hit:
    """การ์ดหนึ่งใบพร้อมคะแนนความเกี่ยวข้อง"""

    card: corpus.Card
    score: float


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFC", text).lower()
    return _KEEP.sub(" ", folded)


def _features(text: str) -> collections.Counter:
    """ลักษณะเด่นของข้อความ: n-gram ของอักษร บวกคำอังกฤษเต็มคำ

    ศัพท์อังกฤษอย่าง ICM หรือ bankroll เป็นสัญญาณแยกแยะที่ชัดกว่า n-gram ไทย
    ที่พบได้ทั่วไป จึงให้น้ำหนักคำเต็มมากกว่า
    """
    counts: collections.Counter = collections.Counter()
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
        score = sum(weight * vector.get(gram, 0.0) for gram, weight in question.items())
        if score >= MIN_SCORE:
            scored.append(Hit(card, round(score, 4)))
    scored.sort(key=lambda hit: hit.score, reverse=True)
    return tuple(scored[:top_k])
