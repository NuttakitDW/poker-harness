"""Strict, atomic, hash-enveloped JSON checkpoints without pickle."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import platform
import secrets
import shutil
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np

from .config import Config, ConfigError
from .solver import Solver

FORMAT = "plo-chipev-checkpoint-v2"
SCHEMA_VERSION = 2
MAX_CHECKPOINT_BYTES = 1_000_000_000
MIN_FREE_DISK_BYTES = 10_000_000
ACTION_SCHEMA = "legacy-actions:fold,check,call,pot;pot-only;raise-cap-2"
ROUND_LEDGER_FORMAT = "plo-chipev-evaluation-round-ledger-v1"


def _canonical(data: Any) -> bytes:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(data: Any) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def game_fingerprint(config: Config) -> str:
    names = (
        "variant",
        "format",
        "players",
        "stack_bb",
        "small_blind_bb",
        "big_blind_bb",
        "ante_bb",
        "rake",
        "utility",
        "payouts_or_icm",
        "postflop",
        "max_voluntary_raises",
        "hand_abstraction",
    )
    semantics = {name: getattr(config, name) for name in names}
    semantics["action_schema"] = ACTION_SCHEMA
    return _digest(semantics)


def source_hashes() -> dict[str, str]:
    package = Path(__file__).resolve().parent
    root = package.parent
    paths = sorted(package.glob("*.py")) + [
        root / "plo_icm" / "game.py",
        root / "plo_icm" / "cards.py",
        root / "plo_icm" / "abstraction.py",
        root / "scripts" / "voice" / "plo_type.py",
    ]
    hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    try:
        from phevaluator import _pheval

        native_path = Path(_pheval.__file__).resolve()
        hashes["dependency:phevaluator-native"] = hashlib.sha256(
            native_path.read_bytes()
        ).hexdigest()
    except (ImportError, OSError, TypeError) as exc:
        raise RuntimeError(
            "phevaluator is required; install the project dependencies before checkpointing"
        ) from exc
    return hashes


def dependency_versions() -> dict[str, str]:
    try:
        phevaluator_version = metadata.version("phevaluator")
    except metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "phevaluator is required; install the project dependencies before checkpointing"
        ) from exc
    return {
        "numpy": np.__version__,
        "phevaluator": phevaluator_version,
        "python_semantics": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def build_payload(solver: Solver, *, evaluation_round: int = 0) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "game_fingerprint": game_fingerprint(solver.config),
        "config": solver.config.to_dict(),
        "solver": solver.snapshot(),
        "evaluation_round": evaluation_round,
        "source_hashes": source_hashes(),
        "dependency_versions": dependency_versions(),
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
    }


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {"format": FORMAT, "sha256": _digest(payload), "payload": payload}


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _guard_output(path: Path, content: bytes) -> None:
    if len(content) > MAX_CHECKPOINT_BYTES:
        raise ValueError("output exceeds size guard")
    path.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path.parent).free
    if free < len(content) + MIN_FREE_DISK_BYTES:
        raise OSError("insufficient free disk space for atomic output")


def atomic_json(path: str | Path, data: Any) -> Path:
    destination = Path(path)
    rendered = json.dumps(
        data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ).encode("utf-8")
    content = rendered + b"\n"
    _guard_output(destination, content)
    _atomic_bytes(destination, content)
    return destination


def round_ledger_path(checkpoint: str | Path) -> Path:
    source = Path(checkpoint)
    return source.with_name(source.stem + ".evaluation-rounds" + source.suffix)


def _round_ledger_envelope(lineage_id: str, high_water: int) -> dict[str, Any]:
    payload = {
        "lineage_id": lineage_id,
        "last_reserved_round": high_water,
    }
    return {
        "format": ROUND_LEDGER_FORMAT,
        "sha256": _digest(payload),
        "payload": payload,
    }


def _load_round_ledger(checkpoint: str | Path) -> tuple[str, int]:
    path = round_ledger_path(checkpoint)
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"evaluation round ledger is missing or corrupt: {path}") from exc
    if not isinstance(envelope, dict) or set(envelope) != {
        "format",
        "sha256",
        "payload",
    }:
        raise ValueError("evaluation round ledger has an incompatible schema")
    payload = envelope["payload"]
    if (
        envelope["format"] != ROUND_LEDGER_FORMAT
        or not isinstance(payload, dict)
        or set(payload) != {"lineage_id", "last_reserved_round"}
        or envelope["sha256"] != _digest(payload)
    ):
        raise ValueError("evaluation round ledger failed integrity validation")
    lineage_id = payload["lineage_id"]
    high_water = payload["last_reserved_round"]
    if not isinstance(lineage_id, str) or not lineage_id:
        raise ValueError("evaluation round ledger lineage is invalid")
    if isinstance(high_water, bool) or not isinstance(high_water, int) or high_water < 0:
        raise ValueError("evaluation round ledger high-water mark is invalid")
    return lineage_id, high_water


def initialize_round_ledger(checkpoint: str | Path) -> int:
    """Create a ledger only for a known-fresh lineage; never repair or reset one."""
    path = round_ledger_path(checkpoint)
    if path.exists():
        return _load_round_ledger(checkpoint)[1]
    atomic_json(path, _round_ledger_envelope(secrets.token_hex(16), 0))
    return 0


def load_round_high_water(checkpoint: str | Path) -> int:
    return _load_round_ledger(checkpoint)[1]


def reserve_evaluation_round(
    checkpoint: str | Path, *, checkpoint_round: int
) -> int:
    """Atomically burn the next confidence-spending index under the caller's OS lock."""
    if (
        isinstance(checkpoint_round, bool)
        or not isinstance(checkpoint_round, int)
        or checkpoint_round < 0
    ):
        raise ValueError("checkpoint_round must be a nonnegative integer")
    lineage_id, high_water = _load_round_ledger(checkpoint)
    if high_water < checkpoint_round:
        raise ValueError(
            "evaluation round ledger cannot prove the checkpoint round high-water mark"
        )
    reserved = high_water + 1
    atomic_json(
        round_ledger_path(checkpoint),
        _round_ledger_envelope(lineage_id, reserved),
    )
    return reserved


