"""Refuse to call a cell quotable unless its record matches the run it claims to belong to.

This is the checklist from TEAM.md / SOUL.md turned into a program, so that "which code, which
build, which game, exact or bound" is answered by the artifact rather than by my memory of it.
Exit status is 1 if any cell is not quotable.

    .venv/bin/python verify_cells.py            # checks cells/, prints a per-cell verdict
    .venv/bin/python verify_cells.py --quiet    # only failures
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import provenance as prov

HERE = Path(__file__).resolve().parent
CELLS = HERE / "cells"

# Every field a quotable record must have. `x: str` means non-empty string, `x: number` a number.
REQUIRED = {
    "cell": str, "setting": str, "stage": str, "n": int, "stack": (int, float),
    "left": int, "target": (int, float), "lifetime_eps": (int, float),
    "check_every": int, "method": str,
    "commit": str, "unit": str, "auditor": str,          # what was run
    "code_fingerprint": str, "code": dict,               # which code
    "build": dict, "cap": int, "stacks": list,           # which build / which game
    "crowd": int, "prizes_paid": int, "nodes": int, "terminals": int, "counts": dict,
    "converged": bool, "iters": int, "seconds": (int, float),
    "history": list, "final_gain": (int, float),
}

# johanson, `johanson-model-vs-real-gap.md` (revised): the model's own error in the best-response
# gain, model vs real deal, in ICM chips/hand. NOT a per-seat-count constant -- it spans ~5x with
# stack and stage WITHIN n=3 (0.0024-0.0121). The values below are the tighter end of the measured
# range at each seat count, i.e. deliberately conservative as a ceiling: a cell that stops below
# these is certainly below its bar, which is the direction an acceptance check should err in.
MODEL_FIDELITY = {3: 0.0055, 6: 0.0075, 9: 0.0119}
# davis, `davis-grid-sigma.md` Sec 2: the lifetime eps of a heads-up cell by stack. Heads-up pricing
# is exact so the model error is ~0 and the lifetime bar binds.
EPS_N2 = {8.0: 0.00059, 12.0: 0.00071, 15.0: 0.00077, 20.0: 0.00082, 30.0: 0.00099}


def check_cell(rec: dict, run: dict) -> list[str]:
    bad = []
    for field, kind in REQUIRED.items():
        if field not in rec:
            bad.append(f"missing {field!r}")
        elif not isinstance(rec[field], kind) or rec[field] == "":
            bad.append(f"{field}={rec[field]!r} is not {kind}")

    if "error" in rec:
        bad.append(f"errored: {rec['error']}")
        return bad  # nothing else is meaningful

    # Provenance: the cell must belong to the frozen run, and the code must be the frozen code.
    if rec.get("code_fingerprint") != run["code_fingerprint"]:
        bad.append(f"fingerprint {rec.get('code_fingerprint')} != run {run['code_fingerprint']}")
    if rec.get("code") != run["code"]:
        diff = {k: (rec.get("code", {}).get(k), v) for k, v in run["code"].items()
                if rec.get("code", {}).get(k) != v}
        bad.append(f"module digests differ from the run manifest: {diff}")
    if rec.get("build") != run["build"]:
        bad.append(f"build {rec.get('build')} != run {run['build']}")

    # The game. The grid is equal stacks, so all n stacks must equal the cell's stack.
    if rec.get("stacks") != [rec.get("stack")] * rec.get("n", 0):
        bad.append(f"stacks {rec.get('stacks')} are not {rec.get('n')} x {rec.get('stack')}")
    if rec.get("unit") != "ICM chips/hand":
        bad.append(f"unit {rec.get('unit')!r} is not in the lifetime-eps unit")

    # The leaf-free claim, checked as data rather than argued. Equal stacks must give flop: 0.
    if rec.get("counts", {}).get("flop", 0) != 0:
        bad.append(f"flop terminals {rec['counts']['flop']} -- not leaf-free, needs burch's item")

    # The stop rule must not be looser than this cell's own bar. At n=2 that bar is the measured
    # lifetime eps for the stack; at n>=3 it is the model's own error, since below that the solve
    # converges on the wrong game. A cell *tighter* than its bar is allowed (older cells are), and
    # is reported as over-solved rather than as a failure. See grid.target_for, design doc Sec 11/17.
    n, stack = rec.get("n", 0), rec.get("stack", 0)
    if n == 2:
        bar = EPS_N2.get(stack)
        if bar is None:
            bad.append(f"no measured lifetime eps for n=2 stack {stack}")
            bar = rec.get("target", 0)
    else:
        bar = MODEL_FIDELITY.get(n, 0.0119)   # fall back to the largest measured n
    if rec.get("target", 0) > bar * 1.001:
        bad.append(f"target {rec['target']:g} is looser than the {bar:g} bar for n={n} {stack:g}bb")
    if rec.get("lifetime_eps") != 0.0006:
        bad.append(f"lifetime_eps {rec.get('lifetime_eps')!r} is not the adopted 0.0006")

    # The solve. `final_gain` is over the target only if it did not converge; say which.
    if rec.get("converged") is False:
        bad.append(f"not converged: gain {rec.get('final_gain')} vs target {rec.get('target')}")
    return bad


def main() -> int:
    quiet = "--quiet" in sys.argv
    runpath = CELLS / "RUN.json"
    if not runpath.exists():
        print(f"no {runpath}; nothing is quotable")
        return 1
    run = json.loads(runpath.read_text())
    live = prov.digests()
    if live != run["code"]:
        print("WARNING: the workspace has moved since this run. Live digests differ:")
        for k, v in sorted(live.items()):
            if run["code"].get(k) != v:
                print(f"  {k:<18} live {v}  run {run['code'].get(k)}")
        print("  -> the frozen copy is cells/code-%s/; check against that, not against live files."
              % run["code_fingerprint"])
        print()

    files = sorted(CELLS.glob("*.json"))
    cells = [p for p in files if p.name != "RUN.json"]
    ok, bad = [], []
    for p in cells:
        rec = json.loads(p.read_text())
        problems = check_cell(rec, run)
        (bad if problems else ok).append((p.name, problems))
        if problems and not quiet:
            print(f"NOT QUOTABLE {p.name}")
            for x in problems:
                print(f"    {x}")

    planned = set(run["plan"])
    present = {p.stem for p in cells}
    missing = sorted(planned - present)
    print(f"\n{len(ok)} quotable, {len(bad)} not quotable, {len(missing)} of {len(planned)} "
          f"planned not yet solved")
    if missing and not quiet:
        print("  pending: " + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
