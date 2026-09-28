"""Sequential exact best response for a preflop tree where a seat acts more than once.

Why this file exists
--------------------
`pushfold/auditor.py` computes, for each seat, `sum over its nodes of PRIOR @ (max_a cfv - now)`.
That is a best-response gain only because in push/fold each seat acts at most once on any
path, so its nodes sit in disjoint subtrees and the per-node maxima are independent. In an
open/3bet tree a seat acts repeatedly and its later nodes are reached only through its own
earlier choices, so the same sum is the sum of immediate counterfactual regrets, which is an
upper bound on the best-response gain (Zinkevich, Johanson, Bowling, Piccione, *Regret
Minimization in Games with Incomplete Information*, NIPS 2007, Theorem 3 / the immediate-regret
lemma), not the gain itself.

What is here
------------
* `Game`: an explicit tree. Nodes carry the acting seat and a child per action; endings carry
  who is still alive and a `cashier.Settlement`. Ragged action counts are allowed.
* `path_columns`: per ending, per seat, the product of that seat's own action probabilities
  along the path, as a 169-vector. The product is taken *inside* the seat's hand class, which
  is the step a reach *scalar* cannot do once a seat acts twice.
* `chip_values` / `icm_values`: `U[seat, h, ending]`, the counterfactual value of an ending to a
  seat: chance and every *other* seat's reach folded in, the seat's own action probabilities
  left out. This is the quantity `pushfold.pricer.values` computes but collapses onto one
  (node, action) column per ending.
* `audit`: exact sequential best response by backward induction over the public tree (max at
  the seat's own nodes, sum elsewhere), and `shortcut_gain`, the old auditor's quantity, for
  comparison.

Exactness. Within the model game this is an exact best response: the tree is the whole game,
the seat's information set is (public history, hand class), the max is taken per information
set, and the walk is full-width over all 169 classes. It is exact *in the model*, and the model
is an abstraction: 169 classes, independent opponent priors at 3+ seats (`pushfold/pricer.py`),
Monte Carlo 3-way tables `eq3`/`pw` (2000 samples/triple, `pushfold/oddsmaker.py`), at most 3
players to a showdown, and whatever leaf model prices an ending that sees a flop. Against the
real game it is neither an upper nor a lower bound; it is a different game's number.

Independence. The value machinery here was written from the game definition (`cashier.settle`,
`oddsmaker` tables, `icm.value`) rather than by reusing `pricer.py` / `icm_pricer.py`, so that
agreement with `pushfold.auditor` on push/fold trees is evidence about both.

Written by the Johanson persona (swarm agent).
"""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np

from pushfold import cashier, hands, icm, oddsmaker
from pushfold.floor import IDLE, JAM, Tree as FloorTree
from pushfold.spot import Spot

N = len(hands.CLASSES)
PRIOR = hands.PRIOR
_AXES = ((0, 1, 2), (1, 0, 2), (2, 0, 1))   # free hand's finishing place moved to axis 0


# ---------------------------------------------------------------- the tree


@dataclasses.dataclass(frozen=True)
class Ending:
    index: int
    alive: tuple[int, ...]          # seats still holding cards (1, 2 or 3)
    settle: cashier.Settlement      # fixed part + contested layers, in chips
    label: str = ""
    pot: float = 0.0                # total chips in the middle, for the "% of pot" denominator


@dataclasses.dataclass(frozen=True)
class Node:
    index: int
    seat: int
    children: tuple[int, ...]       # per action: >= 0 a node index, < 0 means ~ending index
    labels: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Game:
    spot: Spot
    nodes: tuple[Node, ...]
    endings: tuple[Ending, ...]
    root: int                       # node index, or ~ending index if nobody acts

    @property
    def width(self) -> int:
        return max((len(n.children) for n in self.nodes), default=1)

    def nodes_of(self, seat: int) -> list[Node]:
        return [n for n in self.nodes if n.seat == seat]

    def uniform(self) -> np.ndarray:
        """(nodes, 169, width) uniform strategy over each node's legal actions, 0 elsewhere."""
        sigma = np.zeros((len(self.nodes), N, self.width))
        for node in self.nodes:
            sigma[node.index, :, :len(node.children)] = 1.0 / len(node.children)
        return sigma


