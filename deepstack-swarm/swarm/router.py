"""The Router: mailboxes between the user and the ten agents, plus the turn budget.

No LLM code here, so it can be tested on its own. Every agent turn spends one
unit of budget. When the budget runs out the swarm pauses: mail keeps queuing
but nobody wakes until the user grants more with /more. This is the brake on
agents politely replying to each other forever.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Iterable

from swarm.events import EventLog
from swarm.roster import USER_ID, Member


@dataclasses.dataclass(frozen=True)
class Mail:
    sender: str
    text: str
    direct: bool = False  # user wrote to this agent with /to, bypassing the lead
    auto: bool = False    # plain-text answer forwarded by the swarm, not sent by the agent


class Router:
    def __init__(self, roster: Iterable[Member], log: EventLog, turn_budget: int):
        self.members = {m.id: m for m in roster}
        self.log = log
        self.inboxes: dict[str, asyncio.Queue[Mail]] = {mid: asyncio.Queue() for mid in self.members}
        self.turns_left = turn_budget
        self._resumed = asyncio.Event()
        self._resumed.set()

    def known(self, member_id: str) -> bool:
        return member_id in self.members

    def send(self, sender: str, to: str, text: str, direct: bool = False, auto: bool = False) -> str:
        """Queue mail; returns an error string instead of raising, for tool results."""
        text = text.strip()
        if not text:
            return "error: empty message"
        targets = [m for m in self.members if m != sender] if to == "all" else [to]
        unknown = [t for t in targets if not self.known(t)]
        if unknown:
            return f"error: unknown member {unknown[0]!r}; use one of {', '.join(self.members)} or 'all'"
        if sender in targets:
            return "error: cannot message yourself"
        for target in targets:
            self.inboxes[target].put_nowait(Mail(sender, text, direct, auto))
        event = "user" if sender == USER_ID else "message"
        self.log.emit(event, sender=sender, to=to, text=text, **({"auto": True} if auto else {}))
        return f"delivered to {to}"

    async def next_batch(self, member_id: str) -> list[Mail]:
        """Wait for mail, then wait for budget, then take everything queued."""
        inbox = self.inboxes[member_id]
        first = await inbox.get()
        batch = [first]
        await self._take_turn()
        while not inbox.empty():
            batch.append(inbox.get_nowait())
        return batch

    async def _take_turn(self) -> None:
        while self.turns_left <= 0:
            await self._resumed.wait()
        self.turns_left -= 1
        if self.turns_left == 0:
            self._resumed.clear()
            self.log.emit("notice", text="turn budget used up; the swarm is paused until /more", turns_left=0)

    def grant(self, turns: int) -> None:
        self.turns_left += turns
        if self.turns_left > 0:
            self._resumed.set()
        self.log.emit("notice", text=f"granted {turns} turns ({self.turns_left} left)", turns_left=self.turns_left)

    def clear(self) -> int:
        """Drop all queued mail; returns how many were dropped."""
        dropped = 0
        for inbox in self.inboxes.values():
            while not inbox.empty():
                inbox.get_nowait()
                dropped += 1
        return dropped

    def pending(self) -> dict[str, int]:
        return {mid: q.qsize() for mid, q in self.inboxes.items()}
