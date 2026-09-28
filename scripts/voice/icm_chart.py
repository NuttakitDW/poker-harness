"""Live preflop ICM charts with fold, call, raise and all-in kept distinct."""

from __future__ import annotations

import dataclasses
import functools
import math
import os
import pathlib
import sys
import threading

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import preflop  # noqa: E402
import pushfold_chart  # noqa: E402
from icm_open import ENGINE_VERSION, floor3, solve3  # noqa: E402
from pushfold import hands, icm, oddsmaker  # noqa: E402
from pushfold.spot import Spot, SpotError  # noqa: E402

MIN_STACK = 3.0
MAX_STACK = 30.0
MAX_ITERS = 4000
TARGET = {2: 0.002, 3: 0.006, 4: 0.008, 5: 0.009, 6: 0.010,
          7: 0.012, 8: 0.014, 9: 0.015}
ACTION_CODES = {floor3.FOLD: "F", floor3.CALL: "C", floor3.RAISE: "R", floor3.ALLIN: "J"}
ACTION_KEYS = {floor3.FOLD: "fold", floor3.CALL: "call", floor3.RAISE: "raise",
               floor3.ALLIN: "allin"}
_SOLVE_LOCK = threading.Lock()


class IcmChartError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Solved:
    book: dict
    chart: dict
    note: str


def solve_seconds(env=os.environ) -> float:
    default = 25.0 if env.get("VERCEL") else 180.0
    try:
        value = float(env.get("ICM_SOLVE_SECONDS", default))
    except (TypeError, ValueError):
        return default
    cap = 25.0 if env.get("VERCEL") else 240.0
    return min(cap, value) if math.isfinite(value) and value > 0 else default


def applies(request: preflop.Request) -> bool:
    """ICM uses the full preflop model unless push/fold was explicitly requested."""
    wants_icm = (request.icm or request.payouts not in (None, ()) or request.stage_word is not None
                 or request.players_left is not None or request.left_pct is not None
                 or request.buy_in is not None or request.prize_pool is not None)
    return (request.payouts != () and not request.aof and request.game != "cash"
            and not request.explicit_pushfold
            and request.stack is not None and wants_icm)


def _players(request: preflop.Request) -> int:
    return pushfold_chart._players(request)


def _ante(request: preflop.Request) -> float:
    return pushfold_chart._ante(request)


def _spot(request: preflop.Request) -> Spot:
    stack = float(request.stack)
    if request.unsupported_history:
        raise IcmChartError(f"{request.unsupported_history} are outside this preflop model")
    if request.seat_stacks:
        values = {float(value) for _, value in request.seat_stacks}
        if len(values) > 1:
            raise IcmChartError("unequal stacks are not supported; give one effective stack")
        stack = values.pop()
    if not MIN_STACK <= stack <= MAX_STACK:
        raise IcmChartError(f"effective stack must be {MIN_STACK:g}-{MAX_STACK:g}bb")
    return pushfold_chart._spot(stack, _players(request), _ante(request),
                                pushfold_chart._mode(request))


def _sizes(request: preflop.Request) -> tuple[float, float]:
    open_to = float(request.open_size or floor3.OPEN)
    threebet_to = float(request.threebet_size or floor3.MULT * open_to)
    if not math.isfinite(open_to) or not math.isfinite(threebet_to):
        raise IcmChartError("raise sizes must be finite numbers")
    if request.open_size is not None and not 2.0 <= open_to < float(request.stack) - floor3.RAISE_GAP:
        raise IcmChartError("open size must leave at least 1bb behind")
    minimum_threebet = 2 * open_to - 1.0
    if request.threebet_size is not None and not minimum_threebet <= threebet_to < float(request.stack):
        raise IcmChartError(f"3-bet size must be at least {minimum_threebet:g}bb and below all-in")
    return open_to, threebet_to / open_to


