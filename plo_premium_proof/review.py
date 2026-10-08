"""Review a PLO5 (or PLO4) tournament session against all-streets ICM solves of the hands played.

Every hand becomes a FinalTableSpec: the seats and stacks of that hand, the ante, the prizes still to
be paid, and the rest of the field as one crowd of average stacks. Hands the hero played voluntarily
get their own solve; hands the hero only folded share one solve per table, level and table size (the
solve covers every seat, so each fold is read at the hero's position in its own hand).

After a solve the hand's real actions are replayed through the solver's tree (bets and raises of any
size map to the pot-sized raise, the only size in the tree) and, at every hero decision, the solver's
mix for the hero's exact cards on the real board is stored with the action taken.

    .venv/bin/python -m plo_premium_proof.review plan     --hh <file> --payouts 113.80,93.78,... --entries 57 \
        --finish 11 --first-left 45 [--start-stack 10000] [--out tmp/plo5/review]
    .venv/bin/python -m plo_premium_proof.review solve    ... same arguments   (resumable)
    .venv/bin/python -m plo_premium_proof.review evaluate ... same arguments   (option values, resumable)
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import time
from pathlib import Path

import numba
import numpy as np

from plo_equity.cards import card_text
from plo_icm.game import Action

from . import mtticm
from .finaltable import FinalTableSpec
from .fullkernels import no_outcomes, train_full
from .fulltree import STREET_BUCKETS, FullTree
from .hh import Hand, parse_file
from .kernels import colex
from .plo5 import Plo5Tables
from .postflop import board_distribution, postflop_bucket
from .preflop_chart import ACTION_NAMES
from .solve import thread_seeds
from .tables import comb_table, five_card_ranks

OUT = Path("tmp/plo5/review")
CAPS_DEEP_6 = (4, 1, 1, 1)   # six-handed, deep: keep the tree around 4M nodes
CAPS = (4, 2, 1, 1)
START_STACK = 10_000


@dataclasses.dataclass(frozen=True)
class Session:
    hands: list[Hand]
    payouts: tuple[float, ...]
    entries: int
    finish: int                   # hero's finishing place (players left at the last hand + 1 is not known)
    first_left: int               # players left estimated at the first hand
    start_stack: int = START_STACK

    def players_left(self, hand: Hand) -> int:
        """Linear in time from ``first_left`` at the first hand to ``finish`` at the hero's last hand."""
        t0, t1 = self.hands[0].time, self.hands[-1].time
        f = (hand.time - t0) / (t1 - t0) if t1 > t0 else 1.0
        left = round(self.first_left + (self.finish - self.first_left) * f)
        return max(left, len(hand.players))

    def spec(self, hand: Hand, minutes: float, label: str) -> FinalTableSpec:
        left = self.players_left(hand)
        n = len(hand.players)
        away = self.entries * self.start_stack - sum(hand.chips)
        field = (away / (left - n) / hand.bb) if left > n else 0.0
        caps = CAPS_DEEP_6 if n >= 6 and max(hand.stacks_bb) > 30 else CAPS
        return FinalTableSpec(stacks=tuple(round(x, 3) for x in hand.stacks_bb), payouts=self.payouts,
                              ante_bb=round(hand.ante_bb, 4), raise_caps=caps, minutes=minutes,
                              players_left=left if left > n else 0,
                              field_stack_bb=round(max(field, 0.2), 3) if left > n else 0.0, label=label)


def jobs(session: Session) -> list[dict]:
    """One job per voluntary hand, one per (table, level, size) group of fold-only hands."""
    out, groups = [], {}
    for hand in session.hands:
        hero_acts = [a for a in hand.actions if a.player == "Hero"]
        if not hero_acts:
            continue
        if any(a.kind in ("call", "bet", "raise") for a in hero_acts) or any(a.street > 0 for a in hero_acts):
            out.append({"id": hand.hand_id, "hands": [hand.hand_id], "kind": "hand"})
        else:
            groups.setdefault((hand.table, hand.level, len(hand.players)), []).append(hand.hand_id)
    for (table, level, n), ids in groups.items():
        out.append({"id": f"folds-t{table}-L{level}-{n}h", "hands": ids, "kind": "folds"})
    return out


DEEP_ROWS = 40e6     # trees this big (six-handed, 60bb+) cannot be solved well in minutes: not rated
MEDIUM_ROWS = 10e6


def minutes_for(tree_rows: int, kind: str) -> float:
    if tree_rows >= MEDIUM_ROWS:
        return 20.0  # five- and six-handed trees get the time the deep spots would have used
    base = 4.0 if kind == "folds" else 8.0
    return float(min(20.0, base + tree_rows / 20e6))


