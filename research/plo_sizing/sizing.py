"""One-day experiment: which preflop open and 3-bet sizes earn the most under ICM?

The production engine has one raise size per decision (pot). Rather than change it, this
script swaps the preflop raise rule through a ``PLOState`` subclass and solves the same spot
once per size with the unchanged kernels. A size is scored by what it earns the player who
chooses it, at the decision where it is chosen:

* open size  -> each seat's value at its first-in decision (everyone before folded);
* 3-bet size -> the defender's value facing one open (players in between folded).

Values come from the solved average strategy, sampled hand by hand (hero's cards uniform,
everyone else's path weighted by the strategy), so trees with different sizes are compared at
the same decision. Each arm runs with two seeds; a difference counts only if it beats the
seed-to-seed gap.

    .venv/bin/python research/plo_sizing/sizing.py --out tmp/plo_sizing
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from functools import lru_cache
from pathlib import Path

import numba
import numpy as np
from numba import njit, prange

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "final_table"))

import progress  # noqa: E402

from plo_icm.game import EPS, Action, PLOState  # noqa: E402
from plo_premium_proof import mtticm  # noqa: E402
from plo_premium_proof.finaltable import FinalTableSpec, export_result  # noqa: E402
from plo_premium_proof.fullkernels import (  # noqa: E402
    DISTRIBUTION_SIZE,
    _average_action,
    _bucket,
    _reset_deal,
    _utility,
    no_outcomes,
    train_full,
)
from plo_premium_proof.fulltree import FullTree, FullTreeConfig  # noqa: E402
from plo_premium_proof.kernels import _deal, _situation  # noqa: E402
from plo_premium_proof.solve import thread_seeds  # noqa: E402
from plo_premium_proof.tables import HandTables, comb_table, five_card_ranks  # noqa: E402

POT = 0.0          # open_x value meaning "pot-sized open"
MONSTER = ((1531.94, 1136.36, 842.99, 625.36, 463.91, 344.15, 255.30, 178.18) + (146.48,) * 2
           + (120.41,) * 3 + (98.99,) * 4 + (81.38,) * 7 + (66.90,) * 10 + (55.0,) * 17)
JOBS = ROOT / "tmp" / "final_table" / "jobs"
BATCH = ROOT / "tmp" / "final_table" / "batch.json"


# ---------------------------------------------------------------- betting rule

def _preflop_raises(state: PLOState) -> int:
    return sum(1 for h in state.history if h.startswith("0:") and h.split(":")[2] in ("pot", "raise_2bb"))


@lru_cache(maxsize=None)
def sized_state(open_x: float, three_f: float) -> type[PLOState]:
    """PLOState whose preflop 'pot' action raises to ``open_x`` BB first in (0 = pot) and,
    facing one raise, raises by ``three_f`` of a pot raise. Later raises stay pot-sized."""

    class Sized(PLOState):
        OPEN_X = open_x
        THREE_F = three_f

        def action_amount(self, action: Action) -> float:
            pot_amount = super().action_amount(action)
            if action != Action.POT or self.street != 0:
                return pot_amount
            seat = self.actor
            call = self._call_size(seat)
            pot_target = self.street_put[seat] + pot_amount
            raises = _preflop_raises(self)
            if raises == 0 and self.current_bet <= self.big_blind + EPS and self.OPEN_X > 0:
                target = self.OPEN_X * self.big_blind
            elif raises == 1 and self.THREE_F < 1.0:
                pot_raise = pot_target - self.current_bet
                target = self.current_bet + max(self.min_raise, self.THREE_F * pot_raise)
            else:
                return pot_amount
            target = min(target, pot_target)
            return min(self.behind[seat], max(call, target - self.street_put[seat]))

    Sized.__name__ = f"Sized_{open_x:g}_{three_f:g}"
    return Sized


@dataclasses.dataclass(frozen=True)
class SizedConfig(FullTreeConfig):
    open_x: float = POT
    three_f: float = 1.0

    def root(self) -> PLOState:
        return sized_state(self.open_x, self.three_f).new(
            self.seat_stacks, sb=0.5, bb=1.0, ante=self.ante_bb, ante_mode=self.ante_mode,
            opening_raise_mode="pot_only")


@dataclasses.dataclass(frozen=True)
class SizedSpec(FinalTableSpec):
    open_x: float = POT
    three_f: float = 1.0

    def tree_config(self) -> SizedConfig:
        base = super().tree_config()
        return SizedConfig(**{f.name: getattr(base, f.name) for f in dataclasses.fields(FullTreeConfig)},
                           open_x=self.open_x, three_f=self.three_f)


def size_name(open_x: float, three_f: float) -> str:
    opener = "pot" if open_x == POT else f"{open_x:g}x"
    three = "pot" if three_f >= 1.0 else f"{three_f:g}pot"
    return f"open {opener} / 3bet {three}"


# ---------------------------------------------------------------- evaluation kernel

@njit(cache=True)  # pragma: no cover - compiled native code
def _probability(strategy_sum: np.ndarray, row: int, count: int, slot: int) -> float:
    total = 0.0
    for a in range(count):
        total += strategy_sum[row, a]
    return strategy_sum[row, slot] / total if total > 0.0 else 1.0 / count


@njit(parallel=True)  # pragma: no cover - compiled native code
def node_moments(
    task_cards: np.ndarray, task_seed: np.ndarray, samples: int, hero: int, root: int,
    prefix_nodes: np.ndarray, prefix_slots: np.ndarray, bucket_of: np.ndarray, rank5: np.ndarray,
    comb: np.ndarray, strategy_sum: np.ndarray, actor: np.ndarray, street: np.ndarray,
    decision_index: np.ndarray, row_start: np.ndarray, children: np.ndarray, action_count: np.ndarray,
    behind: np.ndarray, sidepot_count: np.ndarray, sidepot_amount: np.ndarray,
    sidepot_eligible_mask: np.ndarray, stacks: np.ndarray, payouts: np.ndarray, outcome_start: np.ndarray,
    outcome_winners: np.ndarray, outcome_values: np.ndarray, moments: np.ndarray,
) -> None:
    """Per task (hero hand): moments[t, a, 0] = sum z*u after root action a, moments[t, 3, 0] =
    sum z, z = probability the other players took the prefix actions with their dealt hands."""
    seats = behind.shape[1]
    for task in prange(task_cards.shape[0]):
        state = task_seed[task:task + 1].copy()
        hero_cards = task_cards[task]
        hands = np.empty((seats, 4), dtype=np.int64)
        board = np.empty(5, dtype=np.int64)
        preflop = np.empty(seats, dtype=np.int64)
        ranks = np.empty(seats, dtype=np.int64)
        buckets = np.empty((4, seats), dtype=np.int64)
        scratch = np.empty(seats + 2 * (1 << seats), dtype=np.float64)
        distributions = np.empty((4, DISTRIBUTION_SIZE), dtype=np.int64)
        counts = np.zeros(4, dtype=np.int64)
        count_root = action_count[root]
        for _ in range(samples):
            _deal(state, hero, hero_cards, hands, board)
            _situation(hands, board, bucket_of, rank5, comb, preflop, ranks)
            _reset_deal(buckets, counts, preflop)
            z = 1.0
            for k in range(prefix_nodes.size):
                node = prefix_nodes[k]
                z *= _probability(strategy_sum, row_start[decision_index[node]] + preflop[actor[node]],
                                  action_count[node], prefix_slots[k])
            moments[task, 3, 0] += z
            if z <= 0.0:
                continue
            for action in range(count_root):
                node = children[root, action]
                while actor[node] >= 0:
                    seat = actor[node]
                    bucket = _bucket(street[node], seat, hands, board, buckets, distributions, counts, rank5, comb)
                    node = children[node, _average_action(strategy_sum, row_start[decision_index[node]] + bucket,
                                                          action_count[node], state)]
                moments[task, action, 0] += z * _utility(
                    node, hero, stacks, behind, sidepot_count, sidepot_amount, sidepot_eligible_mask, ranks,
                    payouts, scratch, outcome_start, outcome_winners, outcome_values)


def _child_with(tree: FullTree, node: int, action_id: int) -> tuple[int, int]:
    for slot in range(int(tree.action_count[node])):
        if int(tree.action_ids[node, slot]) == action_id:
            return int(tree.children[node, slot]), slot
    raise LookupError(f"node {node} has no action {action_id}")


FOLD, CALL, RAISE = 0, 2, 3


def facing_open(tree: FullTree, opener: int, defender: int) -> tuple[int, list[int], list[int]]:
    """Defender's node after ``opener`` opened and everyone else before the defender folded."""
    nodes, slots = [], []
    node = 0
    while int(tree.actor[node]) != opener:
        nodes.append(node)
        node, slot = _child_with(tree, node, FOLD)
        slots.append(slot)
    nodes.append(node)
    node, slot = _child_with(tree, node, RAISE)
    slots.append(slot)
    while int(tree.actor[node]) != defender:
        nodes.append(node)
        node, slot = _child_with(tree, node, FOLD)
        slots.append(slot)
    return node, nodes, slots


