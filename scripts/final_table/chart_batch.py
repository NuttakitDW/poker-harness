"""Solve chip-EV preflop charts for several table sizes and stacks, two seeds each.

Every table is symmetric: each seat has ``stack`` bb after posting a 0.116bb ante (the ante is
added on top). Each (seats, stack) runs ``solve-full`` twice, then ``export-chart`` writes
tmp/plo_premium_proof/charts/<seats>max-<stack>bb. Progress goes to tmp/final_table/batch.json for
the local page's Training tab. Big models are deleted after export to keep the disk free; the chart
keeps the averaged preflop strategy.

    .venv/bin/python scripts/final_table/chart_batch.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import progress  # noqa: E402

PROOF = ROOT / "tmp" / "plo_premium_proof"
BATCH = ROOT / "tmp" / "final_table" / "batch.json"
JOBS = ROOT / "tmp" / "final_table" / "jobs"
ANTE = 0.116
CAPS = "4,2,2,2"
# Minutes per seed, scaled to tree size (6-max 100bb matches the earlier 4-hour runs).
MINUTES = {
    (2, 10): 4, (3, 10): 8, (4, 10): 15, (5, 10): 30, (6, 10): 60,
    (2, 20): 4, (2, 40): 4, (2, 100): 6,
    (3, 20): 8, (3, 40): 8, (3, 100): 15,
    (4, 20): 15, (4, 40): 25, (4, 100): 60,
    (5, 20): 30, (5, 40): 75, (5, 100): 150,
    (6, 20): 60, (6, 40): 150, (6, 100): 240,
}
KEEP_MODEL_GB = 1.0   # delete models bigger than this after the chart is written
SEEDS = (1, 2)


def name(seats: int, stack: int) -> str:
    return f"{seats}max-{stack}bb"


def solve(seats: int, stack: int, seed: int, minutes: float, job: str, log) -> int:
    out = PROOF / f"{name(seats, stack)}-seed-{seed}"
    status = JOBS / job / "status.json"
    command = [sys.executable, "-u", "-m", "plo_premium_proof", "solve-full", "--output", str(out),
               "--minutes", str(minutes), "--stack", str(stack), "--ante", str(ANTE), "--ante-on-top",
               "--seats", str(seats), "--raise-caps", CAPS, "--float32", "--threads", str(os.cpu_count() or 1),
               "--seed", str(seed)]
    started = time.time()
    process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    while process.poll() is None:
        progress.write_json(status, {"state": "solving", "seconds": round(time.time() - started),
                                     "budget_seconds": minutes * 60})
        time.sleep(10)
    progress.write_json(status, {"state": "done" if process.returncode == 0 else "failed",
                                 "seconds": round(time.time() - started), "budget_seconds": minutes * 60})
    return process.returncode


def main() -> int:
    plan = sorted(MINUTES, key=lambda k: (k[0], k[1]))
    items = [{"label": f"{name(s, b)} chip EV · seed {seed}", "minutes": MINUTES[(s, b)], "seats": s,
              "state": "queued", "job": None, "key": [s, b, seed]} for s, b in plan for seed in SEEDS]
    batch = {"name": "short-handed charts", "pid": os.getpid(), "started": time.time(), "state": "running",
             "items": items}
    progress.write_json(BATCH, batch)
    log_path = PROOF / "chart_batch.log"
    try:
        with log_path.open("a") as log:
            for seats, stack in plan:
                chart = PROOF / "charts" / name(seats, stack)
                models = [PROOF / f"{name(seats, stack)}-seed-{seed}" / "model.npz" for seed in SEEDS]
                for seed in SEEDS:
                    item = next(i for i in items if i["key"] == [seats, stack, seed])
                    if (chart / "meta.json").exists() or models[seed - 1].exists() and \
                            json.loads(_meta(models[seed - 1])).get("seconds", 0) >= MINUTES[(seats, stack)] * 60 - 30:
                        item.update(state="skipped")
                        continue
                    job = f"chart-{name(seats, stack)}-s{seed}"
                    item.update(state="running", job=job, started=time.time())
                    progress.write_json(BATCH, batch)
                    log.write(f"\n== {item['label']} {time.ctime()}\n")
                    log.flush()
                    code = solve(seats, stack, seed, MINUTES[(seats, stack)], job, log)
                    item.update(state="done" if code == 0 else "failed", finished=time.time())
                    progress.write_json(BATCH, batch)
                    if code:
                        raise RuntimeError(f"{item['label']} failed with exit {code}; see {log_path}")
                if not (chart / "meta.json").exists():
                    subprocess.run([sys.executable, "-m", "plo_premium_proof", "export-chart", "--name",
                                    name(seats, stack), "--models", *map(str, models)],
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
                    for model in models:
                        if model.exists() and model.stat().st_size > KEEP_MODEL_GB * 1e9:
                            model.unlink()
        batch["state"] = "done"
    except KeyboardInterrupt:
        batch["state"] = "stopped"
    except Exception as error:  # noqa: BLE001 - recorded for the progress page, then re-raised
        batch["state"] = "failed"
        batch["error"] = str(error)
        raise
    finally:
        batch["finished"] = time.time()
        progress.write_json(BATCH, batch)
    return 0


def _meta(model: Path) -> str:
    import numpy as np
    with np.load(model) as data:
        return str(data["meta"])


if __name__ == "__main__":
    sys.exit(main())