def quality(deals: int, rows: int) -> str:
    """How far to trust a solve: deals played per strategy-table row."""
    per_row = deals / max(rows, 1)
    return "solid" if per_row >= 5 else "fair" if per_row >= 1 else "thin"


def solve_spec(spec: FinalTableSpec, tables, log=print) -> tuple[FullTree, np.ndarray, dict]:
    """The all-streets ICM solve of one spec (finaltable.solve, with any hand table); returns the average strategy."""
    started = time.perf_counter()
    tree = FullTree.build(spec.tree_config(), cache_dir=None)
    rank5, comb = five_card_ranks(), comb_table()
    threads = spec.threads or os.cpu_count() or 1
    numba.set_num_threads(threads)
    regrets = np.zeros((tree.rows, 3), dtype=np.float32)
    strategy_sum = np.zeros((tree.rows, 3), dtype=np.float32)
    states = thread_seeds(spec.seed, threads)
    per_thread = max(1, 40_000 // threads)
    if spec.is_mtt:
        table = mtticm.build(tree, spec.field_payouts)
        outcomes, payouts = (table.start, table.winners, table.values), np.zeros(0)
    else:
        prizes = spec.prizes
        scale = float(prizes[0]) / sum(spec.stacks) if prizes[0] > 0 else 1.0
        outcomes, payouts = no_outcomes(), prizes / scale
    solving, epoch = time.perf_counter(), 0
    while time.perf_counter() - solving < spec.minutes * 60:
        train_full(per_thread, states, tables.bucket_of, rank5, comb, tree.actor, tree.street, tree.decision_index,
                   tree.row_start, tree.children, tree.action_count, tree.behind, tree.sidepot_count,
                   tree.sidepot_amount, tree.sidepot_eligible_mask, regrets, strategy_sum, tree.start_stacks,
                   payouts, *outcomes)
        epoch += 1
        if epoch <= 200:  # linear CFR: early iterations fade out
            factor = np.float32(epoch / (epoch + 1))
            regrets *= factor
            strategy_sum *= factor
    meta = {"epochs": epoch, "deals": epoch * per_thread * threads, "seconds": round(time.perf_counter() - solving),
            "build_seconds": round(solving - started), "nodes": tree.node_count, "rows": tree.rows}
    meta["quality"] = quality(meta["deals"], tree.rows)
    log(f"  solved {spec.label}: {meta}")
    return tree, strategy_sum, meta


def policy_rows(strategy_sum: np.ndarray, tree: FullTree, node: int, bucket: int) -> list[float]:
    count = int(tree.action_count[node])
    row = np.asarray(strategy_sum[int(tree.row_start[tree.decision_index[node]]) + bucket, :count], dtype=np.float64)
    total = row.sum()
    return (row / total if total > 0 else np.full(count, 1.0 / count)).round(4).tolist()


def hero_bucket(hand: Hand, street: int, tables, rank5, comb) -> int:
    cards = np.asarray(sorted(hand.hero_cards), dtype=np.int64)
    if street == 0:
        return int(tables.bucket_of[colex(cards, cards.size, comb)])
    board = np.asarray(hand.board, dtype=np.int64)
    dist = np.empty(1326, dtype=np.int64)
    count = board_distribution(board, street + 2, rank5, comb, dist)
    return int(postflop_bucket(cards, board, street, dist, count, rank5, comb))


def replay(hand: Hand, tree: FullTree, strategy_sum: np.ndarray, tables, rank5, comb) -> dict:
    """Walk the hand's actions through the tree; the hero's decisions with the solver's mix."""
    state = tree.config.root()
    node, decisions, note, path = 0, [], None, []
    stack_scale = 1.0
    for action in hand.actions:
        if tree.actor[node] < 0:
            note = "the tree ends before the hand does"
            break
        seat = int(tree.actor[node])
        if hand.players[seat] != action.player:
            note = f"order differs at {action.player} {action.kind}"
            break
        count = int(tree.action_count[node])
        legal = [ACTION_NAMES[int(tree.action_ids[node, s])] for s in range(count)]
        want = {"fold": "fold", "check": "check", "call": "call", "bet": "pot", "raise": "pot"}[action.kind]
        if want == "check" and "check" not in legal and "call" in legal:
            want = "call"
        mapped = want
        if want not in legal:
            if want == "pot" and "call" in legal:
                mapped = "call"
                note = f"{action.player}'s {action.kind} is past the tree's raise cap; read as a call"
            elif want == "pot" and "check" in legal:
                mapped = "check"
                note = f"{action.player}'s {action.kind} is past the tree's raise cap; read as a check"
            else:
                note = f"{action.player} {action.kind} is not in the tree"
                break
        slot = legal.index(mapped)
        if action.player == "Hero":
            street = int(tree.street[node])
            bucket = hero_bucket(hand, street, tables, rank5, comb)
            mix = policy_rows(strategy_sum, tree, node, bucket)
            pot = float(state.pot)
            decisions.append({"street": street, "node": node, "legal": legal, "took": mapped,
                              "real": action.kind, "real_amount": action.amount, "all_in": action.all_in,
                              "bucket": bucket, "mix": mix, "freq_taken": mix[slot],
                              "best": legal[int(np.argmax(mix))], "pot_bb": round(pot, 3),
                              "to_call_bb": round(max(0.0, state.current_bet - state.street_put[seat]), 3),
                              "board": card_text(hand.board[:street + 2]) if street else "",
                              "path": [list(p) for p in path], "slot": slot})
        path.append((node, slot))
        state = state.apply(Action(mapped))
        node = int(tree.children[node, slot])
        if node < 0:
            break
    return {"decisions": decisions, "note": note, "scale": stack_scale}


def run(session: Session, out: Path = OUT, only: set[str] | None = None, log=print) -> None:
    tables = Plo5Tables()
    rank5, comb = five_card_ranks(), comb_table()
    by_id = {h.hand_id: h for h in session.hands}
    out.mkdir(parents=True, exist_ok=True)
    for job in jobs(session):
        if only and job["id"] not in only:
            continue
        folder = out / job["id"]
        if (folder / "review.json").exists() or (folder / "skipped.json").exists():
            continue
        folder.mkdir(parents=True, exist_ok=True)
        members = [by_id[i] for i in job["hands"]]
        lead = members[len(members) // 2]
        probe = session.spec(lead, 1.0, job["id"])
        rows = FullTree.build(probe.tree_config(), cache_dir=None).rows
        attempts_file = folder / "attempts"
        attempts = int(attempts_file.read_text()) if attempts_file.exists() else 0
        if attempts >= 2:
            (folder / "skipped.json").write_text(json.dumps(
                {"job": job, "rows": rows, "reason": "the solver crashed twice on this spot"}))
            log(f"{job['id']}: skipped after {attempts} crashed attempts")
            continue
        attempts_file.write_text(str(attempts + 1))
        if rows >= DEEP_ROWS:
            (folder / "skipped.json").write_text(json.dumps(
                {"job": job, "rows": rows, "reason": "six-handed and deep: too big to solve reliably in the time"}))
            log(f"{job['id']}: skipped, {rows / 1e6:.0f}M rows")
            continue
        minutes = minutes_for(rows, job["kind"])
        spec = session.spec(lead, minutes, job["id"])
        log(f"{job['id']}: {len(members)} hand(s), {len(lead.players)}-handed, {minutes:.1f} min", )
        tree, strategy_sum, meta = solve_spec(spec, tables, log)
        reviews = {}
        for hand in members:
            if len(hand.players) != len(lead.players):
                continue
            reviews[hand.hand_id] = replay(hand, tree, strategy_sum, tables, rank5, comb)
        # compact average strategy (probability x 255) so the solve can be read again or published
        mix = strategy_sum / np.maximum(strategy_sum.sum(axis=1, keepdims=True), 1e-30)
        np.savez_compressed(folder / "policy.npz", policy=np.rint(mix * 255).astype(np.uint8))
        (folder / "review.json").write_text(json.dumps(
            {"job": job, "spec": spec.to_dict(), "meta": meta, "players_left": session.players_left(lead),
             "hands": reviews}, indent=1))


def session_from(path: Path, payouts: tuple[float, ...], entries: int, finish: int, first_left: int,
                 start_stack: int = START_STACK) -> Session:
    return Session(parse_file(path), payouts, entries, finish, first_left, start_stack)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("plan", "solve", "evaluate"))
    parser.add_argument("--hh", type=Path, required=True)
    parser.add_argument("--payouts", required=True, help="prizes 1st, 2nd, ... comma separated")
    parser.add_argument("--entries", type=int, required=True)
    parser.add_argument("--finish", type=int, required=True)
    parser.add_argument("--first-left", type=int, required=True)
    parser.add_argument("--start-stack", type=int, default=START_STACK, help="chips each entry starts with")
    parser.add_argument("--out", type=Path, default=OUT, help="folder for this session's solves")
    parser.add_argument("--deals", type=int, default=200_000, help="evaluate: simulated deals per decision")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args(argv)
    session = session_from(args.hh, tuple(float(x) for x in args.payouts.split(",")), args.entries, args.finish,
                           args.first_left, args.start_stack)
    if args.command == "evaluate":
        for folder in sorted(args.out.iterdir()):
            if (folder / "review.json").exists() and not (folder / "review_ev.json").exists():
                try:
                    evaluate(folder, session, deals=args.deals)
                except Exception as error:  # noqa: BLE001 - the page shows the hand as not rated
                    print(f"FAILED {folder.name}: {error}", flush=True)
        return
    if args.command == "plan":
        total = 0.0
        for job in jobs(session):
            lead = [h for h in session.hands if h.hand_id == job["hands"][len(job["hands"]) // 2]][0]
            rows = FullTree.build(session.spec(lead, 1, job["id"]).tree_config(), cache_dir=None).rows
            total += minutes_for(rows, job["kind"])
            print(job["id"], len(job["hands"]), len(lead.players), f"{rows / 1e6:.1f}M rows",
                  f"{minutes_for(rows, job['kind']):.1f} min", "left", session.players_left(lead), flush=True)
        print(f"{len(jobs(session))} solves, {total / 60:.1f} hours")
    else:
        run(session, out=args.out, only=set(args.only) if args.only else None)


if __name__ == "__main__":
    main()


# ---------- what each option was worth ----------

def evaluate(folder: Path, session: Session, deals: int = 400_000, log=print) -> dict:
    """Add option values (money) to every hero decision in folder/review.json, as review_ev.json."""
    from .review_ev import action_values
    data = json.loads((folder / "review.json").read_text())
    spec = FinalTableSpec.from_dict(data["spec"])
    tree = FullTree.build(spec.tree_config(), cache_dir=None)
    raw = np.load(folder / "policy.npz")["policy"].astype(np.float32)
    policy = raw / np.maximum(raw.sum(axis=1, keepdims=True), 1.0)
    tables = Plo5Tables()
    rank5, comb = five_card_ranks(), comb_table()
    table = mtticm.build(tree, spec.field_payouts) if spec.is_mtt else None
    if table is not None:
        outcomes, payouts = (table.start, table.winners, table.values), np.zeros(0)
        money = sum(spec.field_payouts.prizes) / (sum(spec.stacks) + spec.field_payouts.chips_away)
    else:
        prizes = spec.prizes
        scale = float(prizes[0]) / sum(spec.stacks) if prizes[0] > 0 else 1.0
        outcomes, payouts, money = no_outcomes(), prizes / scale, scale
    threads = os.cpu_count() or 1
    numba.set_num_threads(threads)
    by_id = {h.hand_id: h for h in session.hands}
    result = {}
    for hand_id in data["hands"]:
        hand = by_id[hand_id]
        replayed = replay(hand, tree, policy, tables, rank5, comb)
        cards = np.asarray(sorted(hand.hero_cards), dtype=np.int64)
        for d in replayed["decisions"]:
            known = np.asarray(hand.board[:d["street"] + 2] if d["street"] else [], dtype=np.int64)
            path = np.asarray(d["path"], dtype=np.int64).reshape(-1, 2)
            states = thread_seeds(hash(hand_id) % 100_000 + d["node"] % 1000, threads)
            sums = action_values(max(1, deals // threads), states, hand.hero, cards, known, known.size, d["node"],
                                 path[:, 0].copy(), path[:, 1].copy(), policy, tables.bucket_of, rank5, comb,
                                 tree.actor, tree.street, tree.decision_index, tree.row_start, tree.children,
                                 tree.action_count, tree.behind, tree.sidepot_count, tree.sidepot_amount,
                                 tree.sidepot_eligible_mask, tree.start_stacks, payouts, *outcomes)
            total = sums.sum(axis=0)
            weight = total[0]
            n = len(d["legal"])
            if weight <= 0:
                d["values"] = None
                continue
            values = total[1:1 + n] / weight
            # standard error from the spread between threads
            per_thread = sums[:, 1:1 + n] / np.maximum(sums[:, :1], 1e-300)
            se = per_thread.std(axis=0) / np.sqrt(len(sums)) if len(sums) > 1 else np.zeros(n)
            d["values"] = (values * money).round(4).tolist()
            d["value_se"] = (se * money).round(4).tolist()
            d["loss"] = round(float((values.max() - values[d["slot"]]) * money), 4)
            d["mix_loss"] = round(float((values.max() - float(np.dot(d["mix"], values))) * money), 4)
            d["effective_deals"] = round(float(weight ** 2 / max(float(total[4]), 1e-300)))
        result[hand_id] = replayed
    (folder / "review_ev.json").write_text(json.dumps({"money_per_bb": money, "hands": result}, indent=1))
    log(f"  values {folder.name}: {sum(len(r['decisions']) for r in result.values())} decision(s)")
    return result