def from_floor(tree: FloorTree) -> Game:
    """Adapter: today's push/fold tree as a Game, so the two auditors can be compared."""
    ending_of: dict[tuple[int, ...], int] = {}
    endings: list[Ending] = []
    for z in tree.terminals:
        pot = float(cashier.contributions(tree.spot, z.jammers).sum() + sum(tree.spot.antes))
        endings.append(Ending(len(endings), z.alive, cashier.settle(tree.spot, z.jammers),
                              "".join("fjJ"[a] if a != IDLE else "-" for a in z.actions), pot))
        ending_of[z.actions] = endings[-1].index
    # A floor node is identified by its history; its children are histories one action longer.
    by_history = {n.history: n for n in tree.nodes}

    def resolve(history: tuple[int, ...]) -> int:
        if history in by_history:
            return by_history[history].index
        # Otherwise the rest of the table is forced: find the unique ending extending history.
        for actions, index in ending_of.items():
            if actions[:len(history)] == history:
                return ~index
        raise KeyError(history)

    nodes = tuple(Node(n.index, n.seat, tuple(resolve(n.history + (a,)) for a in (0, 1)),
                       n.labels) for n in tree.nodes)
    root = resolve(()) if tree.nodes else ~0
    return Game(tree.spot, nodes, tuple(endings), root)


# ---------------------------------------------------------------- reach


def path_columns(game: Game, sigma: np.ndarray) -> np.ndarray:
    """(endings, seats, 169): each seat's own action probabilities along the path, per class."""
    out = np.ones((len(game.endings), game.spot.n, N))

    def walk(index: int, acc: np.ndarray) -> None:
        if index < 0:
            out[~index] = acc
            return
        node = game.nodes[index]
        for action, child in enumerate(node.children):
            nxt = acc.copy()
            nxt[node.seat] = acc[node.seat] * sigma[node.index, :, action]
            walk(child, nxt)

    walk(game.root, np.ones((game.spot.n, N)))
    return out


def _opponent_model(n: int) -> np.ndarray:
    """O[h, g]: chance an opponent holds g when I hold h. Same choice as pushfold/pricer.py."""
    return hands.M if n == 2 else np.tile(PRIOR, (N, 1))


# ---------------------------------------------------------------- values


@dataclasses.dataclass(frozen=True)
class Leaf:
    """Showdown tables. Swap these to change the leaf model without touching the audit."""
    e2: np.ndarray
    eq3: np.ndarray
    pw: np.ndarray
    orders: np.ndarray


def tables() -> Leaf:
    t = oddsmaker.three_way()
    return Leaf(oddsmaker.two_way(), t.eq3, t.pw, oddsmaker.orders())


def chip_values(game: Game, paths: np.ndarray, leaf: Leaf | None = None) -> np.ndarray:
    """U[seat, 169, ending] in chips (bb): counterfactual value, own actions excluded."""
    leaf = leaf or tables()
    n = game.spot.n
    O = _opponent_model(n)
    U = np.zeros((n, N, len(game.endings)))
    for z in game.endings:
        c = paths[z.index]                       # (seats, 169) own-action products
        R = O @ c.T                              # R[h, j] = reach of seat j given I hold h
        for seat in range(n):
            others = [j for j in range(n) if j != seat]

            def rest(skip) -> np.ndarray:
                keep = [j for j in others if j not in skip]
                return R[:, keep].prod(axis=1) if keep else np.ones(N)

            u = z.settle.fixed[seat] * rest(())
            for layer in z.settle.layers:
                if seat not in layer.eligible:
                    continue                      # chip EV: an ineligible layer is in `fixed`
                rivals = [j for j in layer.eligible if j != seat]
                if len(rivals) == 2:
                    a, b = rivals
                    share = np.einsum("hgk,g,k->h", leaf.eq3, PRIOR * c[a], PRIOR * c[b])
                    u = u + layer.amount * share * rest(rivals)
                elif len(z.alive) == 3:
                    dead = next(j for j in z.alive if j not in layer.eligible)
                    share = np.einsum("hgk,g,k->h", leaf.pw, PRIOR * c[rivals[0]], PRIOR * c[dead])
                    u = u + layer.amount * share * rest([rivals[0], dead])
                else:
                    share = (O * leaf.e2) @ c[rivals[0]]
                    u = u + layer.amount * share * rest(rivals)
            U[seat, :, z.index] = u
    return U


