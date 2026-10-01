"""Read a PLO final-table screenshot into seats, stacks, blinds and the hero's hand.

The vision model only reports what it sees: players clockwise from the hero (the bottom
seat), who holds the dealer button, stacks as printed, and the blind level if shown. Seat
names and big-blind conversion are worked out here, and anything that could not be read is
listed in ``notes`` so the page can ask the player to fill it in.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "voice"))
sys.path.insert(0, str(ROOT))

import keys  # noqa: E402
import table_image  # noqa: E402

from plo_premium_proof.finaltable import MAX_SEATS, SEAT_NAMES  # noqa: E402

KEY_NAMES = table_image.KEY_NAMES
_CARD = re.compile(r"^[2-9TJQKA][shdc]$")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

PROMPT = """This is a screenshot of a Pot-Limit Omaha tournament final table. Return ONLY JSON, no prose:
{"players": [{"name": str, "stack": number, "bet": number, "cards": [str, str, str, str] | null}],
 "button": str, "stack_unit": "bb" | "chips",
 "blinds": {"sb": number | null, "bb": number | null, "ante": number | null}}
- players: every player still seated with chips, in CLOCKWISE order starting from the player
  at the bottom of the screen (the hero).
- stack: the number shown under the player's name, as a plain number (1,250,000 -> 1250000;
  1.25M -> 1250000; 38.5 BB -> 38.5). bet: chips in front of the player, 0 if none.
- stack_unit: "bb" when stacks are shown in big blinds, otherwise "chips".
- blinds: the blind level in chips if it is shown anywhere (e.g. "Blinds 20K/40K Ante 5K"), else nulls.
- cards: the hero's four face-up cards like "Ah", "Kd", "9c", "8s"; null for everyone else.
- button: the name of the player next to the D (dealer) button."""


class ReadError(ValueError):
    """The screenshot could not be read as a final table."""


def seat_order(count: int, button: int) -> list[int]:
    """Preflop seat index (UTG ... BTN, SB, BB) of each player listed clockwise from the hero."""
    if count == 2:
        return [(i - button) % 2 for i in range(2)]  # heads-up the button is the small blind
    return [((i - button) % count - 3) % count for i in range(count)]


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def parse(text: str) -> dict:
    """The model's JSON as the page's table: seats in preflop order with stacks in bb."""
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
        players = data["players"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReadError(f"the reply is not a table: {text[:80]!r}") from error
    if not isinstance(players, list) or not 2 <= len(players) <= MAX_SEATS:
        raise ReadError(f"expected 2-{MAX_SEATS} players, read {len(players) if isinstance(players, list) else 0}")
    names = [str(p.get("name") or f"Player {i + 1}") for i, p in enumerate(players)]
    if data.get("button") not in names:
        raise ReadError(f"could not tell who has the dealer button ({data.get('button')!r})")
    notes: list[str] = []
    blinds = data.get("blinds") or {}
    big = _number(blinds.get("bb"))
    ante = _number(blinds.get("ante"))
    unit = "bb" if data.get("stack_unit") == "bb" else "chips"
    order = seat_order(len(players), names.index(data["button"]))
    labels = SEAT_NAMES[len(players)]
    seats = [None] * len(players)
    for i, player in enumerate(players):
        chips = (_number(player.get("stack")) or 0.0) + (_number(player.get("bet")) or 0.0)
        stack_bb = chips if unit == "bb" else (chips / big if big else None)
        seats[order[i]] = {"position": labels[order[i]], "name": names[i], "stack_raw": chips,
                           "stack_bb": round(stack_bb, 2) if stack_bb is not None else None}
    if unit == "chips" and not big:
        notes.append("stacks are in chips and the big blind was not visible: enter the big blind")
    ante_bb = None
    if ante is not None and ante > 0:
        ante_bb = round(ante / big, 4) if big else None
        if ante_bb is None:
            notes.append("an ante was shown but the big blind was not: enter the ante in bb")
    cards = players[0].get("cards")
    hand = "".join(cards) if (isinstance(cards, list) and len(cards) == 4
                               and all(isinstance(c, str) and _CARD.match(c) for c in cards)) else None
    if hand is None:
        notes.append("the hero's four cards were not read")
    return {"seats": seats, "hero": labels[order[0]], "hand": hand, "unit": unit,
            "blinds": {"sb": _number(blinds.get("sb")), "bb": big, "ante": ante},
            "ante_bb": ante_bb, "notes": notes}


def read(data: bytes, mime: str) -> dict:
    key = keys.find(*KEY_NAMES)
    if not key:
        raise ReadError(f"no vision key: set {KEY_NAMES[0]} in .env")
    try:
        return parse(table_image.ask(data, mime, key, PROMPT))
    except table_image.TableError as error:
        raise ReadError(str(error)) from error
