"""The strong range used by the hand score: the hands the big blind 3-bets against a button raise.

Taken from a trained solution, so it is the range a player actually meets in a raised pot rather
than a guess. Stored as one weight per four-card hand (combinations(range(52), 4) order), the
probability that the hand's preflop class 3-bets.

    .venv/bin/python -m o8_fl.ranges --run tmp/o8_fl/run2 --pool tmp/o8_fl/pool.npz
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np

RANGE = Path("tmp/o8_fl/strong_range.npz")
COMBOS = np.array(list(itertools.combinations(range(52), 4)), dtype=np.int64)
THREE_BET = ("r", 2)  # big blind facing a raise, slot 2 = raise


def three_bet_weights(trainer, abstraction) -> np.ndarray:
    """Per-hand weights from a Trainer and its Abstraction."""
    history, slot = THREE_BET
    node = trainer.tree.history_to_node[history]
    per_class = np.array([trainer.average_policy(node, c)[slot] for c in range(len(abstraction.preflop_names))])
    return per_class[abstraction.preflop].astype(np.float32)


def load_cdf(path: Path = RANGE) -> tuple[np.ndarray, np.ndarray]:
    """(combos, cumulative weights) for sampling the range with equity.range_hand."""
    weights = np.load(path)["weights"].astype(np.float64)
    if weights.shape != (COMBOS.shape[0],) or weights.sum() <= 0:
        raise ValueError(f"{path} is not a weight per four-card hand")
    return COMBOS, np.cumsum(weights)


def main(argv: list[str] | None = None) -> None:
    # Imported here: pool and flops import this module, and the trainer imports pool.
    from .buckets import Abstraction
    from .cli import ABSTRACTION
    from .game import Rules
    from .pool import DealPool
    from .trainer import Trainer
    from .tree import PublicTree

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, default=Path("tmp/o8_fl/run2"))
    parser.add_argument("--pool", type=Path, default=Path("tmp/o8_fl/pool.npz"))
    parser.add_argument("--cap", type=int, default=5)
    parser.add_argument("--out", type=Path, default=RANGE)
    args = parser.parse_args(argv)
    abstraction = Abstraction.cached(ABSTRACTION)
    trainer = Trainer.load(args.run / "checkpoint.npz", PublicTree.build(Rules(cap=args.cap)), abstraction,
                           DealPool.load(args.pool))
    weights = three_bet_weights(trainer, abstraction)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.out, weights=weights, iterations=trainer.iterations)
    print(json.dumps({"out": str(args.out), "share": round(float(weights.mean()), 4),
                      "iterations": trainer.iterations}))


if __name__ == "__main__":
    main()
