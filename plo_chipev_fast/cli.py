"""Finite, checkpointed command-line workflows for the fast backend."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from plo_chipev.checkpoint import load_checkpoint as load_legacy_checkpoint

from .checkpoint import load_checkpoint, save_checkpoint
from .evaluation import evaluate_profile
from .hands import HandLookup, measure_exact_classes
from .model import DenseModel, import_legacy_solver
from .trainer import FastTrainer, SignalStop
from .tree import PublicTree


def _nonnegative(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return parsed


def _positive(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m plo_chipev_fast")
    commands = result.add_subparsers(dest="command", required=True)
    info = commands.add_parser("build-info")
    info.add_argument("--measure-exact", action="store_true")

    train = commands.add_parser("train")
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--iterations", type=_nonnegative, required=True)
    train.add_argument("--seconds", type=_positive)
    train.add_argument("--resume", action="store_true")
    train.add_argument("--overwrite", action="store_true")
    train.add_argument("--legacy-checkpoint", type=Path)
    train.add_argument("--chance-seed", type=int, default=0xC0FFEE)
    train.add_argument("--sampling-seed", type=int, default=0xBAD5EED)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--checkpoint", type=Path, required=True)
    evaluate.add_argument("--hands", type=_nonnegative, required=True)
    evaluate.add_argument("--seed", type=int, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--overwrite", action="store_true")
    return result


@contextmanager
def _lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "checkpoint.lock"
    with path.open("a+b") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"checkpoint is locked: {root}") from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _new_or_import(
    args: argparse.Namespace, tree: PublicTree, hands: HandLookup
) -> FastTrainer:
    if args.legacy_checkpoint is None:
        model = DenseModel.empty(tree, hands)
    else:
        legacy, _round, _payload = load_legacy_checkpoint(args.legacy_checkpoint)
        digest = hashlib.sha256(args.legacy_checkpoint.read_bytes()).hexdigest()
        model = import_legacy_solver(
            legacy, tree, hands, source_checkpoint_hash=digest
        )
    trainer = FastTrainer(
        model, chance_seed=args.chance_seed, sampling_seed=args.sampling_seed
    )
    if args.legacy_checkpoint is not None:
        trainer.completed_iterations = legacy.completed_iterations
        trainer.completed_traversals = legacy.completed_traversals
        trainer.nodes = legacy.nodes
        trainer.imported_iterations = legacy.completed_iterations
        trainer.imported_traversals = legacy.completed_traversals
        trainer.imported_nodes = legacy.nodes
    return trainer


def _train(args: argparse.Namespace) -> int:
    tree = PublicTree.build()
    hands = HandLookup.build()
    with _lock(args.output):
        checkpoint_exists = (args.output / "checkpoint.json").exists()
        if args.resume:
            if args.overwrite or args.legacy_checkpoint is not None:
                raise ValueError("--resume cannot be combined with --overwrite or --legacy-checkpoint")
            trainer, loaded = load_checkpoint(args.output, tree, hands)
        else:
            if checkpoint_exists and not args.overwrite:
                raise ValueError("output exists; use --resume or --overwrite")
            trainer = _new_or_import(args, tree, hands)
            loaded = None
            # Valid generation zero exists even if the deadline prevents training.
            save_checkpoint(trainer, args.output, overwrite=args.overwrite)
        with SignalStop(trainer):
            metrics = trainer.train(iterations=args.iterations, seconds=args.seconds)
        save_checkpoint(trainer, args.output)
        status = {
            **metrics,
            "checkpoint": str(args.output / "checkpoint.json"),
            "loaded_generation": loaded["loaded_generation"] if loaded else None,
            "feature_bucket_count": hands.bucket_count,
            "physical_hand_count": hands.physical_count,
            "public_nodes": tree.node_count,
            "public_decision_nodes": tree.decision_count,
            "claim": "feature-abstracted forced-checkdown approximation; not ordinary-PLO GTO",
        }
        _atomic_json(args.output / "status.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    if args.hands <= 0:
        raise ValueError("hands must be positive")
    if args.output.exists() and not args.overwrite:
        raise ValueError("evaluation output exists; use --overwrite explicitly")
    tree = PublicTree.build()
    hands = HandLookup.build()
    with _lock(args.checkpoint):
        trainer, _metadata = load_checkpoint(args.checkpoint, tree, hands)
        report = evaluate_profile(trainer, hands=args.hands, seed=args.seed)
        _atomic_json(args.output, report)
    print(json.dumps(report["model_identity"], sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "build-info":
        tree = PublicTree.build()
        hands = HandLookup.build()
        result: dict[str, object] = {
            "public_nodes": tree.node_count,
            "decision_nodes": tree.decision_count,
            "terminal_nodes": tree.terminal_count,
            "physical_hands": hands.physical_count,
            "feature_buckets": hands.bucket_count,
            "feature_dense_bytes": tree.decision_count * hands.bucket_count * 3 * 16,
        }
        if args.measure_exact:
            result["exact_measurement"] = measure_exact_classes()
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "train":
        return _train(args)
    if args.command == "evaluate":
        return _evaluate(args)
    raise AssertionError(args.command)
