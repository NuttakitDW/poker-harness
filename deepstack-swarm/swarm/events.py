"""The Logbook: every run writes one append-only events.jsonl that the monitor tails.

runs/<stamp>/events.jsonl   one JSON object per line, always with "ts" and "type"
runs/<stamp>/state.json     session ids, so `chat --resume` can pick the run back up
runs/CURRENT                name of the run the chat terminal is writing to

Event types: run_start, user, message, reply, tool, text, state, turn_end, notice, error.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

CURRENT = "CURRENT"
EVENTS = "events.jsonl"
STATE = "state.json"


class EventLog:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.path = run_dir / EVENTS

    def emit(self, type_: str, **fields: Any) -> dict[str, Any]:
        event = {"ts": time.time(), "type": type_, **fields}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event


def new_run(runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = runs_dir / stamp
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = runs_dir / f"{stamp}-{suffix}"
    run_dir.mkdir()
    (runs_dir / CURRENT).write_text(run_dir.name, encoding="utf-8")
    return run_dir


def current_run(runs_dir: Path) -> Path | None:
    pointer = runs_dir / CURRENT
    if not pointer.exists():
        return None
    run_dir = runs_dir / pointer.read_text(encoding="utf-8").strip()
    return run_dir if run_dir.is_dir() else None


def read_state(run_dir: Path) -> dict[str, Any]:
    path = run_dir / STATE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(run_dir: Path, state: dict[str, Any]) -> None:
    tmp = run_dir / (STATE + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(run_dir / STATE)


def read_new(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Events appended since byte `offset`, and the new offset.

    A half-written last line is left for the next call.
    """
    if not path.exists():
        return [], offset
    with path.open("rb") as f:
        f.seek(offset)
        chunk = f.read()
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], offset
    events = []
    for line in chunk[: end + 1].splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a corrupt line must not freeze the monitor
    return events, offset + end + 1
