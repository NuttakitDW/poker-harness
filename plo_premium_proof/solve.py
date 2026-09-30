"""Time-bounded, checkpointed MCCFR driver with Pluribus-style linear discounting."""

from __future__ import annotations

import dataclasses
import json
import os
import time
from pathlib import Path
from typing import Any

import numba
import numpy as np

from .kernels import train_batch
from .tables import HandTables, TreeArrays, comb_table, five_card_ranks

MASK64 = (1 << 64) - 1
SCHEMA = "plo-premium-proof-model-v1"


def thread_seeds(seed: int, threads: int) -> np.ndarray:
    """Distinct SplitMix64 starting states, one per worker thread."""
    states = []
    value = seed & MASK64
    for _ in range(threads):
        value = (value + 0x9E3779B97F4A7C15) & MASK64
        mixed = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        mixed = ((mixed ^ (mixed >> 27)) * 0x94D049BB133111EB) & MASK64
        states.append((mixed ^ (mixed >> 31)) & MASK64)
    return np.asarray(states, dtype=np.uint64)


@dataclasses.dataclass(frozen=True)
class SolveConfig:
    seconds: float
    threads: int = 12
    seed: int = 1
    epoch_traversals: int = 4_000_000
    discount_epochs: int = 100
    checkpoint_every: int = 25

    def __post_init__(self) -> None:
        if not self.seconds > 0:
            raise ValueError("seconds must be positive")
        if self.threads < 1 or self.epoch_traversals < self.threads:
            raise ValueError("need at least one traversal per thread per epoch")
        if self.discount_epochs < 0 or self.checkpoint_every < 1:
            raise ValueError("invalid discount or checkpoint schedule")


def save_model(path: Path, regrets: np.ndarray, strategy_sum: np.ndarray, meta: dict[str, Any]) -> None:
    """Write atomically so an interrupted save never replaces a good checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.npz")
    np.savez(temporary, regrets=regrets, strategy_sum=strategy_sum, meta=json.dumps(meta))
    os.replace(temporary, path)


def load_model(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    with np.load(path) as data:
        meta = json.loads(str(data["meta"]))
        if meta.get("schema") != SCHEMA:
            raise ValueError(f"{path} is not a {SCHEMA} checkpoint")
        return data["regrets"], data["strategy_sum"], meta


def solve(config: SolveConfig, output: Path, *, log=print) -> dict[str, Any]:
    tables = HandTables.build()
    if not tables.tier_is_pure():
        raise RuntimeError("abstraction mixes Hwang tiers")
    rank5 = five_card_ranks()
    comb = comb_table()
    tree = TreeArrays.build()
    shape = (tree.decision_count, tables.bucket_count, 3)
    regrets = np.zeros(shape, dtype=np.float64)
    strategy_sum = np.zeros(shape, dtype=np.float64)
    states = thread_seeds(config.seed, config.threads)
    per_thread = config.epoch_traversals // config.threads
    numba.set_num_threads(config.threads)
    started = time.perf_counter()
    epoch = 0
    meta: dict[str, Any] = {}

    def checkpoint() -> dict[str, Any]:
        info = {
            "schema": SCHEMA,
            "seed": config.seed,
            "threads": config.threads,
            "epochs": epoch,
            "traversals": epoch * per_thread * config.threads,
            "discounted_epochs": min(epoch, config.discount_epochs),
            "seconds": time.perf_counter() - started,
            "buckets": tables.bucket_count,
            "abstraction": "572 feature buckets x Hwang tier (tier-pure)",
            "game": "PLO4 6-max 100bb chip EV, pot-only, 2-raise cap, check-down",
        }
        save_model(output / "model.npz", regrets, strategy_sum, info)
        return info

    while time.perf_counter() - started < config.seconds:
        train_batch(
            per_thread, states, 1.0, tables.bucket_of, rank5, comb,
            tree.actor, tree.decision_index, tree.children, tree.action_count, tree.behind,
            tree.sidepot_count, tree.sidepot_amount, tree.sidepot_eligible_mask,
            regrets, strategy_sum,
        )
        epoch += 1
        if epoch <= config.discount_epochs:
            factor = epoch / (epoch + 1)
            regrets *= factor
            strategy_sum *= factor
        if epoch % config.checkpoint_every == 0:
            meta = checkpoint()
            log(json.dumps({"epoch": epoch, "traversals": meta["traversals"],
                            "seconds": round(meta["seconds"], 1)}))
    return checkpoint()
