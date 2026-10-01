"""อ่านรูปหน้าจอโต๊ะโป๊กเกอร์ แล้วเขียนเป็นคำถามแบบที่คนพิมพ์ถาม spot_chart

โมเดลภาพของ DeepSeek อ่านรูปเป็น JSON ส่วนการนับตำแหน่ง สแตก และคำถาม คิดเองในไฟล์นี้
โมเดลบอกแค่สิ่งที่เห็น ลำดับผู้เล่นตามเข็มนาฬิกาเริ่มจากเรา (ที่นั่งล่างสุด) กับใครถือปุ่ม D

ปิด thinking ไว้ เปิดแล้วอ่านถูกเท่ากันแต่ช้า 7-35 วินาที ปิดแล้วราว 2 วินาที (ทดสอบ 2026-09-26)
รูปถูกย่อฝั่ง DeepSeek เหลือไม่เกิน 384 token ตัวเลขเล็ก ๆ อาจอ่านพลาด จึงบอกผู้ถามเสมอว่าอ่านได้อะไร
"""

from __future__ import annotations

import base64
import dataclasses
import json
import re
import sys
import pathlib
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from pushfold.spot import position_names  # noqa: E402

URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-v4-flash-vision-exp"
KEY_NAMES = ("DEEPSEEK_API_KEY", "DEEPSEEK_API")
TIMEOUT = 30.0
MIN_PLAYERS, MAX_PLAYERS = 2, 9
RANKS = "AKQJT98765432"
_CARD = re.compile(rf"^[{RANKS}][shdc]$")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_AOF = re.compile(r"all\s*-?\s*in\s*(?:or|/)\s*fold|\baof\b", re.IGNORECASE)
ALL_IN, FOLD = "all-in", "fold"

PROMPT = """This is a poker table screenshot. Return ONLY JSON, no prose:
{"game": str, "players": [{"name": str, "stack_bb": number, "bet_bb": number,
"action": "all-in"|"call"|"fold"|null, "cards": [str, str]|null}],
"button": str, "hand_finished": bool}
- game: the game name in the window title, e.g. "NL All-in or Fold".
- players: only players dealt into this hand, in CLOCKWISE order starting from the player
  at the bottom of the screen (the hero).
- stack_bb: the number under the player's name. bet_bb: chips in front of them, 0 if none.
- action: the label shown on the player this hand, null if none.
- cards: face-up cards like "Qh", "Td", "8c"; null when face down or absent.
- button: the name of the player next to the D button.
- hand_finished: true if a winner is shown or the board has five cards."""


class TableError(ValueError):
    """อ่านรูปนี้เป็นโต๊ะไม่ได้ ข้อความบอกว่าเพราะอะไร"""


@dataclasses.dataclass(frozen=True)
class Seat:
    name: str
    stack: float
    bet: float
    action: str | None
    cards: tuple[str, str] | None

    @property
    def total(self) -> float:
        return self.stack + self.bet


@dataclasses.dataclass(frozen=True)
class Table:
    aof: bool
    seats: tuple[Seat, ...]   # ตามเข็มนาฬิกา เริ่มที่เรา
    button: int               # ที่นั่งที่ถือปุ่ม D
    finished: bool


def ask(data: bytes, mime: str, api_key: str, prompt: str) -> str:
    """ส่งรูปกับคำสั่งให้โมเดลภาพของ DeepSeek คืนข้อความที่ตอบ พังเป็น TableError"""
    image = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    body = {"model": MODEL, "temperature": 0, "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image}},
                {"type": "text", "text": prompt}]}]}
    request = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            reply = json.loads(response.read())
        return reply["choices"][0]["message"]["content"]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as error:
        raise TableError(f"DeepSeek อ่านรูปไม่สำเร็จ: {error}") from error


def read(data: bytes, mime: str, api_key: str) -> Table:
    """ส่งรูปให้ DeepSeek อ่าน พังตรงไหนก็เป็น TableError ให้ผู้เรียกตอบผู้ใช้ได้"""
    return parse(ask(data, mime, api_key, PROMPT))


