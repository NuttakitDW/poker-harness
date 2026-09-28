"""Inject a seed-specific oddsmaker 3-way table into every reader, without editing pushfold/.

The only source of Monte Carlo noise in the game is `oddsmaker.three_way()` (eq3, pw). Every
reader of it goes through either

  * `oddsmaker.orders()`                    (lru_cache) -> pushfold.icm_pricer._layouts()
  * `pushfold.pricer._three_way()`          (lru_cache) -> pricer3, icm_pricer3
  * `johanson.seqbr.tables()`               (uncached)  -> seqbr3.Auditor's leaf

and all three bottom out at `oddsmaker.three_way` looked up in the module dict at call time.
So one rebind plus clearing the four caches above it is the whole injection. `e2` is exact and
does not change with SEED, so `oddsmaker.two_way` is left alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepstack-swarm" / "workspace" / "burch" / "open3bet"))

from pushfold import icm_pricer, oddsmaker, pricer  # noqa: E402

TMP_E3 = ROOT / "tmp" / "pushfold-e3.npz"          # SEED = 20260924, read-only
SEEDS_DIR = ROOT / "deepstack-swarm" / "workspace" / "burch" / "seeds"


def load_tables(path: Path) -> oddsmaker.Tables:
    with np.load(path) as saved:
        return oddsmaker.Tables(np.empty(0), saved["eq3"], saved["pw"],
                                saved["possible"], int(saved["samples"]))


def seed_paths() -> dict[str, Path]:
    return {"A": TMP_E3, "B": SEEDS_DIR / "e3-seedB.npz", "C": SEEDS_DIR / "e3-seedC.npz"}


def install(tab: oddsmaker.Tables) -> None:
    """Point oddsmaker's 3-way table at `tab` and drop everything cached above it."""
    oddsmaker.three_way = lambda: tab
    oddsmaker.orders.cache_clear()
    pricer._three_way.cache_clear()
    pricer._two_way.cache_clear()
    icm_pricer._layouts.cache_clear()
    icm_pricer._pair.cache_clear()


def install_seed(name: str) -> oddsmaker.Tables:
    tab = load_tables(seed_paths()[name])
    install(tab)
    return tab
