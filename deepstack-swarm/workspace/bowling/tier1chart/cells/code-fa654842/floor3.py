"""The Floor for ICM-OPEN3BET-v0: who may act after what, when a seat acts more than once.

Drop-in replacement for `pushfold.floor.build`, never editing it. Differences that matter:

* A node has 2-4 actions, not 2, so everything is indexed by *sequence* (node, action) pairs
  rather than by node*2+action.
* A seat can act up to three times on one path (open, then face a 3bet, then face a 4bet-all-in),
  so a Terminal records the whole path and each Node records this seat's previous decision.
  Counterfactual values, average-strategy weights and best responses all need that.
* Terminals are tagged by type: ALLFOLD / UNCONTESTED / SHOWDOWN / FLOP, and carry the chips
  each seat put in, so a Terminal can be priced without re-deriving it from an "all-in" flag.

Action abstraction (bowling, `workspace/bowling/open3bet-design.md` §2), sizes in bb:
  unopened, not BB : fold, open to OPEN, all-in
  unopened BB      : no decision (walk), unless it faces a seat all-in by posting
  facing one raise : fold, call, 3bet to MULT x the facing raise, all-in
  facing 3bet+     : fold, call, all-in
  facing an all-in : fold, call
A raise is clipped to the stack and dropped when within RAISE_GAP bb of all-in. No limps.

Cap: at most `cap` seats may still hold cards when preflop ends. A seat whose non-fold action
would make it the (cap+1)-th seat in for the current price may only fold. Same rule as
`pushfold.floor` MAX_ALLIN = 3, and the same rule GTO Wizard ships.

Round closure: the round ends when only one seat is live, or when every live seat is all-in or
has both matched the current bet and acted since the last raise.

`behind_cap` (default None = unchanged behaviour). `bowling-tier1-flop-gap.md`: at *unequal*
stacks, Tier 1 still lets a deep seat call a short jam and keep chips, so two deep seats can both
do it, `close()` tags the ending FLOP, and nothing downstream prices a flop -- the ending is
settled by `cashier3.checkdown`, which is the L0 leaf. `behind_cap=k` makes a non-fold action
illegal when, right after it, more than `k` live seats would be matched at the new price with
chips behind (the exact condition `close()` tests as FLOP). `behind_cap=1` is "the cap
strengthened so at most one live seat has chips behind": a leaf-free Tier 1 tree at any stacks.
At equal stacks it can never bind, so `behind_cap=1` is a no-op there -- which is what makes it
usable as the leaf-free arm of an A/B.
"""

from __future__ import annotations

import dataclasses

from pushfold.spot import Spot

FOLD, CALL, RAISE, ALLIN = 0, 1, 2, 3
ACTION_NAMES = ("fold", "call", "raise", "allin")
ALLFOLD, UNCONTESTED, SHOWDOWN, FLOP = "allfold", "uncontested", "showdown", "flop"

OPEN = 2.2        # unopened raise, in bb
MULT = 3.0        # a 3bet is this times the raise it faces
RAISE_GAP = 1.0   # drop a raise that leaves under this much behind: play it as all-in
CAP = 3           # seats that may reach the flop
EPS = 1e-9


@dataclasses.dataclass(frozen=True)
class Node:
    index: int
    seat: int
    actions: tuple[int, ...]           # subset of (FOLD, CALL, RAISE, ALLIN), in that order
    history: tuple[tuple[int, int], ...]   # (seat, action) of every decision before this one
    base: int                          # global sequence id of actions[0]
    own_prev: int                      # this seat's previous node on this path, -1 if none
    to_call: float                     # chips this seat must add to match
    raise_to: float                    # total this seat's RAISE goes to (0.0 if RAISE is illegal)
    pot: float                         # chips in the middle before this decision, antes included
    raises: int                        # raises already made (an open is 1)

    @property
    def labels(self) -> tuple[str, ...]:
        out = []
        for a in self.actions:
            if a == RAISE:
                out.append(f"{'open' if self.raises == 0 else '3bet'} {self.raise_to:g}")
            elif a == CALL:
                out.append(f"call {self.to_call:g}")
            else:
                out.append(ACTION_NAMES[a])
        return tuple(out)

    def seq(self, action: int) -> int:
        return self.base + self.actions.index(action)

    @property
    def own_prev_action(self) -> int:
        """Action this seat took at `own_prev` to reach here, -1 if this is its first decision."""
        for s, a in reversed(self.history):
            if s == self.seat:
                return a
        return -1


