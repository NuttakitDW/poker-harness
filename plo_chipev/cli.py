"""Bounded training, frozen evaluation, and certification orchestration."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import fcntl
import hashlib
import json
import math
import os
import signal
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .certificate import certify_profile
from .checkpoint import (
    atomic_json,
    initialize_round_ledger,
    load_checkpoint,
    load_round_high_water,
    reserve_evaluation_round,
    save_checkpoint,
)
from .config import Config
from .evaluation import (
    EvaluationDeadlineExceeded,
    evaluate_profile,
    frozen_profile_hash,
)
from .solver import Solver


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--abstraction", choices=("features", "exact"))
    parser.add_argument("--max-infosets", type=_positive_int, default=250_000)
    parser.add_argument("--max-nodes", type=_positive_int, default=1_000_000)
    parser.add_argument("--overwrite", action="store_true")


def _add_certificate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--certificate-batches", type=_positive_int, default=2)
    parser.add_argument("--certificate-batch-hands", type=_positive_int, default=1)
    parser.add_argument("--certificate-alpha", type=_positive_float, default=0.05)
    parser.add_argument("--certificate-max-nodes", type=_positive_int)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m plo_chipev")
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train", help="train or resume one bounded chunk")
    _add_model_arguments(train)
    train.add_argument("--seconds", type=_positive_float)
    train.add_argument("--iterations", type=_nonnegative_int)

    evaluate = commands.add_parser("evaluate", help="evaluate one frozen checkpoint")
    evaluate.add_argument("checkpoint", type=Path)
    evaluate.add_argument("--hands", type=_positive_int, required=True)
    evaluate.add_argument("--seed", type=int, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--overwrite", action="store_true")
    evaluate.add_argument("--certificate-batches", type=_nonnegative_int, default=0)
    evaluate.add_argument("--certificate-batch-hands", type=_positive_int, default=1)
    evaluate.add_argument("--certificate-alpha", type=_positive_float, default=0.05)
    evaluate.add_argument("--certificate-max-nodes", type=_positive_int)
    evaluate.add_argument("--certificate-max-seconds", type=_positive_float)

    solve = commands.add_parser(
        "solve", help="bounded train/checkpoint/evaluate/certify loop"
    )
    _add_model_arguments(solve)
    _add_certificate_arguments(solve)
    solve.add_argument("--max-seconds", type=_positive_float, required=True)
    solve.add_argument("--chunk-seconds", type=_positive_float, default=5.0)
    solve.add_argument("--chunk-iterations", type=_positive_int, default=2**31 - 1)
    solve.add_argument("--evaluation-hands", type=_positive_int, default=10)
    return parser


@contextmanager
def _exclusive_lock(checkpoint: Path) -> Iterator[None]:
    lock_path = checkpoint.with_name(checkpoint.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"checkpoint is locked by another process: {checkpoint}") from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _install_signal_handlers(solver: Solver) -> dict[signal.Signals, Any]:
    previous: dict[signal.Signals, Any] = {}

    def request_stop(_signum: int, _frame: Any) -> None:
        solver.request_stop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, request_stop)
    return previous


def _restore_signal_handlers(previous: dict[signal.Signals, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _checkpoint_for(args: argparse.Namespace) -> Path:
    return args.output / "checkpoint.json"


def _guard_fresh_output(args: argparse.Namespace) -> None:
    checkpoint = _checkpoint_for(args)
    if args.resume is not None and args.resume.resolve() != checkpoint.resolve():
        raise ValueError("--resume must name the checkpoint inside --output")
    if args.resume is None and checkpoint.exists() and not args.overwrite:
        raise ValueError(
            f"output already contains a checkpoint; use --resume or --overwrite: {checkpoint}"
        )


def _load_or_create(
    args: argparse.Namespace, *, iterations: int, seconds: float | None
) -> tuple[Solver, int]:
    if args.resume:
        solver, evaluation_round, _ = load_checkpoint(args.resume)
        if args.abstraction is not None and args.abstraction != solver.config.hand_abstraction:
            raise ValueError("resume abstraction does not match checkpoint fingerprint")
        if args.max_infosets < len(solver.infosets):
            raise ValueError("max-infosets cannot be lower than the loaded state")
        if args.max_nodes < solver.nodes:
            raise ValueError("max-nodes cannot be lower than cumulative loaded nodes")
        solver.config = dataclasses.replace(
            solver.config,
            iterations=iterations,
            time_limit_seconds=seconds,
            max_infosets=args.max_infosets,
            max_nodes=args.max_nodes,
        )
        return solver, evaluation_round
    return (
        Solver(
            Config(
                seed=args.seed,
                hand_abstraction=args.abstraction or "features",
                iterations=iterations,
                time_limit_seconds=seconds,
                max_infosets=args.max_infosets,
                max_nodes=args.max_nodes,
            )
        ),
        0,
    )


def _status_for_stop(reason: str) -> str:
    if reason == "signal":
        return "stopped_by_user"
    if reason == "max_infosets":
        return "resource_limited"
    if reason in {"max_nodes", "time_limit_seconds"}:
        return "budget_limited"
    return "checkpointed"


def _train(args: argparse.Namespace) -> int:
    if args.iterations is None and args.seconds is None:
        raise ValueError("train requires a finite --iterations and/or --seconds budget")
    additional_iterations = args.iterations if args.iterations is not None else 2**63 - 1
    checkpoint_path = _checkpoint_for(args)
    with _exclusive_lock(checkpoint_path):
        _guard_fresh_output(args)
        fresh_replace = args.resume is None and args.overwrite and checkpoint_path.exists()
        solver, evaluation_round = _load_or_create(
            args, iterations=additional_iterations, seconds=args.seconds
        )
        status_path = args.output / "status.json"
        atomic_json(
            status_path,
            {
                "state": "running",
                "started_unix": time.time(),
                "completed_iterations_before": solver.completed_iterations,
            },
        )
        previous = _install_signal_handlers(solver)
        try:
            metadata = solver.train(
                additional_iterations=additional_iterations, seconds=args.seconds
            )
        finally:
            _restore_signal_handlers(previous)
        save_checkpoint(
            solver,
            checkpoint_path,
            evaluation_round=evaluation_round,
            fresh_replace=fresh_replace,
        )
        if args.resume is None:
            initialize_round_ledger(checkpoint_path)
        result = {
            "state": _status_for_stop(metadata["stop_reason"]),
            "checkpoint": str(checkpoint_path),
            "metadata": metadata,
            "target_certified": False,
            "note": "budget completion is not a convergence certificate",
        }
        atomic_json(status_path, result)
    print(
        f"iterations={metadata['iterations_completed']} nodes={metadata['nodes']} "
        f"infosets={metadata['infosets']} stop={metadata['stop_reason']} "
        f"elapsed={metadata['elapsed_seconds']:.3f}s"
    )
    return 0


def _write_csv(path: Path, report: dict[str, Any]) -> None:
    csv_path = path.with_suffix(".csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = csv_path.with_name(f".{csv_path.name}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "report_id",
                "profile_hash",
                "iterations_completed",
                "evaluation_round",
                "section",
                "name",
                "population",
                "vpip",
                "net_bb_per_100",
            ),
        )
        writer.writeheader()
        identity = report["evaluated_checkpoint"]
        common = {
            "report_id": report["report_id"],
            "profile_hash": identity["profile_hash"],
            "iterations_completed": identity["iterations_completed"],
            "evaluation_round": identity["evaluation_round"],
        }
        for name, row in report["by_position"].items():
            writer.writerow(
                common
                | {
                    "section": "position",
                    "name": name,
                    "population": report["table_hands"],
                    "vpip": row["vpip"],
                    "net_bb_per_100": row["net_bb_per_100"],
                }
            )
        for name, row in report["hwang_inspired_reporting_only"].items():
            writer.writerow(
                common
                | {
                    "section": "hwang_inspired_tier",
                    "name": name,
                    "population": row["population"],
                    "vpip": row["vpip"],
                    "net_bb_per_100": "",
                }
            )
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, csv_path)


def _checkpoint_identity(solver: Solver) -> dict[str, Any]:
    return {
        "profile_hash": frozen_profile_hash(solver),
        "iterations_completed": solver.completed_iterations,
    }


def _tag_report(
    report: dict[str, Any], solver: Solver, *, evaluation_round: int
) -> dict[str, Any]:
    identity = _checkpoint_identity(solver) | {"evaluation_round": evaluation_round}
    report["evaluated_checkpoint"] = identity
    material = json.dumps(
        report, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    report["report_id"] = hashlib.sha256(material).hexdigest()
    return report


def _load_written_report(path: Path) -> dict[str, Any] | None:
    csv_path = path.with_suffix(".csv")
    if not path.exists() or not csv_path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            return None
        report_id = report.pop("report_id")
        material = json.dumps(
            report, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        report["report_id"] = report_id
        with csv_path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        expected_rows = len(report.get("by_position", {})) + len(
            report.get("hwang_inspired_reporting_only", {})
        )
        if (
            not isinstance(report_id, str)
            or hashlib.sha256(material).hexdigest() != report_id
            or not rows
            or len(rows) != expected_rows
            or any(row.get("report_id") != report_id for row in rows)
            or not isinstance(report.get("evaluated_checkpoint"), dict)
        ):
            return None
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        csv.Error,
        KeyError,
        StopIteration,
        TypeError,
        ValueError,
    ):
        return None
    return report


def _guard_report_output(path: Path, overwrite: bool) -> None:
    if (path.exists() or path.with_suffix(".csv").exists()) and not overwrite:
        raise ValueError(f"evaluation output exists; pass --overwrite: {path}")


def _evaluate(args: argparse.Namespace) -> int:
    _guard_report_output(args.output, args.overwrite)
    with _exclusive_lock(args.checkpoint):
        solver, evaluation_round, _ = load_checkpoint(args.checkpoint)
        if args.certificate_batches:
            if args.certificate_batches < 2:
                raise ValueError("certificate-batches must be 0 or at least 2")
            evaluation_round = reserve_evaluation_round(
                args.checkpoint, checkpoint_round=evaluation_round
            )
            save_checkpoint(solver, args.checkpoint, evaluation_round=evaluation_round)
        report = evaluate_profile(solver, hands=args.hands, seed=args.seed)
        if args.certificate_batches:
            report["certificate"] = certify_profile(
                solver,
                batches=args.certificate_batches,
                batch_hands=args.certificate_batch_hands,
                seed=args.seed,
                alpha=args.certificate_alpha,
                round_index=evaluation_round,
                max_nodes=args.certificate_max_nodes,
                max_seconds=args.certificate_max_seconds,
            )
        else:
            report["certificate"] = {
                "complete": False,
                "certified": False,
                "reason": "certificate not requested",
            }
        _tag_report(report, solver, evaluation_round=evaluation_round)
        atomic_json(args.output, report)
        _write_csv(args.output, report)
    overall = report["overall_vpip"]
    certificate = report["certificate"]
    print(
        f"hands={args.hands} vpip={100 * overall['mean']:.2f}% "
        f"table_net_bb_per_100={report['table_net_bb_per_100']:.9g} "
        f"certified={certificate['certified']}"
    )
    return 0


def _solve(args: argparse.Namespace) -> int:
    checkpoint_path = _checkpoint_for(args)
    status_path = args.output / "status.json"
    evaluation_path = args.output / "evaluation.json"
    started = time.perf_counter()
    deadline = started + args.max_seconds
    active_train = 0.0
    active_evaluation = 0.0
    written_report: dict[str, Any] | None = None
    fresh_lineage = args.resume is None
    with _exclusive_lock(checkpoint_path):
        _guard_fresh_output(args)
        fresh_replace = fresh_lineage and args.overwrite and checkpoint_path.exists()
        solver, checkpoint_round = _load_or_create(
            args, iterations=args.chunk_iterations, seconds=args.chunk_seconds
        )
        if fresh_lineage:
            save_checkpoint(
                solver,
                checkpoint_path,
                evaluation_round=checkpoint_round,
                fresh_replace=fresh_replace,
            )
            initialize_round_ledger(checkpoint_path)
        evaluation_round = load_round_high_water(checkpoint_path)
        if evaluation_round < checkpoint_round:
            raise ValueError(
                "evaluation round ledger cannot prove the checkpoint round high-water mark"
            )
        written_report = (
            None if fresh_lineage else _load_written_report(evaluation_path)
        )
        previous = _install_signal_handlers(solver)
        try:
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                before_train = time.perf_counter()
                metadata = solver.train(
                    additional_iterations=args.chunk_iterations,
                    seconds=min(args.chunk_seconds, remaining),
                )
                active_train += time.perf_counter() - before_train
                remaining = deadline - time.perf_counter()
                if remaining <= 0 or metadata["stop_reason"] in {
                    "signal",
                    "max_nodes",
                    "max_infosets",
                }:
                    save_checkpoint(
                        solver, checkpoint_path, evaluation_round=evaluation_round
                    )
                    break
                save_checkpoint(
                    solver, checkpoint_path, evaluation_round=evaluation_round
                )
                evaluation_round = reserve_evaluation_round(
                    checkpoint_path, checkpoint_round=evaluation_round
                )
                save_checkpoint(
                    solver, checkpoint_path, evaluation_round=evaluation_round
                )
                before_evaluation = time.perf_counter()
                try:
                    candidate_report = evaluate_profile(
                        solver,
                        hands=args.evaluation_hands,
                        seed=args.seed,
                        deadline=deadline,
                        honor_stop_request=True,
                    )
                except EvaluationDeadlineExceeded:
                    active_evaluation += time.perf_counter() - before_evaluation
                    break
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    active_evaluation += time.perf_counter() - before_evaluation
                    break
                candidate_report["certificate"] = certify_profile(
                    solver,
                    batches=args.certificate_batches,
                    batch_hands=args.certificate_batch_hands,
                    seed=args.seed,
                    alpha=args.certificate_alpha,
                    round_index=evaluation_round,
                    max_nodes=args.certificate_max_nodes,
                    max_seconds=remaining,
                )
                _tag_report(
                    candidate_report, solver, evaluation_round=evaluation_round
                )
                active_evaluation += time.perf_counter() - before_evaluation
                atomic_json(evaluation_path, candidate_report)
                _write_csv(evaluation_path, candidate_report)
                written_report = candidate_report
                if written_report["certificate"]["certified"]:
                    break
                if not written_report["certificate"]["complete"]:
                    break
        finally:
            _restore_signal_handlers(previous)

        current_identity = _checkpoint_identity(solver)
        written_identity = (
            written_report.get("evaluated_checkpoint") if written_report else None
        )
        evaluation_stale = (
            None
            if written_identity is None
            else any(
                written_identity.get(name) != current_identity[name]
                for name in ("profile_hash", "iterations_completed")
            )
        )
        certified = bool(
            written_report is not None
            and evaluation_stale is False
            and written_report.get("certificate", {}).get("certified", False)
        )
        if certified:
            state = "certified"
        elif solver.stop_reason == "signal" or solver.stop_requested:
            state = "stopped_by_user"
        elif solver.stop_reason == "max_infosets":
            state = "resource_limited"
        else:
            state = "budget_limited"
        result = {
            "state": state,
            "target_certified": certified,
            "checkpoint": str(checkpoint_path),
            "checkpoint_identity": current_identity,
            "evaluation": str(evaluation_path) if written_report is not None else None,
            "last_successfully_written_evaluation": written_identity,
            "evaluation_stale": evaluation_stale,
            "evaluation_round": evaluation_round,
            "active_train_seconds": active_train,
            "active_evaluation_seconds": active_evaluation,
            "total_elapsed_seconds": time.perf_counter() - started,
            "metadata": solver.metadata(),
        }
        atomic_json(status_path, result)
    print(
        f"state={result['state']} iterations={solver.completed_iterations} "
        f"nodes={solver.nodes} rounds={evaluation_round} "
        f"train={active_train:.3f}s eval={active_evaluation:.3f}s"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "train":
            return _train(args)
        if args.command == "evaluate":
            return _evaluate(args)
        return _solve(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
