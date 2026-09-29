"""Reproducible fixed-budget runner for the restricted-action PLO ICM pilot."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import dataclasses
import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "voice"))

import plo_type  # noqa: E402
from plo_icm.cards import parse_cards  # noqa: E402
from plo_icm.config import sunday_classic_mini  # noqa: E402
from plo_icm.hand_advice import solve_hand  # noqa: E402

VERSION = "plo-archetype-study-v1"
POSITIONS = {"UTG": 0, "HJ": 1, "CO": 2, "BTN": 3, "SB": 4}
SEEDS = (17, 29, 43)
STAGES = (76, 60)
COHORT = (
    ("premium_aakk", "AsAhKsKh", "Premium"),
    ("premium_jt98", "JsTc9s8c", "Premium"),
    ("speculative_aa82", "AsAc8d2h", "Speculative"),
    ("speculative_a986", "Ad9d8s6s", "Speculative"),
    ("marginal_jj63", "JdJc6c3s", "Marginal"),
    ("marginal_kjt9", "KdJhTd9s", "Marginal"),
    ("trash_9753", "9h7d5c3s", "Trash"),
    ("trash_qj76", "QsJs7c6c", "Trash"),
)
PILOT = (
    ("premium_aakk", "AsAhKsKh", "Premium", "UTG", 76, 17),
    ("speculative_a986", "Ad9d8s6s", "Speculative", "BTN", 60, 17),
    ("marginal_jj63", "JdJc6c3s", "Marginal", "SB", 76, 17),
    ("trash_qj76", "QsJs7c6c", "Trash", "BTN", 60, 17),
)
SENSITIVITY_HAND_IDS = {"premium_aakk", "speculative_aa82", "marginal_jj63", "trash_9753"}


def validate_cohort() -> None:
    for _, cards, expected in COHORT:
        asked = plo_type.lookup(cards)
        actual = plo_type.classify(asked.hand).tier if asked and asked.hand else None
        if actual != expected:
            raise RuntimeError(f"cohort tier drift for {cards}: expected {expected}, got {actual}")


def _source_paths() -> tuple[Path, ...]:
    drills = sorted((ROOT / "harnesses" / "EN" / "sources" / "web").glob(
        "plo-starting-hands-classify-*.md"))
    return (Path(__file__), *sorted((ROOT / "plo_icm").glob("*.py")),
            *sorted((ROOT / "pushfold").glob("*.py")),
            *sorted((ROOT / "scripts" / "voice").glob("*.py")),
            *drills)


def _source_hash() -> str:
    digest = hashlib.sha256()
    for path in _source_paths():
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _mode(value: str | bool) -> str:
    return "pilot" if value is True else "main" if value is False else value


def _manifest(max_nodes: int, eval_attempts: int, timeout: float, wall_limit: float,
              mode: str | bool) -> dict:
    mode = _mode(mode)
    try:
        revision = os.getenv("PLO_STUDY_GIT_REVISION") or subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            capture_output=True, check=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        revision = "unavailable"
    return {
        "version": VERSION, "source_sha256": _source_hash(), "git_revision": revision,
        "python": platform.python_version(), "numpy": importlib.metadata.version("numpy"),
        "pokerkit": importlib.metadata.version("pokerkit"),
        "max_nodes": max_nodes, "eval_attempts": eval_attempts, "timeout_seconds": timeout,
        "wall_limit_seconds": wall_limit,
        "opening_raise_mode": "two_bb_only", "stacks_before_posts_bb": 10,
        "ante_bb": .1, "ante_mode": "individual", "rake": 0,
        "stages": list(STAGES), "seeds": list(SEEDS), "positions": list(POSITIONS),
        "cohort": [list(row) for row in COHORT], "mode": mode,
    }


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _cell_id(cell: tuple) -> str:
    hand_id, _, _, position, remaining, seed = cell
    return f"{hand_id}__{position.lower()}__left{remaining}__seed{seed}"


def cells(mode: str | bool = "main") -> tuple[tuple, ...]:
    mode = _mode(mode)
    if mode == "pilot":
        return PILOT
    if mode == "sensitivity":
        return tuple((*hand, "BTN", 76, seed) for hand in COHORT
                     if hand[0] in SENSITIVITY_HAND_IDS for seed in SEEDS)
    return tuple((*hand, position, remaining, seed)
                 for hand in COHORT for position in POSITIONS
                 for remaining in STAGES for seed in SEEDS)


def run_cell(cell: tuple, max_nodes: int, eval_attempts: int, timeout: float,
             source_sha256: str) -> dict:
    hand_id, card_text, tier, position, remaining, seed = cell
    began = time.perf_counter()
    cfg = sunday_classic_mini(players_remaining=remaining, stack=10, ante=.1,
                              ante_mode="individual", iterations=1_000_000, seed=seed,
                              time_limit=timeout, max_nodes=max_nodes, max_infosets=100_000,
                              opening_raise_mode="two_bb_only")
    payload = {
        "study_version": VERSION, "source_sha256": source_sha256, "cell_id": _cell_id(cell),
        "hand_id": hand_id, "cards": card_text, "tier": tier, "position": position,
        "seat": POSITIONS[position], "players_remaining": remaining, "seed": seed,
        "config": cfg.to_dict(), "eval_attempts_requested": eval_attempts,
    }
    try:
        if _source_hash() != source_sha256:
            raise RuntimeError("study source changed after manifest freeze")
        advice = solve_hand(cfg, POSITIONS[position], parse_cards(card_text, 4),
                            train_seconds=timeout, eval_seconds=timeout,
                            eval_attempts=eval_attempts,
                            eval_seed=seed * 100_000 + remaining * 10 + POSITIONS[position],
                            min_samples=1)
        training_complete = (advice.training.get("stop_reason") == "max_nodes"
                             and advice.training.get("nodes", 0) >= max_nodes)
        payload.update({
            "status": "complete" if advice.evaluation_complete and training_complete else "truncated",
            "selected_action": advice.action, "selected_amount_bb": advice.amount,
            "action_amounts_bb": advice.amounts, "action_ev_dollars": advice.values.ev,
            "se_vs_selected_dollars": advice.values.se_vs_best,
            "pairwise_se_dollars": advice.values.pairwise_se,
            "effective_sample_size": advice.values.ess, "complete_paired_samples": advice.samples,
            "evaluation_attempts_completed": advice.evaluation_attempts,
            "uniform_fallback_fraction": advice.untrained_fraction,
            "training": advice.training, "interpretation": advice.label,
            "training_budget_complete": training_complete,
        })
    except Exception as exc:  # Cell failures are research data and must not abort the grid.
        payload.update({"status": "error", "error_type": type(exc).__name__, "error": str(exc)})
    payload["wall_seconds"] = time.perf_counter() - began
    raw_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    payload["peak_rss_mb"] = raw_rss / (1024 * 1024) if sys.platform == "darwin" else raw_rss / 1024
    return payload


def _prepare(output: Path, manifest: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "manifest.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise RuntimeError("output manifest differs; choose a new output directory")
    else:
        _atomic_json(path, manifest)
        snapshot = output / "source_snapshot"
        for source in _source_paths():
            relative = source.relative_to(ROOT)
            destination = snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def _existing_complete(path: Path, cell: tuple, manifest: dict) -> bool:
    if not path.exists():
        return False
    row = json.loads(path.read_text(encoding="utf-8"))
    hand_id, cards, tier, position, remaining, seed = cell
    expected = _cell_id(cell)
    config = row.get("config", {})
    expected_config = sunday_classic_mini(
        players_remaining=remaining, stack=10, ante=.1, ante_mode="individual",
        iterations=1_000_000, seed=seed, time_limit=manifest["timeout_seconds"],
        max_nodes=manifest["max_nodes"], max_infosets=100_000,
        opening_raise_mode=manifest["opening_raise_mode"]).to_dict()
    expected_config = json.loads(json.dumps(expected_config))
    valid = (row.get("cell_id") == expected
             and row.get("source_sha256") == manifest["source_sha256"]
             and row.get("eval_attempts_requested") == manifest["eval_attempts"]
             and row.get("hand_id") == hand_id and row.get("cards") == cards
             and row.get("tier") == tier and row.get("position") == position
             and row.get("players_remaining") == remaining and row.get("seed") == seed
             and config == expected_config)
    if not valid:
        raise RuntimeError(f"existing cell does not match manifest: {path.name}")
    return row.get("status") == "complete"


def run_grid(output: Path, max_nodes: int, eval_attempts: int, timeout: float,
             wall_limit: float, workers: int, mode: str) -> dict:
    validate_cohort()
    manifest = _manifest(max_nodes, eval_attempts, timeout, wall_limit, mode)
    _prepare(output, manifest)
    todo = [cell for cell in cells(mode)
            if not _existing_complete(output / "cells" / f"{_cell_id(cell)}.json", cell, manifest)]
    completed = Counter()
    began = time.monotonic()
    stopped_for_wall = False
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        iterator = iter(todo)
        futures = {}
        for _ in range(workers):
            cell = next(iterator, None)
            if cell is not None:
                futures[pool.submit(run_cell, cell, max_nodes, eval_attempts, timeout,
                                    manifest["source_sha256"])] = cell
        while futures:
            done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                futures.pop(future)
                payload = future.result()
                _atomic_json(output / "cells" / f"{payload['cell_id']}.json", payload)
                completed[payload["status"]] += 1
                print(payload["cell_id"], payload["status"], f"{payload['wall_seconds']:.2f}s", flush=True)
                if time.monotonic() - began >= wall_limit:
                    stopped_for_wall = True
                    continue
                cell = next(iterator, None)
                if cell is not None:
                    futures[pool.submit(run_cell, cell, max_nodes, eval_attempts, timeout,
                                        manifest["source_sha256"])] = cell
    result = {"scheduled": len(todo), "status_counts": dict(completed),
              "total_cells": len(cells(mode)), "output": str(output)}
    result["stopped_for_wall_limit"] = stopped_for_wall
    _atomic_json(output / "run_status.json", result)
    return result


def summarize(output: Path) -> dict:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    expected_cells = cells(manifest["mode"])
    expected_ids = {_cell_id(cell) for cell in expected_cells}
    paths = sorted((output / "cells").glob("*.json"))
    unexpected = [path.name for path in paths if path.stem not in expected_ids]
    if unexpected:
        raise RuntimeError("unexpected cell files: " + ", ".join(unexpected))
    rows = []
    for cell in expected_cells:
        path = output / "cells" / f"{_cell_id(cell)}.json"
        if path.exists():
            _existing_complete(path, cell, manifest)  # validates identity even when truncated/error
            rows.append(json.loads(path.read_text(encoding="utf-8")))
    completed = [row for row in rows if row.get("status") == "complete"]
    tables = output / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    columns = ("cell_id", "status", "tier", "cards", "position", "players_remaining", "seed",
               "selected_action", "ev_fold", "ev_call", "ev_raise_2bb",
               "contrast_raise_minus_limp", "se_raise_minus_limp",
               "contrast_limp_minus_fold", "se_limp_minus_fold",
               "complete_paired_samples", "effective_sample_size", "uniform_fallback_fraction",
               "training_nodes", "training_iterations", "training_stop_reason", "wall_seconds")
    with (tables / "completed_cells.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            ev = row.get("action_ev_dollars", {})
            pair = row.get("pairwise_se_dollars", {})
            training = row.get("training", {})
            flat = dict(row, ev_fold=ev.get("fold"), ev_call=ev.get("call"),
                        ev_raise_2bb=ev.get("raise_2bb"),
                        contrast_raise_minus_limp=(ev.get("raise_2bb") - ev.get("call")
                                                   if ev.get("raise_2bb") is not None and ev.get("call") is not None else None),
                        se_raise_minus_limp=pair.get("raise_2bb|call"),
                        contrast_limp_minus_fold=(ev.get("call") - ev.get("fold")
                                                  if ev.get("call") is not None and ev.get("fold") is not None else None),
                        se_limp_minus_fold=pair.get("call|fold"), training_nodes=training.get("nodes"),
                        training_iterations=training.get("iterations_completed"),
                        training_stop_reason=training.get("stop_reason"))
            writer.writerow({key: flat.get(key) for key in columns})
    counts = Counter((row["tier"], row["selected_action"]) for row in completed)
    actions = ("fold", "call", "raise_2bb")
    latex = ["% Generated only from complete study cells.",
             "\\begin{tabular}{lrrr}", "\\toprule",
             "Tier & Fold & Limp/Call & Raise to 2bb \\\\", "\\midrule"]
    for tier in ("Premium", "Speculative", "Marginal", "Trash"):
        latex.append(f"{tier} & {counts[tier, actions[0]]} & {counts[tier, actions[1]]} & "
                     f"{counts[tier, actions[2]]} \\\\")
    latex += ["\\bottomrule", "\\end{tabular}"]
    (tables / "action_counts.tex").write_text("\n".join(latex) + "\n", encoding="utf-8")
    summary = {"cells_expected": len(expected_cells), "cells_found": len(rows), "complete": len(completed),
               "missing": len(expected_cells) - len(rows),
               "status_counts": dict(Counter(row.get("status", "unknown") for row in rows)),
               "action_counts": {f"{tier}|{action}": count for (tier, action), count in counts.items()}}
    _atomic_json(output / "summary.json", summary)
    return summary


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser()
    command.add_argument("mode", choices=("pilot", "run", "sensitivity", "summarize"))
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--max-nodes", type=int, default=5000)
    command.add_argument("--eval-attempts", type=int, default=128)
    command.add_argument("--timeout", type=float, default=60)
    command.add_argument("--wall-limit", type=float, default=3600)
    command.add_argument("--workers", type=int, choices=(1, 2), default=2)
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    args.output = args.output.resolve()
    if args.mode == "summarize":
        print(json.dumps(summarize(args.output), indent=2))
    else:
        study_mode = "main" if args.mode == "run" else args.mode
        if os.getenv("PLO_STUDY_FROZEN") != "1":
            manifest = _manifest(args.max_nodes, args.eval_attempts, args.timeout,
                                 args.wall_limit, study_mode)
            _prepare(args.output, manifest)
            frozen = args.output / "source_snapshot" / "research" / "plo_icm_archetypes" / "run_study.py"
            environment = os.environ.copy()
            environment["PLO_STUDY_FROZEN"] = "1"
            environment["PLO_STUDY_GIT_REVISION"] = manifest["git_revision"]
            command = [sys.executable, str(frozen), args.mode, "--output", str(args.output),
                       "--max-nodes", str(args.max_nodes), "--eval-attempts", str(args.eval_attempts),
                       "--timeout", str(args.timeout), "--wall-limit", str(args.wall_limit),
                       "--workers", str(args.workers)]
            return subprocess.run(command, env=environment, check=False).returncode
        print(json.dumps(run_grid(args.output, args.max_nodes, args.eval_attempts,
                                  args.timeout, args.wall_limit, args.workers, study_mode), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