def _worth(game: Game, payouts: icm.Payouts) -> list[dict[tuple[int, ...], np.ndarray]]:
    """Per ending: finishing order of the live seats -> ICM chips won or lost, per seat."""
    spot = game.spot
    keys, finals = [], []
    for z in game.endings:
        for order in itertools.permutations(z.alive):
            net = z.settle.net_for({s: place + 1 for place, s in enumerate(order)})
            keys.append((z.index, order))
            finals.append(np.array(spot.stacks) + net)
    before = icm.value(np.array([spot.stacks]), spot.stacks, payouts)[0]
    rows = icm.value(np.array(finals), spot.stacks, payouts) - before
    out: list[dict] = [{} for _ in game.endings]
    for (index, order), row in zip(keys, rows):
        out[index][order] = row
    return out


def icm_values(game: Game, paths: np.ndarray, payouts: icm.Payouts,
               leaf: Leaf | None = None) -> np.ndarray:
    """U[seat, 169, ending] in ICM chips: counterfactual value, own actions excluded."""
    leaf = leaf or tables()
    n = game.spot.n
    payouts.check(n)
    O = _opponent_model(n)
    worth = _worth(game, payouts)
    U = np.zeros((n, N, len(game.endings)))
    for z in game.endings:
        c = paths[z.index]
        R = O @ c.T
        for seat in range(n):
            others = [j for j in range(n) if j != seat]

            def rest(skip) -> np.ndarray:
                keep = [j for j in others if j not in skip]
                return R[:, keep].prod(axis=1) if keep else np.ones(N)

            w = worth[z.index]
            if len(z.alive) == 1:
                u = w[z.alive][seat] * rest(())
            elif len(z.alive) == 2:
                a, b = z.alive
                if seat in z.alive:
                    rival = b if seat == a else a
                    lose, win = w[(rival, seat)][seat], w[(seat, rival)][seat]
                    beat = (O * leaf.e2) @ c[rival]
                    u = lose * rest(()) + (win - lose) * beat * rest([rival])
                else:
                    b_wins, a_wins = w[(b, a)][seat], w[(a, b)][seat]
                    # `beats` already carries a's and b's reach, so it pairs with rest(alive);
                    # the constant term does not, so it pairs with the full product.
                    beats = float((PRIOR * c[a]) @ (leaf.e2 * PRIOR[None, :]) @ c[b])
                    u = b_wins * rest(()) + (a_wins - b_wins) * beats * rest(z.alive)
            else:
                free = seat if seat in z.alive else z.alive[0]
                u = np.zeros(N)
                for order, row in w.items():
                    if row[seat] == 0.0:
                        continue
                    y, x = (s for s in order if s != free)
                    axes = _AXES[order.index(free)]
                    tensor = leaf.orders.transpose(axes)
                    term = np.einsum("hgk,g,k->h", tensor, PRIOR * c[y], PRIOR * c[x])
                    if seat in z.alive:
                        u = u + row[seat] * term * rest(z.alive)
                    else:
                        u = u + row[seat] * float((PRIOR * c[free]) @ term) * rest(z.alive)
            U[seat, :, z.index] = u
    return U


def values(game: Game, sigma: np.ndarray, payouts: icm.Payouts | None = None,
           leaf: Leaf | None = None) -> np.ndarray:
    paths = path_columns(game, sigma)
    return (chip_values(game, paths, leaf) if payouts is None
            else icm_values(game, paths, payouts, leaf))


# ---------------------------------------------------------------- the audit