def problem(request: preflop.Request) -> str | None:
    try:
        table = _spot(request)
        if len(set(round(s - a, 9) for s, a in zip(table.stacks, table.antes))) != 1:
            raise IcmChartError("only equal post-ante stacks are supported")
        chosen = pushfold_chart.payouts(request)
        if chosen is None:
            raise IcmChartError("ICM needs a payout structure")
        chosen.check(table.n)
        open_to, mult = _sizes(request)
        _requested_node(floor3.build(table, cap=3, tier15=True,
                                     open_to=open_to, mult=mult), request)
    except (IcmChartError, SpotError, icm.PayoutError, ValueError) as error:
        return str(error)
    return None


def _seat(names: tuple[str, ...], name: str | None) -> str | None:
    return "SB" if len(names) == 2 and name == "BTN" else name


def _label(names: tuple[str, ...], name: str | None) -> str | None:
    return "BTN/SB" if len(names) == 2 and name == "SB" else name


def _requested_events(tree: floor3.Tree, request: preflop.Request) -> tuple[tuple[int, int], ...]:
    names = tree.spot.names
    hero = _seat(names, request.hero)
    villain = _seat(names, request.villain)
    if hero not in names:
        raise IcmChartError(f"{request.hero or 'hero seat'} is not at this {len(names)}-handed table")
    if request.scenario not in (None, "RFI", "All-In", "3-Bet"):
        raise IcmChartError("this action history is not supported; ask for unopened, facing an open, or facing a shove")
    if request.scenario == "All-In" or request.shovers:
        ordered = [_seat(names, s) for s in request.shovers] or [villain]
        return tuple((names.index(name), floor3.ALLIN if index == 0 else floor3.CALL)
                     for index, name in enumerate(ordered))
    if request.scenario == "3-Bet":
        if villain not in names:
            raise IcmChartError("name the seat that 3-bet")
        return ((names.index(hero), floor3.RAISE), (names.index(villain), floor3.RAISE))
    elif villain:
        if names.index(villain) >= names.index(hero):
            raise IcmChartError(f"{villain} cannot open before {hero}")
        return ((names.index(villain), floor3.RAISE),)
    return ()


def _requested_node(tree: floor3.Tree, request: preflop.Request) -> floor3.Node:
    events = _requested_events(tree, request)
    hero = _seat(tree.spot.names, request.hero)
    found = [node for node in tree.nodes
             if node.seat == tree.spot.names.index(hero)
             and tuple(event for event in node.history if event[1] != floor3.FOLD) == events]
    if len(found) != 1:
        raise IcmChartError("that preflop action history has no decision in this model")
    return found[0]


def _payout_key(chosen: icm.Payouts) -> tuple:
    return chosen.prizes, chosen.field, chosen.crowd, chosen.crowd_stack


@functools.lru_cache(maxsize=24)
def _solve(stacks: tuple[float, ...], ante: float, ante_mode: str,
           payout_key: tuple, open_to: float, mult: float, budget: float
           ) -> tuple[floor3.Tree, np.ndarray, tuple[int, float], float]:
    missing = [path.name for path in (oddsmaker.E2_FILE, oddsmaker.E3_FILE) if not path.exists()]
    if missing:
        raise IcmChartError("required precomputed equity tables are unavailable: " + ", ".join(missing))
    table = Spot(stacks=stacks, ante=ante, ante_mode=ante_mode)
    prizes, field, crowd, crowd_stack = payout_key
    chosen = icm.Payouts(prizes, field, crowd, crowd_stack)
    tree = floor3.build(table, cap=3, tier15=True, open_to=open_to, mult=mult)
    if tree.counts().get(floor3.FLOP):
        raise IcmChartError("this tree reaches unsupported postflop leaves")
    result = solve3.solve_icm(tree, chosen, TARGET[table.n], check_every=10,
                              max_iters=MAX_ITERS, max_seconds=budget)
    if not result.history or not result.converged:
        achieved = result.history[-1][1] if result.history else math.inf
        raise IcmChartError(f"live solve needs more than {budget:g}s for this table "
                            f"(best-response gain {achieved:.4g})")
    sigma = result.st.average()
    if not np.isfinite(sigma).all():
        raise IcmChartError("solver returned non-finite strategy frequencies")
    for node in tree.nodes:
        rows = sigma[node.index, :, :len(node.actions)]
        if np.any(rows < -1e-9) or not np.allclose(rows.sum(axis=1), 1.0, atol=1e-6):
            raise IcmChartError("solver returned unnormalised strategy frequencies")
    return tree, sigma, result.history[-1], result.seconds