@dataclasses.dataclass(frozen=True)
class Terminal:
    index: int
    kind: str
    live: tuple[int, ...]              # seats still holding cards
    invested: tuple[float, ...]        # per seat, chips put in beyond the ante (blinds included)
    path: tuple[tuple[int, int], ...]  # (node index, action) of every decision taken
    raises: int

    def behind(self, spot: Spot) -> tuple[float, ...]:
        return tuple(spot.stacks[s] - spot.antes[s] - self.invested[s] for s in range(len(spot.stacks)))

    def pot(self, spot: Spot) -> float:
        return float(sum(self.invested) + sum(spot.antes))

    def decisions_of(self, seat: int, nodes: tuple[Node, ...]) -> tuple[tuple[int, int], ...]:
        return tuple((i, a) for i, a in self.path if nodes[i].seat == seat)


@dataclasses.dataclass(frozen=True)
class Tree:
    spot: Spot
    nodes: tuple[Node, ...]
    terminals: tuple[Terminal, ...]
    sequences: int                     # total (node, action) pairs
    cap: int

    def nodes_of(self, seat: int) -> list[Node]:
        return [n for n in self.nodes if n.seat == seat]

    @property
    def max_actions(self) -> int:
        return max((len(n.actions) for n in self.nodes), default=0)

    def counts(self) -> dict[str, int]:
        out = {k: 0 for k in (ALLFOLD, UNCONTESTED, SHOWDOWN, FLOP)}
        for z in self.terminals:
            out[z.kind] += 1
        return out

    def depth_of_own_decisions(self) -> int:
        """Most decisions one seat makes on one path: how many targets a terminal term hits."""
        best = 0
        for z in self.terminals:
            for seat in range(self.spot.n):
                best = max(best, sum(1 for i, _ in z.path if self.nodes[i].seat == seat))
        return best


def _behind_after(invested, live, cur_bet, raise_to, room, seat, action) -> int:
    """Live seats that would be matched at the post-action price with chips behind.

    This is `close()`'s FLOP test (`room[s] - invested[s] > EPS` over matched live seats) read
    one action early, at the price the action sets. A seat can only become matched-with-chips by
    acting, so testing every action means no close can find two of them -- see `behind_cap`.
    """
    inv, ncur = invested[seat], cur_bet
    if action == CALL:
        inv = min(cur_bet, room[seat])
    elif action == RAISE:
        inv = ncur = raise_to
    else:                                            # ALLIN
        inv = room[seat]
        if inv > cur_bet + EPS:
            ncur = inv
    return sum(1 for s in live
               if (inv if s == seat else invested[s]) >= ncur - EPS
               and room[s] - (inv if s == seat else invested[s]) > EPS)