def _walk(game: Game, u: np.ndarray, sigma: np.ndarray, seat: int, best: bool) -> np.ndarray:
    """Backward induction. `best`: max at `seat`'s nodes. Otherwise follow sigma there."""
    def go(index: int) -> np.ndarray:
        if index < 0:
            return u[:, ~index]
        node = game.nodes[index]
        kids = np.stack([go(child) for child in node.children], axis=1)   # (169, actions)
        if node.seat != seat:
            return kids.sum(axis=1)
        if best:
            return kids.max(axis=1)
        return (sigma[node.index, :, :kids.shape[1]] * kids).sum(axis=1)
    return go(game.root)


@dataclasses.dataclass(frozen=True)
class Report:
    ev: np.ndarray           # per seat, chips or ICM chips per hand
    gain: np.ndarray         # exact sequential best-response gain per seat
    shortcut: np.ndarray     # what pushfold/auditor.py's formula gives on this tree
    exploitability: float    # max over seats, the convention pushfold/auditor.py uses
    nashconv: float          # sum over seats
    unit: str

    @property
    def mean(self) -> float:
        return float(self.gain.mean())


def audit(game: Game, sigma: np.ndarray, payouts: icm.Payouts | None = None,
          leaf: Leaf | None = None, U: np.ndarray | None = None) -> Report:
    U = values(game, sigma, payouts, leaf) if U is None else U
    ev, gain, shortcut = [], [], []
    for seat in range(game.spot.n):
        u = U[seat]
        now = _walk(game, u, sigma, seat, best=False)
        best = _walk(game, u, sigma, seat, best=True)
        ev.append(float(PRIOR @ now))
        gain.append(float(PRIOR @ (best - now)))
        shortcut.append(shortcut_gain(game, u, sigma, seat))
    gain = np.array(gain)
    return Report(np.array(ev), gain, np.array(shortcut), float(gain.max()), float(gain.sum()),
                  "ICM chips/hand" if payouts is not None else "bb/hand")


def shortcut_gain(game: Game, u: np.ndarray, sigma: np.ndarray, seat: int) -> float:
    """`pushfold/auditor.py`'s quantity: sum over the seat's nodes of the local max gain.

    = the sum of immediate counterfactual regrets. Equal to the best-response gain when the
    seat acts at most once per path; an upper bound on it otherwise.
    """
    cache: dict[int, np.ndarray] = {}

    def go(index: int) -> np.ndarray:
        if index < 0:
            return u[:, ~index]
        node = game.nodes[index]
        kids = np.stack([go(child) for child in node.children], axis=1)
        cache[node.index] = kids
        if node.seat != seat:
            return kids.sum(axis=1)
        return (sigma[node.index, :, :kids.shape[1]] * kids).sum(axis=1)

    go(game.root)
    total = 0.0
    for node in game.nodes_of(seat):
        kids = cache[node.index]
        now = (sigma[node.index, :, :kids.shape[1]] * kids).sum(axis=1)
        total += float(PRIOR @ (kids.max(axis=1) - now))
    return total


# ---------------------------------------------------------------- units


def initial_pot(spot: Spot) -> float:
    """Chips in the middle before anyone acts: the blinds and antes."""
    return float(sum(spot.blinds) + sum(spot.antes))


def as_pct_of_pot(gain: float, spot: Spot) -> float:
    """Gain as a percentage of the pot BEFORE the first action. State which denominator."""
    return 100.0 * gain / initial_pot(spot)


def reach_probability(game: Game, sigma: np.ndarray) -> np.ndarray:
    """(endings,) chance each ending is reached under sigma, averaged over the deal."""
    paths = path_columns(game, sigma)
    n = game.spot.n
    out = np.zeros(len(game.endings))
    for z in game.endings:
        c = paths[z.index]
        if n == 2:
            out[z.index] = float((PRIOR * c[0]) @ (hands.M @ c[1]))
        else:
            out[z.index] = float(np.prod([PRIOR @ c[j] for j in range(n)]))
    return out


def average_pot(game: Game, sigma: np.ndarray) -> float:
    """Reach-weighted final pot under sigma. The other defensible % of pot denominator."""
    reach = reach_probability(game, sigma)
    return float(reach @ np.array([z.pot for z in game.endings]) / max(reach.sum(), 1e-12))