def _chart(tree: floor3.Tree, sigma: np.ndarray, node: floor3.Node,
           request: preflop.Request, last: tuple[int, float], seconds: float) -> Solved:
    order = list(hands.CLASSES)
    by_hand = {hand: sigma[node.index, i, :len(node.actions)] for i, hand in enumerate(order)}
    codes, mixed = [], {}
    for hand in order:
        values = by_hand[hand]
        primary = node.actions[int(np.argmax(values))]
        codes.append(ACTION_CODES[primary])
        mixed[hand] = {ACTION_KEYS[action]: float(value)
                       for action, value in zip(node.actions, values)}
    names = tree.spot.names
    hero = names[node.seat]
    aggressors = [names[s] for s, action in node.history
                  if s != node.seat and action in (floor3.RAISE, floor3.ALLIN)]
    action_names = {}
    for action, label in zip(node.actions, node.labels):
        key = ACTION_KEYS[action]
        action_names[key] = label.replace("allin", "all-in")
    model = pushfold_chart._model(request)
    chosen = pushfold_chart.payouts(request)
    book = {"game": "tournament", "title": "Live preflop ICM solver",
            "hand_order": order}
    context = "Unopened" if node.raises == 0 else "Facing " + " + ".join(
        _label(names, seat) for seat in aggressors)
    effective_stack = tree.spot.stacks[node.seat] - tree.spot.antes[node.seat]
    chart = {"stack": effective_stack, "section": "SOLVER", "page": None,
             "hero": _label(names, hero),
             "villain": "+".join(_label(names, seat) for seat in aggressors) or None,
             "scenario": context, "actions": "".join(codes), "mixed": mixed,
             "names": action_names,
             "metadata": {"engine_version": ENGINE_VERSION, "model": "preflop ICM",
                          "cap": 3, "stacks": list(tree.spot.stacks),
                          "blinds": [tree.spot.sb, tree.spot.bb],
                          "ante": tree.spot.ante, "ante_mode": tree.spot.ante_mode,
                          "payouts": list(chosen.prizes), "field": list(chosen.field),
                          "crowd": chosen.crowd, "crowd_stack": chosen.crowd_stack,
                          "open_to": _sizes(request)[0], "raise_multiplier": _sizes(request)[1],
                          "target": TARGET[tree.spot.n], "achieved": last[1],
                          "iterations": last[0], "converged": True}}
    table = "heads-up" if tree.spot.n == 2 else f"{tree.spot.n}-handed"
    ante = pushfold_chart._ante_words(request)
    note = (f"{model}; {table}; equal {effective_stack:g}bb stacks after ante; {ante}; zero rake; "
            f"preflop actions exclude limps and flat calls, open {_sizes(request)[0]:g}bb, 3-bet "
            f"{_sizes(request)[1]:g}x, cap 3; target {TARGET[tree.spot.n]:g}, converged "
            f"best-response gain {last[1]:.4g} ICM "
            f"chips/hand in {last[0]} iterations ({seconds:.1f}s). Multiway hand-strength "
            "pricing is an approximation; no postflop leaf was used.")
    return Solved(book, chart, note)


def solved(request: preflop.Request) -> Solved:
    issue = problem(request)
    if issue:
        raise IcmChartError(issue)
    table = _spot(request)
    chosen = pushfold_chart.payouts(request)
    open_to, mult = _sizes(request)
    if not _SOLVE_LOCK.acquire(timeout=0.1):
        raise IcmChartError("another live ICM solve is running; try this spot again shortly")
    try:
        tree, sigma, last, seconds = _solve(table.stacks, table.ante, table.ante_mode,
                                            _payout_key(chosen), open_to, mult,
                                            solve_seconds())
    finally:
        _SOLVE_LOCK.release()
    return _chart(tree, sigma, _requested_node(tree, request), request, last, seconds)
