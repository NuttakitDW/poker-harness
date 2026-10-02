"""Progress of the long jobs behind the solver: the spot library batch and network training.

Both write a small JSON file the page polls (``/api/progress``):

* ``tmp/final_table/batch.json`` -- written by ``mtt_batch.py``: one item per spot with its
  state (queued, running, done, failed, skipped), job id and times.
* ``tmp/final_table/training/status.json`` -- written by the network trainer: state, epoch,
  epochs, loss histories, held-out gap, best epoch. Passed through as written.

The page reads; it never starts or stops these jobs.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

OVERHEAD_MINUTES = 1.0   # tree build + ICM pricing + compile per spot, until measured


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=1))
    os.replace(temporary, path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def library(batch_file: Path, jobs: Path, now: float | None = None) -> dict[str, Any] | None:
    """The batch's counts, current spot and time left; None when no batch has run."""
    batch = _read(batch_file)
    if not batch or not isinstance(batch.get("items"), list):
        return None
    now = time.time() if now is None else now
    items = batch["items"]
    count = {state: sum(1 for i in items if i.get("state") == state)
             for state in ("queued", "running", "done", "failed", "skipped")}
    finished = [i for i in items if i.get("state") == "done" and i.get("started") and i.get("finished")]
    overhead = (sum((i["finished"] - i["started"]) / 60 - i.get("minutes", 0) for i in finished) / len(finished)
                if finished else OVERHEAD_MINUTES)
    overhead = max(0.0, overhead)
    state = batch.get("state", "running")
    if state == "running" and not _alive(batch.get("pid")):
        state = "interrupted"

    current = None
    left = sum(i.get("minutes", 0) + overhead for i in items if i.get("state") == "queued") * 60
    running = next((i for i in items if i.get("state") == "running"), None)
    if running and state == "running":
        status = _read(jobs / str(running.get("job")) / "status.json") or {}
        budget = float(status.get("budget_seconds") or running.get("minutes", 0) * 60)
        seconds = float(status.get("seconds") or 0)
        current = {"label": running.get("label"), "job": running.get("job"), "seats": running.get("seats"),
                   "state": status.get("state", "starting"), "seconds": seconds, "budget": budget,
                   "deals": status.get("deals"), "elapsed": now - running.get("started", now)}
        left += max(0.0, budget - seconds) + (overhead * 60 if seconds == 0 else 0)
    if state != "running":
        left = 0.0
    return {
        "name": batch.get("name"), "state": state, "started": batch.get("started"),
        "elapsed": (batch.get("finished") or now) - batch.get("started", now),
        "total": len(items) - count["skipped"], "done": count["done"], "failed": count["failed"],
        "queued": count["queued"], "eta_seconds": round(left), "finish_at": now + left if left else None,
        "overhead_minutes": round(overhead, 2), "current": current,
        "recent": [{"label": i.get("label"), "state": i.get("state"), "job": i.get("job"),
                    "minutes": round((i["finished"] - i["started"]) / 60, 1) if i.get("finished") else None}
                   for i in items if i.get("state") in ("done", "failed")][-8:][::-1],
        "next": [i.get("label") for i in items if i.get("state") == "queued"][:5],
    }


def training(status_file: Path) -> dict[str, Any] | None:
    status = _read(status_file)
    if not status:
        return None
    if status.get("state") == "running" and not _alive(status.get("pid")):
        status = {**status, "state": "interrupted"}
    return status


def snapshot(root: Path, jobs: Path) -> dict[str, Any]:
    existing = next(p for p in (root, *root.parents) if p.exists())
    disk = shutil.disk_usage(existing)
    return {"library": library(root / "batch.json", jobs), "training": training(root / "training" / "status.json"),
            "disk_free_gb": round(disk.free / 1e9, 1), "now": time.time()}
