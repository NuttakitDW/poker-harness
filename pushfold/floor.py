"""The Floor: who may act after what.

Every action is all-in or fold. First in: fold or shove. Facing a shove: fold or call
(a call is all-in too; chips nobody can match come back from the Cashier).
Once `max_allin` players are in, everyone left must fold (we cap showdowns at 3-way).
If everyone folds to the BB, the BB wins without acting.
"""

from __future__ import annotations

import dataclasses

from pushfold.spot import Spot

FOLD, JAM, IDLE = 0, 1, 2  # IDLE: never got to act (walk, or forced fold after the cap)
MAX_ALLIN = 3


@dataclasses.dataclass(frozen=True)
class Node:
    index: int
    seat: int
    history: tuple[int, ...]   # actions of the seats before this one

    @property
    def facing(self) -> bool:
        return JAM in self.history

    @property
    def labels(self) -> tuple[str, str]:
        return ("fold", "call") if self.facing else ("fold", "shove")


@dataclasses.dataclass(frozen=True)
class Terminal:
    index: int
    actions: tuple[int, ...]   # one per seat: FOLD, JAM or IDLE
    nodes: tuple[int, ...]     # node where each seat acted, -1 if IDLE

    @property
    def jammers(self) -> tuple[int, ...]:
        return tuple(s for s, a in enumerate(self.actions) if a == JAM)

    @property
    def alive(self) -> tuple[int, ...]:
        """Seats still holding cards: the jammers, or the BB on a walk."""
        return self.jammers or (len(self.actions) - 1,)


@dataclasses.dataclass(frozen=True)
class Tree:
    spot: Spot
    nodes: tuple[Node, ...]
    terminals: tuple[Terminal, ...]

    def nodes_of(self, seat: int) -> list[Node]:
        return [node for node in self.nodes if node.seat == seat]


def build(spot: Spot, max_allin: int = MAX_ALLIN) -> Tree:
    nodes: list[Node] = []
    terminals: list[Terminal] = []

    def walk(history: tuple[int, ...], links: tuple[int, ...]) -> None:
        seat = len(history)
        if seat == spot.n:
            terminals.append(Terminal(len(terminals), history, links))
            return
        jams = history.count(JAM)
        walked = seat == spot.n - 1 and jams == 0
        if walked or jams >= max_allin:
            rest = spot.n - seat
            terminals.append(Terminal(len(terminals), history + (IDLE,) * rest, links + (-1,) * rest))
            return
        node = Node(len(nodes), seat, history)
        nodes.append(node)
        for action in (FOLD, JAM):
            walk(history + (action,), links + (node.index,))

    walk((), ())
    return Tree(spot, tuple(nodes), tuple(terminals))
