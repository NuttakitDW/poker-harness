"""Digest the code a grid cell was actually solved with.

Why this exists. `deepstack-swarm/workspace/` is NOT tracked by git (`git ls-files
deepstack-swarm/workspace/` returns nothing), so the `commit` field in a cell record pins only
`pushfold/` and the repo around it -- not the solver. The grid's 41 first cells were written between
22:22 and 23:10 on 2026-09-27 while `fasticm3.py` was edited at 22:24 and `floor3.py` at 23:30, so
they are not one artifact and cannot be reproduced from the record. Every cell now carries a short
SHA-256 of every module in the solve path; `snapshot()` freezes those modules next to the cells so a
reader can re-run against the exact code rather than whatever the workspace holds later.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPEN3BET = HERE.parents[1] / "burch" / "open3bet"
ROOT = HERE.parents[3]

# The modules the solve path imports, in the order solve3 imports them, plus the drivers.
MODULES = [
    OPEN3BET / "floor3.py",
    OPEN3BET / "pricer3.py",
    OPEN3BET / "icm_pricer3.py",
    OPEN3BET / "seqbr3.py",
    OPEN3BET / "fasticm3.py",
    OPEN3BET / "coach3.py",
    OPEN3BET / "solve3.py",
    HERE / "scenarios.py",
    ROOT / "pushfold" / "icm.py",
    ROOT / "pushfold" / "hands.py",
    ROOT / "pushfold" / "spot.py",
    ROOT / "pushfold" / "cashier.py",
    ROOT / "pushfold" / "oddsmaker.py",
]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def digests() -> dict[str, str]:
    """{module name: 12 hex chars}. Missing files are recorded as 'missing', not skipped."""
    out = {}
    for p in MODULES:
        out[p.name] = _digest(p) if p.exists() else "missing"
    return out


def snapshot(dest: Path | None = None) -> Path:
    """Copy every module into `dest` (default `cells/code-<tag>`) and return it."""
    dest = dest or (HERE / "cells" / f"code-{fingerprint()}")
    dest.mkdir(parents=True, exist_ok=True)
    for p in MODULES:
        if p.exists():
            shutil.copy2(p, dest / p.name)
    (dest / "MANIFEST.txt").write_text(
        "module  sha256[:12]\n" + "".join(f"{k}  {v}\n" for k, v in sorted(digests().items()))
    )
    return dest


def fingerprint() -> str:
    """One short string identifying the whole solve path, for a filename or a log line."""
    h = hashlib.sha256("".join(f"{k}={v}" for k, v in sorted(digests().items())).encode())
    return h.hexdigest()[:8]


if __name__ == "__main__":
    d = digests()
    print(f"fingerprint {fingerprint()}")
    for k, v in sorted(d.items()):
        print(f"  {k:<18} {v}")