def first_in(tree: FullTree, seat: int) -> tuple[int, list[int], list[int]]:
    nodes, slots, node = [], [], 0
    while int(tree.actor[node]) != seat:
        nodes.append(node)
        node, slot = _child_with(tree, node, FOLD)
        slots.append(slot)
    return node, nodes, slots


def node_value(tree, strategy_sum, tables, rank5, comb, payoff, root, prefix_nodes, prefix_slots,
               *, hands: int, samples: int, seed: int) -> dict:
    """The actor's value at ``root`` (hero hands uniform, others weighted by reaching it)."""
    hero = int(tree.actor[root])
    rng = np.random.default_rng(seed)
    cards = np.stack([rng.choice(52, size=4, replace=False) for _ in range(hands)]).astype(np.int64)
    moments = np.zeros((hands, 4, 1))
    payouts, start, winners, values = payoff
    node_moments(cards, thread_seeds(seed, hands), samples, hero, root, np.asarray(prefix_nodes, dtype=np.int64),
                 np.asarray(prefix_slots, dtype=np.int64), tables.bucket_of, rank5, comb, strategy_sum, tree.actor,
                 tree.street, tree.decision_index, tree.row_start, tree.children, tree.action_count, tree.behind,
                 tree.sidepot_count, tree.sidepot_amount, tree.sidepot_eligible_mask, tree.start_stacks, payouts,
                 start, winners, values, moments)
    count = int(tree.action_count[root])
    from plo_premium_proof.preflop_chart import colex_index
    rows = tree.row_start[tree.decision_index[root]] + np.asarray(
        [tables.bucket_of[colex_index(tuple(sorted(int(c) for c in hand)))] for hand in cards])
    mix = strategy_sum[rows, :count].astype(np.float64)
    mix = np.where(mix.sum(1, keepdims=True) > 0, mix / np.maximum(mix.sum(1, keepdims=True), 1e-300), 1 / count)
    z = moments[:, 3, 0]
    y = (mix * moments[:, :count, 0]).sum(1)
    per_hand = np.divide(y, z, out=np.zeros_like(y), where=z > 0)
    weight = z / z.sum()
    value = float((weight * per_hand).sum())
    se = float(math.sqrt(((weight ** 2) * (per_hand - value) ** 2).sum()))
    freq = (weight[:, None] * mix).sum(0)
    return {"value": value, "se": se, "reach": float(z.mean()), "frequency": [float(f) for f in freq]}