def parse(text: str) -> Table:
    """JSON ที่โมเดลตอบ บางทีห่อด้วย ```json มา"""
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
        players = data["players"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise TableError(f"ไม่ใช่ JSON ของโต๊ะ: {text[:80]!r}") from error
    if not isinstance(players, list) or not MIN_PLAYERS <= len(players) <= MAX_PLAYERS:
        raise TableError(f"ต้องมีผู้เล่น {MIN_PLAYERS}-{MAX_PLAYERS} คน")
    seats = tuple(_seat(item) for item in players)
    names = [seat.name for seat in seats]
    if data.get("button") not in names:
        raise TableError(f"ไม่รู้ว่าใครถือปุ่ม D ({data.get('button')!r})")
    return Table(aof=bool(_AOF.search(str(data.get("game") or ""))), seats=seats,
                 button=names.index(data["button"]), finished=bool(data.get("hand_finished")))


def _seat(item: dict) -> Seat:
    try:
        stack, bet = float(item.get("stack_bb") or 0), float(item.get("bet_bb") or 0)
    except (TypeError, ValueError) as error:
        raise TableError(f"สแตกอ่านไม่ออก: {item!r}") from error
    cards = item.get("cards")
    good = (isinstance(cards, list) and len(cards) == 2
            and all(isinstance(card, str) and _CARD.match(card) for card in cards))
    action = item.get("action")
    return Seat(name=str(item.get("name")), stack=max(stack, 0.0), bet=max(bet, 0.0),
                action=action.lower() if isinstance(action, str) else None,
                cards=tuple(cards) if good else None)


def seat_names(table: Table) -> tuple[str, ...]:
    """ตำแหน่งของทุกที่นั่ง ถัดจากปุ่มตามเข็มนาฬิกาคือ SB แล้ว BB heads-up ปุ่มคือ SB"""
    n = len(table.seats)
    order = position_names(n)  # ลำดับการเล่น UTG ... BTN SB BB
    first = n - 3 if n >= 3 else 0
    clockwise = order[first:] + order[:first]
    return tuple(clockwise[(i - table.button) % n] for i in range(n))


def hand_of(cards: tuple[str, str] | None) -> str | None:
    """ไพ่สองใบเป็นชื่อมือ Th 6d คือ T6o"""
    if not cards:
        return None
    high, low = sorted(cards, key=lambda card: RANKS.index(card[0]))
    if high[0] == low[0]:
        return high[0] * 2
    return f"{high[0]}{low[0]}{'s' if high[1] == low[1] else 'o'}"


def _stack(table: Table) -> float | None:
    """สแตกที่ใช้แก้ คือที่เรามี (รวมที่ลงไปแล้ว) ไม่เกินคนที่ยังอยู่ที่มีมากที่สุด"""
    hero = table.seats[0].total
    others = [seat.total for seat in table.seats[1:] if seat.action != FOLD and seat.total > 0]
    stack = min(hero, max(others)) if others else hero
    return stack if stack > 0 else None


def question(table: Table) -> str:
    """คำถามภาษาอังกฤษที่ spot_chart อ่านได้ เช่น aof 4 handed BB vs CO shove 10bb hold AJo"""
    names = seat_names(table)
    n = len(names)
    words = ["aof"] if table.aof else []
    words.append("heads-up" if n == 2 else f"{n} handed")
    words.append(names[0])
    if not table.finished:
        order = position_names(n)
        shovers = sorted((names[i] for i, seat in enumerate(table.seats)
                          if i and seat.action == ALL_IN), key=order.index)
        if len(shovers) == 1:
            words.append(f"vs {shovers[0]} shove")
        elif shovers:
            words.append("vs " + " and ".join(shovers))
    stack = _stack(table)
    if stack:
        words.append(f"{stack:g}bb")
    hand = hand_of(table.seats[0].cards)
    if hand:
        words.append(f"hold {hand}")
    return " ".join(words)
