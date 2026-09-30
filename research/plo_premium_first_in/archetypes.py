"""Data-driven first-in archetypes for 20bb six-max PLO, derived from the tier-pure solve.

Rules are checked in order; the first match wins. A ``big`` card is a Ten or higher
(a paired big card counts twice), a ``suited Ace`` shares its suit with another card,
and a ``rundown`` has all four ranks inside one five-rank straight window.
"""

from __future__ import annotations

from typing import Mapping

TEN, QUEEN, KING = 8, 10, 11
SUITED = ("ss", "ds")

ARCHETYPES = (
    ("aces", "Aces", "Two or more Aces."),
    ("nut_big", "Nut big cards",
     "Three or more big cards with a suited Ace or two suits; or double-suited with a suited Ace "
     "and one more big card."),
    ("strong_pair", "Strong big pair",
     "KK that is not rainbow, QQ with another big card, or JJ/TT with two other big cards."),
    ("broadway_rundown", "Broadway rundown", "Unpaired suited rundown with at least two big cards."),
    ("medium_pair", "Medium big pair", "Suited QQ, suited JJ/TT with another big card, or KK rainbow."),
    ("big_one_suit", "Big cards, one suit",
     "Unpaired: three big cards single-suited, or two big cards double-suited, no suited Ace."),
    ("ace_suited", "Suited Ace",
     "A suited Ace with one more big card, or a double-suited Ace-high hand."),
    ("late_big", "Big cards, poor suits",
     "Anything left with three big cards or a TT-QQ pair: mostly rainbow or three-flush big cards, "
     "and TT-JJ with no second big card."),
    ("low_ds_rundown", "Double-suited low rundown", "Double-suited rundown with at most one big card."),
    ("small_pair_ace", "Small pair with suited Ace", "A pair of Nines or lower plus a suited Ace."),
    ("rest", "Rest", "Everything else, including every single-suited rundown below Ten."),
)
NAMES = {key: name for key, name, _ in ARCHETYPES}
ORDER = tuple(key for key, _, _ in ARCHETYPES)


def archetype(f: Mapping[str, object]) -> str:
    """Classify a hand from its ``features()`` dictionary."""
    high, shape, flush = int(f["high"]), str(f["shape"]), str(f["flush"])
    structure, pair, window = str(f["structure"]), int(f["pair_rank"]), int(f["window"])
    nut = flush == "nut"
    paired = structure in ("one_pair", "two_pair")
    big_pair = paired and pair >= TEN
    if int(f["aces"]) >= 2:
        return "aces"
    if structure == "trips":
        return "rest"
    if (high >= 3 and (nut or shape == "ds")) or (shape == "ds" and nut and high >= 2):
        return "nut_big"
    if big_pair and ((pair == KING and shape != "rb") or (pair == QUEEN and high >= 3) or high >= 4):
        return "strong_pair"
    if structure == "unpaired" and window == 4 and high >= 2 and shape in SUITED:
        return "broadway_rundown"
    if big_pair and (shape in SUITED or pair == KING) and (pair >= QUEEN or high >= 3):
        return "medium_pair"
    if structure == "unpaired" and shape in SUITED and (high >= 3 or (shape == "ds" and high >= 2)):
        return "big_one_suit"
    if nut and (high >= 2 or shape == "ds"):
        return "ace_suited"
    if high >= 3 or big_pair:
        return "late_big"
    if shape == "ds" and window == 4:
        return "low_ds_rundown"
    if paired and nut:
        return "small_pair_ace"
    return "rest"