# ---------------------------------------------------------------- one arm

def solve_arm(spec: SizedSpec, *, chip_ev: bool, seed: int, minutes: float, deals_target: int, hands: int,
              samples: int,
              opens: list[tuple[int, int]], log=print, on_progress=lambda seconds, deals: None) -> dict:
    numba.set_num_threads(numba.config.NUMBA_NUM_THREADS)
    threads = numba.config.NUMBA_NUM_THREADS
    started = time.time()
    tree = FullTree.build(spec.tree_config(), cache_dir=None)
    tables = HandTables.build()
    rank5, comb = five_card_ranks(), comb_table()
    if chip_ev:
        payoff = (np.zeros(0), *no_outcomes())
    else:
        table = mtticm.build(tree, spec.field_payouts)
        payoff = (np.zeros(0), table.start, table.winners, table.values)
    regrets = np.zeros((tree.rows, 3), dtype=np.float32)
    strategy_sum = np.zeros((tree.rows, 3), dtype=np.float32)
    states = thread_seeds(seed, threads)
    per_thread = max(1, 40_000 // threads)
    # Same number of deals for every size (smaller opens make bigger, slower trees); minutes caps it.
    solving, epoch, reported = time.time(), 0, 0.0
    while epoch * per_thread * threads < deals_target and time.time() - solving < minutes * 60:
        if time.time() - reported > 10:
            reported = time.time()
            on_progress(reported - solving, epoch * per_thread * threads)
        train_full(per_thread, states, tables.bucket_of, rank5, comb, tree.actor, tree.street,
                   tree.decision_index, tree.row_start, tree.children, tree.action_count, tree.behind,
                   tree.sidepot_count, tree.sidepot_amount, tree.sidepot_eligible_mask, regrets, strategy_sum,
                   tree.start_stacks, *payoff)
        epoch += 1
        if epoch <= 200:
            factor = np.float32(epoch / (epoch + 1))
            regrets *= factor
            strategy_sum *= factor
    deals = epoch * per_thread * threads
    log(f"  solved {tree.node_count:,} nodes, {deals:,} deals in {(time.time() - solving) / 60:.1f} min")
    seats = tree.seats
    names = spec.seat_names
    out = {"first_in": {}, "facing_open": {}}
    for seat in range(seats - 1):
        root, nodes, slots = first_in(tree, seat)
        out["first_in"][names[seat]] = node_value(tree, strategy_sum, tables, rank5, comb, payoff, root, nodes, slots,
                                                  hands=hands, samples=samples, seed=seed * 1000 + seat)
    for opener, defender in opens:
        root, nodes, slots = facing_open(tree, opener, defender)
        out["facing_open"][f"{names[opener]}>{names[defender]}"] = node_value(
            tree, strategy_sum, tables, rank5, comb, payoff, root, nodes, slots,
            hands=hands, samples=samples, seed=seed * 1000 + 100 + opener * 10 + defender)
    meta = {"epochs": epoch, "deals": deals, "seconds": round(time.time() - solving, 1), "threads": threads,
            "nodes": tree.node_count}
    result = export_result(spec, tree, strategy_sum, meta)
    return {"values": out, "meta": meta, "result": result, "minutes_total": (time.time() - started) / 60}


# ---------------------------------------------------------------- experiment

def spot(open_x: float, three_f: float, *, chip_ev: bool, seed: int, minutes: float,
         table: tuple[str, tuple[float, ...]] | None = None) -> SizedSpec:
    """The bubble spot: ~60 left, 60 x 30bb in play; ``table`` = (name, stacks UTG..BB) or all 30bb."""
    name, stacks = table or ("", (30.0,) * 6)
    field = (60 * 30.0 - sum(stacks)) / (60 - len(stacks))
    mode = "chip EV" if chip_ev else "ICM ~60 left"
    tag = f"{name} · " if name else ""
    return SizedSpec(stacks=stacks, payouts=MONSTER, ante_bb=0.12, minutes=max(0.5, minutes), seed=seed,
                     players_left=0 if chip_ev else 60, field_stack_bb=round(field, 4), hero="BTN",
                     label=f"sizing · {tag}{size_name(open_x, three_f)} · {mode} · seed {seed}",
                     open_x=open_x, three_f=three_f)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=ROOT / "tmp" / "plo_sizing")
    parser.add_argument("--deals", type=float, default=25e6, help="deals per arm (same for every size)")
    parser.add_argument("--minutes", type=float, default=45.0, help="time cap per arm")
    parser.add_argument("--hands", type=int, default=6000, help="hero hands sampled per decision")
    parser.add_argument("--samples", type=int, default=64, help="deals per hero hand")
    parser.add_argument("--opens", default="2,2.5,3,0", help="open sizes in BB; 0 = pot")
    parser.add_argument("--threes", default="0.5,0.75", help="3-bet fractions of pot besides pot")
    parser.add_argument("--table", action="append", default=[],
                        help="NAME:UTG,HJ,CO,BTN,SB,BB stacks; repeatable. Opens only, ICM, seeds 1-2.")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    opens = [float(x) for x in args.opens.split(",")]
    pairs = [(o, d) for o in range(5) for d in range(o + 1, 6)]

    tables = [(t.split(":")[0], tuple(float(x) for x in t.split(":")[1].split(","))) for t in args.table]
    if tables:
        arms = [(o, 1.0, False, s, t) for t in tables for s in (1, 2) for o in opens]
    else:
        arms = [(o, 1.0, False, s, None) for s in (1, 2) for o in opens] + [(o, 1.0, True, 1, None) for o in opens]
    batch = {"name": "plo-sizing", "pid": __import__("os").getpid(), "started": time.time(), "state": "running",
             "items": [{"label": spot(o, f, chip_ev=c, seed=s, minutes=args.minutes, table=t).label, "minutes": 15,
                        "seats": 6, "state": "queued", "job": None} for o, f, c, s, t in arms]}
    summary_path = args.out / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}

    def run(arm_index: int, open_x: float, three_f: float, chip_ev: bool, seed: int, table=None) -> None:
        spec = spot(open_x, three_f, chip_ev=chip_ev, seed=seed, minutes=args.minutes, table=table)
        item = batch["items"][arm_index]
        if spec.label in summary:
            item.update(state="skipped")
            progress.write_json(BATCH, batch)
            return
        job = time.strftime("%Y%m%d-%H%M%S")
        folder = JOBS / job
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "spec.json").write_text(json.dumps(spec.to_dict(), indent=1))
        progress.write_json(folder / "status.json", {"state": "solving", "seconds": 0,
                                                     "budget_seconds": args.minutes * 60, "spec": spec.to_dict()})
        item.update(state="running", job=job, started=time.time())
        progress.write_json(BATCH, batch)
        print(f"[{arm_index + 1}/{len(batch['items'])}] {spec.label}", flush=True)
        def report(seconds: float, deals: int) -> None:
            budget = seconds * args.deals / deals if deals else args.minutes * 60
            progress.write_json(folder / "status.json", {"state": "solving", "seconds": round(seconds, 1),
                                                         "deals": deals, "budget_seconds": round(min(budget, args.minutes * 60)),
                                                         "spec": spec.to_dict()})

        arm = solve_arm(spec, chip_ev=chip_ev, seed=seed, minutes=args.minutes, deals_target=int(args.deals),
                        hands=args.hands,
                        samples=args.samples, opens=pairs, on_progress=report)
        (folder / "result.json").write_text(json.dumps(arm.pop("result"), separators=(",", ":")))
        progress.write_json(folder / "status.json", {"state": "done", **arm["meta"],
                                                     "budget_seconds": args.minutes * 60, "spec": spec.to_dict()})
        summary[spec.label] = {"open_x": open_x, "three_f": three_f, "chip_ev": chip_ev, "seed": seed, "job": job,
                               "table": table[0] if table else None, "stacks": list(spec.stacks), **arm}
        progress.write_json(summary_path, summary)
        item.update(state="done", finished=time.time())
        progress.write_json(BATCH, batch)

    try:
        for i, (o, f, c, s, t) in enumerate(arms):
            run(i, o, f, c, s, t)
        if tables:
            batch["state"] = "done"
            return 0
        best = pick_open(summary, opens)
        print(f"best open (ICM): {size_name(best, 1.0)}", flush=True)
        threes = [float(x) for x in args.threes.split(",")]
        extra = [(best, f, False, s) for s in (1, 2) for f in threes]
        for o, f, c, s in extra:
            batch["items"].append({"label": spot(o, f, chip_ev=c, seed=s, minutes=args.minutes).label,
                                   "minutes": 20, "seats": 6, "state": "queued", "job": None})
        for k, (o, f, c, s) in enumerate(extra):
            run(len(arms) + k, o, f, c, s)
        batch["state"] = "done"
    except KeyboardInterrupt:
        batch["state"] = "stopped"
    finally:
        batch["finished"] = time.time()
        progress.write_json(BATCH, batch)
    return 0


def pick_open(summary: dict, opens: list[float]) -> float:
    """Open size with the best seat-average first-in value under ICM, averaged over seeds."""
    score = {}
    for o in opens:
        runs = [v for v in summary.values() if v["open_x"] == o and v["three_f"] == 1.0 and not v["chip_ev"]]
        if runs:
            score[o] = np.mean([np.mean([x["value"] for x in r["values"]["first_in"].values()]) for r in runs])
    return max(score, key=score.get)


if __name__ == "__main__":
    sys.exit(main())
