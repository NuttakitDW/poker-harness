"""Checksummed NPZ checkpoints with atomic manifests and one-generation recovery."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import numba
import numpy as np

from .hands import HandLookup
from .model import DenseModel
from .trainer import FastTrainer
from .tree import PublicTree

FORMAT = "plo-chipev-fast-checkpoint-v1"
SCHEMA_VERSION = 1
MIN_FREE_BYTES = 64 * 1024 * 1024
MAX_DATA_BYTES = 2 * 1024 * 1024 * 1024
GAME = {
    "variant": "PLO4-high",
    "players": 6,
    "stack_bb": 100.0,
    "blinds_bb": [0.5, 1.0],
    "ante_bb": 0.0,
    "rake": 0.0,
    "format": "tournament",
    "utility": "chip_ev_no_icm",
    "postflop": "forced_check_down",
    "max_voluntary_raises": 2,
    "hand_abstraction": "features",
    "averaging_epsilon": 0.05,
    "ordinary_plo_optimum": False,
}
RNG_PROVENANCE = {
    "algorithm": "splitmix64",
    "chance_stream": "separate explicit uint64 state; fresh stream after legacy import",
    "sampling_stream": "separate explicit uint64 state",
    "saved_at_batch_boundary": True,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / "plo_chipev_fast").glob("*.py")) + [
        root / "plo_chipev" / "game.py",
        root / "plo_chipev" / "showdown.py",
        root / "plo_chipev" / "abstraction.py",
        root / "plo_icm" / "game.py",
        root / "plo_icm" / "cards.py",
        root / "plo_icm" / "abstraction.py",
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def dependency_manifest() -> dict[str, str]:
    native_path = Path(__import__("phevaluator")._pheval.__file__).resolve()
    return {
        "python_semantics": f"{sys.version_info.major}.{sys.version_info.minor}",
        "numpy": np.__version__,
        "numba": numba.__version__,
        "llvmlite": importlib.metadata.version("llvmlite"),
        "phevaluator": importlib.metadata.version("phevaluator"),
        "phevaluator_native_sha256": _sha256_file(native_path),
    }


def representation_hash(tree: PublicTree, hands: HandLookup) -> str:
    return hashlib.sha256(
        (tree.representation_hash() + ":" + hands.representation_hash()).encode()
    ).hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, _canonical(value) + b"\n")


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _envelope(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
        "payload": payload,
    }


def _manifest_payload(trainer: FastTrainer, data_file: str, data_sha256: str, data_bytes: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "game": GAME,
        "representation_hash": representation_hash(trainer.model.tree, trainer.model.hands),
        "source_hashes": source_hashes(),
        "dependencies": dependency_manifest(),
        "runtime": {"python": sys.version, "platform": platform.platform()},
        "source_checkpoint_hash": trainer.model.source_checkpoint_hash,
        "rng": RNG_PROVENANCE,
        "trainer": trainer.state_dict(),
        "data_file": data_file,
        "data_sha256": data_sha256,
        "data_bytes": data_bytes,
    }


def _validate_free_space(root: Path, model: DenseModel) -> None:
    estimated = model.regrets.nbytes + model.strategy_sum.nbytes + model.visits.nbytes
    free = shutil.disk_usage(root).free
    if free < estimated + MIN_FREE_BYTES:
        raise OSError(
            f"insufficient free disk for safe checkpoint: need at least {estimated + MIN_FREE_BYTES} bytes"
        )


def save_checkpoint(trainer: FastTrainer, root: Path, *, overwrite: bool = False) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    current_path = root / "checkpoint.json"
    previous_path = root / "checkpoint.previous.json"
    trainer.model.validate()
    _validate_free_space(root, trainer.model)
    current_valid: bytes | None = None
    recovered_previous = False
    fresh_replace = current_path.exists() and overwrite
    if current_path.exists() and not overwrite:
        try:
            _load_manifest_exact(current_path, trainer.model.tree, trainer.model.hands)
        except (OSError, TypeError, ValueError) as current_error:
            if not previous_path.exists():
                raise ValueError(
                    "current checkpoint is invalid and no valid previous generation exists"
                ) from current_error
            _load_manifest_exact(previous_path, trainer.model.tree, trainer.model.hands)
            recovered_previous = True
        else:
            current_valid = current_path.read_bytes()
    token = secrets.token_hex(8)
    data_name = f"generation-{trainer.completed_iterations}-{token}.npz"
    data_path = root / data_name
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{data_name}.", dir=root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as stream:
            np.savez_compressed(
                stream,
                regrets=trainer.model.regrets,
                strategy_sum=trainer.model.strategy_sum,
                visits=trainer.model.visits,
            )
            stream.flush()
            os.fsync(stream.fileno())
        data_bytes = temporary.stat().st_size
        if data_bytes > MAX_DATA_BYTES:
            raise ValueError("checkpoint data exceeds size guard")
        data_sha256 = _sha256_file(temporary)
        os.replace(temporary, data_path)
        _fsync_directory(root)
        manifest = _envelope(
            _manifest_payload(trainer, data_name, data_sha256, data_bytes)
        )
        if current_valid is not None:
            _atomic_bytes(previous_path, current_valid)
        elif fresh_replace:
            _atomic_json(previous_path, manifest)
        elif recovered_previous:
            # Preserve the already validated recovery point; never rotate the
            # corrupt current generation over it.
            pass
        _atomic_json(current_path, manifest)
        _load_manifest_exact(current_path, trainer.model.tree, trainer.model.hands)
        if previous_path.exists():
            _load_manifest_exact(previous_path, trainer.model.tree, trainer.model.hands)
        _cleanup_generations(root, current_path, previous_path)
    finally:
        temporary.unlink(missing_ok=True)
    return current_path


def _load_manifest_exact(
    path: Path, tree: PublicTree, hands: HandLookup
) -> tuple[FastTrainer, dict[str, Any]]:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("checkpoint manifest is missing or corrupt") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"format", "sha256", "payload"}:
        raise ValueError("checkpoint manifest envelope schema is incompatible")
    if envelope["format"] != FORMAT:
        raise ValueError("checkpoint manifest format is incompatible")
    payload = envelope["payload"]
    if not isinstance(payload, dict) or not isinstance(envelope["sha256"], str):
        raise TypeError("checkpoint manifest envelope schema is incompatible")
    if envelope["sha256"] != hashlib.sha256(_canonical(payload)).hexdigest():
        raise ValueError("checkpoint manifest SHA256 mismatch")
    required = {
        "schema_version", "game", "representation_hash", "source_hashes",
        "dependencies", "runtime", "source_checkpoint_hash", "rng", "trainer",
        "data_file", "data_sha256", "data_bytes",
    }
    if set(payload) != required or payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("checkpoint manifest schema is incompatible")
    if payload["game"] != GAME:
        raise ValueError("checkpoint game configuration is incompatible")
    if payload["rng"] != RNG_PROVENANCE:
        raise ValueError("checkpoint RNG provenance is incompatible")
    if payload["representation_hash"] != representation_hash(tree, hands):
        raise ValueError("checkpoint representation hash is incompatible")
    if payload["source_hashes"] != source_hashes():
        raise ValueError("checkpoint source hashes are incompatible")
    if payload["dependencies"] != dependency_manifest():
        raise ValueError("checkpoint dependency manifest is incompatible")
    runtime = payload["runtime"]
    if (
        not isinstance(runtime, dict)
        or set(runtime) != {"python", "platform"}
        or not all(isinstance(value, str) for value in runtime.values())
    ):
        raise ValueError("checkpoint runtime provenance is invalid")
    source_checkpoint_hash = payload["source_checkpoint_hash"]
    if source_checkpoint_hash is not None and (
        not isinstance(source_checkpoint_hash, str)
        or len(source_checkpoint_hash) != 64
        or any(character not in "0123456789abcdef" for character in source_checkpoint_hash)
    ):
        raise ValueError("checkpoint source checkpoint hash is invalid")
    FastTrainer.validate_state(payload["trainer"])
    data_file = payload["data_file"]
    if not isinstance(data_file, str) or Path(data_file).name != data_file:
        raise ValueError("checkpoint data filename is unsafe")
    data_bytes = payload["data_bytes"]
    if (
        isinstance(data_bytes, bool)
        or not isinstance(data_bytes, int)
        or not 0 < data_bytes <= MAX_DATA_BYTES
    ):
        raise ValueError("checkpoint data size is invalid")
    data_sha256 = payload["data_sha256"]
    if (
        not isinstance(data_sha256, str)
        or len(data_sha256) != 64
        or any(character not in "0123456789abcdef" for character in data_sha256)
    ):
        raise ValueError("checkpoint data SHA256 is invalid")
    data_path = path.parent / data_file
    if data_path.stat().st_size != data_bytes:
        raise ValueError("checkpoint data size mismatch")
    if _sha256_file(data_path) != data_sha256:
        raise ValueError("checkpoint data SHA256 mismatch")
    try:
        with np.load(data_path, allow_pickle=False) as archive:
            if set(archive.files) != {"regrets", "strategy_sum", "visits"}:
                raise ValueError("checkpoint array schema is incompatible")
            model = DenseModel(
                tree=tree,
                hands=hands,
                regrets=archive["regrets"].copy(),
                strategy_sum=archive["strategy_sum"].copy(),
                visits=archive["visits"].copy(),
                source_checkpoint_hash=source_checkpoint_hash,
            )
    except (OSError, ValueError) as exc:
        raise ValueError("checkpoint NPZ is invalid") from exc
    model.validate()
    trainer = FastTrainer.from_state(model, payload["trainer"])
    return trainer, payload


def _cleanup_generations(root: Path, current: Path, previous: Path) -> None:
    referenced: set[str] = set()
    for path in (current, previous):
        if not path.exists():
            continue
        envelope = json.loads(path.read_text(encoding="utf-8"))
        referenced.add(envelope["payload"]["data_file"])
    for path in root.glob("generation-*.npz"):
        if path.name not in referenced:
            path.unlink()
    _fsync_directory(root)


def load_checkpoint(
    root: Path, tree: PublicTree, hands: HandLookup
) -> tuple[FastTrainer, dict[str, Any]]:
    root = Path(root)
    current = root / "checkpoint.json"
    try:
        trainer, manifest = _load_manifest_exact(current, tree, hands)
        return trainer, {**manifest, "loaded_generation": "current"}
    except (OSError, TypeError, ValueError) as current_error:
        previous = root / "checkpoint.previous.json"
        if not previous.exists():
            raise
        try:
            trainer, manifest = _load_manifest_exact(previous, tree, hands)
        except (OSError, TypeError, ValueError):
            raise current_error
        return trainer, {
            **manifest,
            "loaded_generation": "previous",
            "recovered_current_error": str(current_error),
        }