def save_checkpoint(
    solver: Solver,
    path: str | Path,
    *,
    evaluation_round: int = 0,
    fresh_replace: bool = False,
) -> Path:
    destination = Path(path)
    rendered = json.dumps(
        _envelope(build_payload(solver, evaluation_round=evaluation_round)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    _guard_output(destination, rendered)
    if fresh_replace and destination.exists():
        # An explicit CLI --overwrite starts a fresh checkpoint generation. Write
        # both related generations without interpreting stale semantic hashes.
        previous = destination.with_name(
            destination.stem + ".previous" + destination.suffix
        )
        _guard_output(previous, rendered)
        _atomic_bytes(previous, rendered)
        _atomic_bytes(destination, rendered)
        return destination
    if destination.exists():
        previous = destination.with_name(destination.stem + ".previous" + destination.suffix)
        try:
            _load_checkpoint_exact(destination)
        except (OSError, ValueError, RuntimeError):
            if not previous.exists():
                raise ValueError(
                    "current checkpoint is invalid and no valid previous generation exists"
                )
            _load_checkpoint_exact(previous)
            # Preserve the valid previous generation; replace only the corrupt current.
        else:
            previous_content = destination.read_bytes()
            _guard_output(previous, previous_content)
            _atomic_bytes(previous, previous_content)
    _atomic_bytes(destination, rendered)
    return destination


def _validate_snapshot(snapshot: Any, config: Config) -> None:
    required = {
        "iterations_completed",
        "traversals_completed",
        "nodes",
        "stop_reason",
        "elapsed_seconds",
        "rng_state",
        "infosets",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != required:
        raise ValueError("checkpoint solver state has an incompatible schema")
    counters = (
        snapshot["iterations_completed"],
        snapshot["traversals_completed"],
        snapshot["nodes"],
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counters):
        raise ValueError("checkpoint counters must be nonnegative integers")
    elapsed = snapshot["elapsed_seconds"]
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(elapsed)
        or elapsed < 0
    ):
        raise ValueError("checkpoint elapsed_seconds must be finite and nonnegative")
    infosets = snapshot["infosets"]
    if not isinstance(infosets, dict) or len(infosets) > config.max_infosets:
        raise ValueError("checkpoint infoset count exceeds configured memory guard")
    allowed_actions = {"fold", "check", "call", "pot"}
    for key, row in infosets.items():
        if not isinstance(key, str) or not isinstance(row, dict) or set(row) != {
            "actions", "regrets", "strategy_sum", "visits"
        }:
            raise ValueError("malformed checkpoint infoset row")
        actions = row["actions"]
        regrets = row["regrets"]
        strategy_sum = row["strategy_sum"]
        visits = row["visits"]
        if (
            not isinstance(actions, list)
            or not actions
            or len(actions) > 3
            or any(action not in allowed_actions for action in actions)
            or not isinstance(regrets, list)
            or not isinstance(strategy_sum, list)
            or len(regrets) != len(actions)
            or len(strategy_sum) != len(actions)
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in regrets + strategy_sum
            )
            or not np.isfinite(np.asarray(regrets, dtype=float)).all()
            or not np.isfinite(np.asarray(strategy_sum, dtype=float)).all()
            or any(value < 0 for value in strategy_sum)
            or isinstance(visits, bool)
            or not isinstance(visits, int)
            or visits < 0
        ):
            raise ValueError("invalid checkpoint infoset values")


def _load_checkpoint_exact(path: str | Path) -> tuple[Solver, int, dict[str, Any]]:
    source = Path(path)
    if source.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint exceeds size guard")
    try:
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("checkpoint is not valid UTF-8 JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"format", "sha256", "payload"}:
        raise ValueError("checkpoint envelope has an incompatible schema")
    if envelope["format"] != FORMAT:
        raise ValueError("unsupported checkpoint format")
    payload = envelope["payload"]
    if not isinstance(payload, dict) or envelope["sha256"] != _digest(payload):
        raise ValueError("checkpoint SHA256 mismatch")
    required = {
        "schema_version",
        "game_fingerprint",
        "config",
        "solver",
        "evaluation_round",
        "source_hashes",
        "dependency_versions",
        "runtime",
    }
    if set(payload) != required or payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("checkpoint payload has an incompatible schema")
    try:
        config = Config.from_dict(payload["config"])
    except ConfigError as exc:
        raise ValueError("invalid checkpoint configuration") from exc
    if payload["game_fingerprint"] != game_fingerprint(config):
        raise ValueError("checkpoint game or abstraction fingerprint mismatch")
    if payload["source_hashes"] != source_hashes():
        raise ValueError("checkpoint semantic source hashes are incompatible")
    if payload["dependency_versions"] != dependency_versions():
        raise ValueError("checkpoint dependency versions are incompatible")
    evaluation_round = payload["evaluation_round"]
    if isinstance(evaluation_round, bool) or not isinstance(evaluation_round, int) or evaluation_round < 0:
        raise ValueError("checkpoint evaluation_round must be a nonnegative integer")
    _validate_snapshot(payload["solver"], config)
    solver = Solver(config)
    try:
        solver.restore_snapshot(payload["solver"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("checkpoint RNG or solver state is malformed") from exc
    return solver, evaluation_round, payload


def load_checkpoint(path: str | Path) -> tuple[Solver, int, dict[str, Any]]:
    source = Path(path)
    try:
        solver, evaluation_round, payload = _load_checkpoint_exact(source)
        payload = dict(payload)
        payload["_loaded_from"] = str(source)
        return solver, evaluation_round, payload
    except (OSError, ValueError, RuntimeError) as current_error:
        previous = source.with_name(source.stem + ".previous" + source.suffix)
        if not previous.exists():
            raise
        try:
            solver, evaluation_round, payload = _load_checkpoint_exact(previous)
        except (OSError, ValueError, RuntimeError):
            raise current_error
        payload = dict(payload)
        payload["_loaded_from"] = str(previous)
        payload["_recovered_current_error"] = str(current_error)
        return solver, evaluation_round, payload


def with_training_limits(
    config: Config,
    *,
    iterations: int,
    seconds: float | None,
    max_infosets: int | None = None,
) -> Config:
    changes: dict[str, Any] = {
        "iterations": iterations,
        "time_limit_seconds": seconds,
    }
    if max_infosets is not None:
        changes["max_infosets"] = max_infosets
    return dataclasses.replace(config, **changes)
