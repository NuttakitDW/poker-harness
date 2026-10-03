"""Hold'em equity questions in the chart chat: "K8 vs A7 equity", "AKs vs QQ vs JTs %",
"KsKc vs AhKh on Qh7h2c". The numbers come from equity.calculate (exact enumeration with the
precomputed preflop memo), never from the language model.

A message counts as an equity question only when it says so (equity, %, odds, โอกาสชนะ ...) and
names two to six hands or ranges separated by "vs" (or "กับ", "against"), so spot questions like
"BB vs BTN shove 10bb" keep going to the chart solver.
"""

from __future__ import annotations

import dataclasses
import re

import equity

KEYWORD = re.compile(r"(?i)equity|\beq\b|odds|win\s*(?:rate|chance|%)|%|percent|อี?ค[ิวี]+ตี้|อิควิตี้|"
                     r"เปอร์เซ็น|โอกาสชนะ|เป็นต่อ|ชนะกี่")
SEPARATOR = re.compile(r"(?i)\s+(?:vs\.?|v\.?|versus|against|กับ|เจอ|ชน)\s+|\s*\bvs\.?\s*")
BOARD = re.compile(r"(?i)(?:\bon\b|\bboard\b|\bflop\b|\bturn\b|บอร์ด|ฟล็อป|ฟลอป)\s*[:=]?\s*"
                   r"((?:(?:10|[2-9tjqka])[shdc]\s*){3,5})")
CARD = r"(?:10|[2-9TJQKA])[shdc]"
SPECIFIC = re.compile(rf"(?i)^{CARD}{CARD}$")
RANGE_PART = r"(?:10|[2-9TJQKA])(?:10|[2-9TJQKA])[so]?\+?(?:-(?:10|[2-9TJQKA]){2}[so]?)?"
RANGE = re.compile(rf"(?i)^{RANGE_PART}(?:,{RANGE_PART})*$")
ANY = re.compile(r"(?i)^(?:any(?:\s*two)?|random|xx|100%)$")
TOKEN = re.compile(r"[A-Za-z0-9+,\-%]+")
WORDS = {
    "EN": {"title": "Equity {when}", "preflop": "preflop", "board": "on {board}",
           "exact": "exact, every board", "exact_board": "exact, every runout", "approx": "estimate ±{margin:.1f}%",
           "line": "{hand}  {eq:.1f}%  (win {win:.1f}% · tie {tie:.1f}%)", "combos": "combos: {combos}",
           "made": "now: {made}"},
    "TH": {"title": "equity {when}", "preflop": "ก่อน flop", "board": "บนบอร์ด {board}",
           "exact": "คิดครบทุกบอร์ด", "exact_board": "คิดครบทุกใบที่เหลือ", "approx": "ค่าประมาณ ±{margin:.1f}%",
           "line": "{hand}  {eq:.1f}%  (ชนะ {win:.1f}% · เสมอ {tie:.1f}%)", "combos": "นับทุกมือที่เป็นไปได้ {combos} แบบ",
           "made": "ตอนนี้: {made}"},
}


@dataclasses.dataclass(frozen=True)
class Asked:
    players: tuple[str, ...]
    board: str


def _card_text(text: str) -> str:
    text = text.replace("10", "T")
    return "".join(c.upper() if c.isalnum() and i % 2 == 0 else c.lower() for i, c in enumerate(text))


def _hand(side: str) -> str | None:
    """The one hand or range named in one side of the question, written the way equity.py reads it."""
    side = KEYWORD.sub(" ", side)
    if ANY.match(side.strip()):
        return "any"
    for raw in TOKEN.findall(side):
        token = raw.strip(",")
        if SPECIFIC.match(token):
            return _card_text(token)
        if RANGE.match(token):
            fixed = token.replace("10", "T")
            parts = []
            for part in fixed.split(","):
                head, _, tail = part.partition("-")
                norm = lambda p: p[:2].upper() + p[2:].lower()  # noqa: E731
                parts.append(norm(head) + (f"-{norm(tail)}" if tail else ""))
            return ",".join(parts)
        if ANY.match(token):
            return "any"
    return None


def parse(text: str) -> Asked | None:
    """An equity question, or None when the message is something else."""
    if not KEYWORD.search(text):
        return None
    board = ""
    found = BOARD.search(text)
    if found:
        board = _card_text(re.sub(r"\s+", "", found.group(1)))
        text = text[:found.start()] + " " + text[found.end():]
    sides = [s for s in SEPARATOR.split(text) if s.strip()]
    if not 2 <= len(sides) <= equity.MAX_PLAYERS:
        return None
    hands = [_hand(side) for side in sides]
    if any(h is None for h in hands):
        return None
    return Asked(tuple(hands), board)


def answer(asked: Asked, lang: str) -> str:
    """The equity table as chat text; raises equity.EquityError for impossible hands or boards."""
    words = WORDS["TH" if lang == "TH" else "EN"]
    result = equity.calculate(list(asked.players), asked.board)
    when = words["board"].format(board=asked.board) if asked.board else words["preflop"]
    exact = words["exact_board"] if asked.board else words["exact"]
    how = exact if result.exact else words["approx"].format(margin=result.margin * 100)
    lines = [f"{words['title'].format(when=when)} ({how})"]
    for player in result.players:
        line = words["line"].format(hand=player.label, eq=player.equity * 100, win=player.win * 100,
                                    tie=player.tie * 100)
        if player.made_hand:
            line += " · " + words["made"].format(made=player.made_hand)
        lines.append(line)
    if any(p.combos > 1 for p in result.players):
        lines.append(words["combos"].format(combos=" x ".join(str(p.combos) for p in result.players)))
    return "\n".join(lines)