def build(spot: Spot, cap: int = CAP, open_to: float = OPEN, mult: float = MULT,
          tier1: bool = False, behind_cap: int | None = None) -> Tree:
    """`tier1=True`: bowling's "open or jam" (`open3bet-design.md` Sec 6b) -- drop the flat call
    and the 3bet. Facing one raise, not all-in: fold or all-in only. Every other rule (cap, the
    unopened action set, facing-all-in) is unchanged, so this game is a strict subset of the same
    tree, built the same way, and the only ending types left are ALLFOLD / UNCONTESTED / SHOWDOWN
    -- no FLOP terminal is reachable, so no leaf model is consulted.
    """
    n = spot.n
    antes = spot.antes
    posted = spot.blinds
    forced = set(spot.forced)              # all-in by posting: never acts, always live
    if len(forced) > cap:
        raise ValueError(f"{len(forced)} seats are all-in by posting; the cap is {cap}")
    room = tuple(spot.stacks[s] - antes[s] for s in range(n))   # chips available beyond the ante

    nodes: list[Node] = []
    terminals: list[Terminal] = []
    seq = 0

    def in_for_price(invested, live, cur_bet) -> int:
        """Seats that would still hold cards if everyone left folded."""
        return sum(1 for s in live
                   if invested[s] >= cur_bet - EPS or invested[s] >= room[s] - EPS)

    def close(invested, live, raises) -> None:
        live = tuple(sorted(live))
        if len(live) <= 1:
            kind = ALLFOLD if raises == 0 else UNCONTESTED
        else:
            chips = sum(1 for s in live if room[s] - invested[s] > EPS)
            kind = SHOWDOWN if chips <= 1 else FLOP
        terminals.append(Terminal(len(terminals), kind, live, tuple(invested), (), raises))
        return len(terminals) - 1

    def rec(invested, live, cur_bet, raises, acted, aggressor, pos, path, own_last) -> None:
        nonlocal seq
        if len(live) <= 1:
            _finish(close(invested, live, raises), path)
            return
        seat = None
        for k in range(n):
            s = (pos + k) % n
            if s not in live or invested[s] >= room[s] - EPS:
                continue                                   # folded, or all-in: no decision
            if raises == 0 and invested[s] >= cur_bet - EPS:
                continue    # the BB in an unopened pot: it has matched and there is no limp to face
            if s not in acted or invested[s] < cur_bet - EPS:
                seat = s
                break
        if seat is None:
            _finish(close(invested, live, raises), path)
            return

        to_call = min(cur_bet, room[seat]) - invested[seat]
        facing_allin = aggressor is not None and invested[aggressor] >= room[aggressor] - EPS
        unopened = raises == 0

        if unopened:
            acts = [FOLD, RAISE, ALLIN]
        elif facing_allin or raises >= 2:
            acts = [FOLD, CALL, ALLIN] if not facing_allin else [FOLD, CALL]
        elif tier1:
            acts = [FOLD, ALLIN]
        else:
            acts = [FOLD, CALL, RAISE, ALLIN]

        # Cap: no room for another body in the pot, so the only legal action is to fold.
        if in_for_price(invested, live, cur_bet) >= cap and not (
                invested[seat] >= cur_bet - EPS or invested[seat] >= room[seat] - EPS):
            acts = [FOLD]

        # Cap reached: this seat has no decision at all, so make no node (as pushfold.floor does).
        if acts == [FOLD]:
            rec(invested, live - {seat}, cur_bet, raises, acted | {seat}, aggressor,
                (seat + 1) % n, path, own_last)
            return

        raise_to = 0.0
        if RAISE in acts:
            raise_to = min(room[seat], open_to if unopened else mult * cur_bet)
            if raise_to >= room[seat] - RAISE_GAP + EPS or raise_to <= cur_bet + EPS:
                acts = [a for a in acts if a != RAISE]
                raise_to = 0.0
        if ALLIN in acts and CALL in acts and room[seat] <= cur_bet + EPS:
            acts = [a for a in acts if a != ALLIN]   # calling all-in already is the all-in

        if behind_cap is not None:
            kept = [a for a in acts
                    if a == FOLD
                    or _behind_after(invested, live, cur_bet, raise_to, room, seat, a) <= behind_cap]
            if len(kept) <= 1 and (not kept or kept[0] == FOLD):
                rec(invested, live - {seat}, cur_bet, raises, acted | {seat}, aggressor,
                    (seat + 1) % n, path, own_last)     # forced fold: no node, as the cap rule does
                return
            acts = kept

        node = Node(len(nodes), seat, tuple(acts), tuple((nodes[i].seat, a) for i, a in path),
                    seq, own_last[seat], float(to_call), float(raise_to),
                    float(sum(invested) + sum(antes)), raises)
        nodes.append(node)
        seq += len(acts)

        for action in acts:
            inv = list(invested)
            nlive, ncur, nraises, nacted, nagg = set(live), cur_bet, raises, set(acted), aggressor
            if action == FOLD:
                nlive.discard(seat)
            elif action == CALL:
                inv[seat] = min(cur_bet, room[seat])
            elif action == RAISE:
                inv[seat] = raise_to
                ncur, nraises, nacted, nagg = raise_to, raises + 1, set(), seat
            else:
                inv[seat] = room[seat]
                if inv[seat] > cur_bet + EPS:
                    ncur, nraises, nacted, nagg = inv[seat], raises + 1, set(), seat
            nacted.add(seat)
            nown = own_last[:seat] + (node.index,) + own_last[seat + 1:]
            rec(tuple(inv), nlive, ncur, nraises, frozenset(nacted), nagg,
                (seat + 1) % n, path + ((node.index, action),), nown)

    def _finish(index: int, path) -> None:
        z = terminals[index]
        terminals[index] = dataclasses.replace(z, path=tuple(path))

    start_invested = tuple(posted)
    live = set(range(n))
    cur_bet = max(max(posted), 0.0)
    rec(start_invested, live, cur_bet, 0, frozenset(), None, 0, (), (-1,) * n)
    return Tree(spot, tuple(nodes), tuple(terminals), seq, cap)
