"""Solve chosen hands from a GG tournament history one after another (an overnight batch).

Each hand becomes an ICM spec: the real table in preflop order, the tournament's payouts,
players left estimated from the history (``gg_history.players_left_curve``) and the rest of
the chips spread over the other tables. Solves land in tmp/final_table/jobs/<id>/ like the
ones started from the page, so ``make ft`` lists and explores them. Finished labels are
skipped on a rerun. Progress goes to tmp/final_table/batch.json for the page's Training tab.

    .venv/bin/python scripts/final_table/mtt_batch.py --history "GG...txt" --entries 374 \
        --start-stack 50000 --payouts payouts.json --pin TM191037843:14 --hands TM1,TM2,...
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gg_history  # noqa: E402
import progress  # noqa: E402

from plo_premium_proof.finaltable import STATUS, FinalTableSpec  # noqa: E402

JOBS = ROOT / "tmp" / "final_table" / "jobs"
BATCH = ROOT / "tmp" / "final_table" / "batch.json"


def spec_for(hand: gg_history.Hand, left: int, total_chips: float, payouts: tuple[float, ...],
             minutes: float) -> FinalTableSpec:
    stacks = hand.stacks_bb
    total_bb = total_chips / hand.bb
    field = (total_bb - sum(stacks)) / (left - len(stacks)) if left > len(stacks) else 0.0
    label = f"{hand.hand_id} {hand.hero_seat} {hand.hero_cards} · L{hand.level} · ~{left} left"
    return FinalTableSpec(stacks=stacks, payouts=payouts, ante_bb=round(hand.ante / hand.bb, 4),
                          minutes=minutes, hero=hand.hero_seat, hand=hand.hero_cards,
                          players_left=left if left > len(stacks) else 0,
                          field_stack_bb=round(field, 2), label=label)


def finished_labels(jobs: Path) -> set[str]:
    done = set()
    for folder in jobs.glob("*-*"):
        spec, status = folder / "spec.json", folder / STATUS
        if spec.exists() and status.exists() and json.loads(status.read_text()).get("state") == "done":
            done.add(json.loads(spec.read_text()).get("label"))
    return done


def new_job(spec: FinalTableSpec, jobs: Path) -> str:
    while True:
        job = time.strftime("%Y%m%d-%H%M%S")
        folder = jobs / job
        if not folder.exists():
            break
        time.sleep(1)
    folder.mkdir(parents=True)
    (folder / "spec.json").write_text(json.dumps(spec.to_dict(), indent=1))
    return job


def run(job: str, jobs: Path) -> None:
    folder = jobs / job
    with (folder / "log.txt").open("w") as log:
        code = subprocess.call([sys.executable, "-m", "plo_premium_proof", "ft-solve", "--spec",
                                str(folder / "spec.json"), "--output", str(folder)],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if code:
        (folder / STATUS).write_text(json.dumps({"state": "failed", "exit": code}))


def run_batch(specs: list[FinalTableSpec], jobs: Path, batch_file: Path, name: str) -> dict:
    """Solve ``specs`` in order, keeping ``batch_file`` current for the progress page."""
    jobs.mkdir(parents=True, exist_ok=True)
    done = finished_labels(jobs)
    batch = {"name": name, "pid": os.getpid(), "started": time.time(), "state": "running",
             "items": [{"label": s.label, "minutes": s.minutes, "seats": len(s.stacks),
                        "state": "skipped" if s.label in done else "queued", "job": None}
                       for s in specs]}
    progress.write_json(batch_file, batch)
    try:
        for number, (spec, item) in enumerate(zip(specs, batch["items"]), 1):
            if item["state"] == "skipped":
                print(f"[{number}/{len(specs)}] skip (done) {spec.label}", flush=True)
                continue
            item.update(state="running", job=new_job(spec, jobs), started=time.time())
            progress.write_json(batch_file, batch)
            run(item["job"], jobs)
            status = json.loads((jobs / item["job"] / STATUS).read_text())
            item.update(state="done" if status.get("state") == "done" else "failed", finished=time.time())
            progress.write_json(batch_file, batch)
            print(f"[{number}/{len(specs)}] {item['job']} {item['state']} in "
                  f"{(item['finished'] - item['started']) / 60:.1f} min  {spec.label}", flush=True)
        batch["state"] = "done"
    except KeyboardInterrupt:
        batch["state"] = "stopped"
    finally:
        batch["finished"] = time.time()
        progress.write_json(batch_file, batch)
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--entries", type=int, required=True, help="entries incl. re-entries")
    parser.add_argument("--start-stack", type=float, required=True, help="chips per entry")
    parser.add_argument("--payouts", type=Path, required=True, help="JSON list, 1st place first")
    parser.add_argument("--pin", required=True, help="HANDID:PLAYERS_LEFT anchoring the estimate")
    parser.add_argument("--hands", required=True, help="comma-separated hand ids, solved in this order")
    parser.add_argument("--minutes", default="5:10,6:18,7:22", help="solve minutes by seat count")
    parser.add_argument("--from-level", type=int, default=14, help="first level used to fit players left")
    parser.add_argument("--dry-run", action="store_true", help="print the specs and stop")
    args = parser.parse_args()

    hands = gg_history.read_hands(args.history)
    by_id = {h.hand_id: h for h in hands}
    pin_id, pin_left = args.pin.split(":")
    total = args.entries * args.start_stack
    left = gg_history.players_left_curve(hands, total, pin=(pin_id, int(pin_left)), from_level=args.from_level)
    payouts = tuple(float(x) for x in json.loads(args.payouts.read_text()))
    minutes = {int(k): float(v) for k, v in (part.split(":") for part in args.minutes.split(","))}
    wanted = [x.strip() for x in args.hands.split(",") if x.strip()]
    missing = [x for x in wanted if x not in by_id]
    if missing:
        parser.error(f"hands not in the history: {', '.join(missing)}")
    specs = [spec_for(by_id[x], left(by_id[x]), total, payouts, minutes.get(len(by_id[x].players), 15.0))
             for x in wanted]
    for spec in specs:
        print(f"{spec.minutes:4.0f} min  {spec.label}  field {spec.field_stack_bb}bb  stacks {spec.stacks}")
    print(f"total {sum(s.minutes for s in specs) / 60:.1f} h of solving", flush=True)
    if args.dry_run:
        return 0
    batch = run_batch(specs, JOBS, BATCH, args.history.stem)
    return 0 if batch["state"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
