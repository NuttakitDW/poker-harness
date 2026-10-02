"""Large-field ICM for the all-streets game: every terminal outcome priced once, before solving.

Mid-tournament a table's players share the prizes with a field at other tables, so prize
equity needs the crowd recursion in ``pushfold.icm`` (exact Harville, but far too slow to run
at every terminal of every deal). A terminal's final stacks, though, depend only on who wins
each pot layer, so each (terminal, winners) pair is priced once here and the solver looks it
up. Ties are outcomes too, so chopped pots are priced exactly.

Layers are the terminal's pot levels (``FullTree.sidepot_*``). Their eligible masks shrink as
the level rises, so the winners are built from the top layer down: each lower layer's
winners are the top layer's, or players only it contains who beat them, or both tied.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from pushfold.icm import Payouts, value

from .fulltree import FullTree

ROUND = 1e-7       # final stacks closer than this price as one
CHUNK = 20_000     # stack vectors priced per batch (crowd recursion holds 2**seats copies)


@dataclasses.dataclass(frozen=True)
class OutcomeTable:
    start: np.ndarray    # (nodes + 1,) int64: node's outcome rows are start[node]:start[node + 1]
    winners: np.ndarray  # (rows, seats) int32: winner mask of each pot layer
    values: np.ndarray   # (rows, seats) float64: every seat's prize equity, in chips

    @classmethod
    def empty(cls, seats: int) -> OutcomeTable:
        return cls(np.zeros(0, dtype=np.int64), np.zeros((0, seats), dtype=np.int32),
                   np.zeros((0, seats), dtype=np.float64))


def _subsets(mask: int) -> list[int]:
    """Non-empty subsets of ``mask``."""
    out, sub = [], mask
    while sub:
        out.append(sub)
        sub = (sub - 1) & mask
    return out


def layer_outcomes(masks: tuple[int, ...]) -> list[tuple[int, ...]]:
    """Every possible winner mask per layer for these eligible masks (lowest level first)."""
    live = [i for i, mask in enumerate(masks) if mask]
    if not live:
        return [tuple(0 for _ in masks)]
    tops: list[list[int]] = [[]]   # partial results, innermost layer first
    inner = 0
    for i in reversed(live):
        fresh = masks[i] & ~inner
        grown = []
        for partial in tops:
            best = partial[-1] if partial else 0
            if best:
                grown.append(partial + [best])
            for extra in _subsets(fresh):
                grown.append(partial + [extra])
                if best:
                    grown.append(partial + [best | extra])
        tops = grown
        inner = masks[i]
    out = []
    for partial in tops:
        row = [0] * len(masks)
        for i, winners in zip(reversed(live), partial):
            row[i] = winners
        out.append(tuple(row))
    return out


def _shares(outcomes: list[tuple[int, ...]], seats: int) -> np.ndarray:
    """(outcomes, layers, seats): each seat's fraction of each layer."""
    share = np.zeros((len(outcomes), len(outcomes[0]), seats))
    for o, row in enumerate(outcomes):
        for layer, winners in enumerate(row):
            members = [s for s in range(seats) if winners >> s & 1]
            share[o, layer, members] = 1.0 / len(members) if members else 0.0
    return share


def build(tree: FullTree, payouts: Payouts) -> OutcomeTable:
    """Price every terminal outcome of ``tree`` with crowd ICM (values in chips)."""
    n = tree.seats
    start_stacks = tuple(float(x) for x in tree.start_stacks)
    payouts.check(n)
    terminals = np.flatnonzero(tree.actor < 0)
    counts = tree.sidepot_count[terminals].astype(np.int64)
    masks = tree.sidepot_eligible_mask[terminals].astype(np.int64)
    keys: dict[tuple[int, ...], list[int]] = {}
    for k, (count, row) in enumerate(zip(counts, masks)):
        keys.setdefault(tuple(int(m) for m in row[:count]), []).append(k)

    per_node = np.zeros(tree.node_count, dtype=np.int64)
    blocks: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []   # (nodes, winners, finals)
    for key, members in keys.items():
        nodes = terminals[members]
        outcomes = layer_outcomes(key) if key else [()]
        layers = len(key)
        win = np.zeros((len(outcomes), n), dtype=np.int32)
        if layers:
            win[:, :layers] = np.asarray(outcomes, dtype=np.int32)
            share = _shares(outcomes, n)
            finals = tree.behind[nodes][:, None, :] + np.einsum(
                "kl,ols->kos", tree.sidepot_amount[nodes][:, :layers], share)
        else:
            finals = np.repeat(tree.behind[nodes][:, None, :], 1, axis=1)
        per_node[nodes] = len(outcomes)
        blocks.append((nodes, win, finals))

    start = np.zeros(tree.node_count + 1, dtype=np.int64)
    np.cumsum(per_node, out=start[1:])
    rows = int(start[-1])
    winners = np.zeros((rows, n), dtype=np.int32)
    finals_all = np.zeros((rows, n))
    for nodes, win, finals in blocks:
        index = start[nodes][:, None] + np.arange(win.shape[0])[None, :]
        winners[index] = win[None, :, :]
        finals_all[index] = finals

    unique, inverse = np.unique(np.round(finals_all / ROUND) * ROUND, axis=0, return_inverse=True)
    priced = np.empty_like(unique)
    for lo in range(0, unique.shape[0], CHUNK):
        priced[lo:lo + CHUNK] = value(unique[lo:lo + CHUNK], start_stacks, payouts)
    return OutcomeTable(start=start, winners=winners, values=priced[inverse.reshape(-1)])
