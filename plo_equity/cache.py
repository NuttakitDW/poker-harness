"""Strict SQLite checkpoint storage for additive PLO equity statistics."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import math
import pathlib
import platform
import sqlite3
from dataclasses import dataclass
from typing import Self

from .simulation import BLOCK_SIZE, RNG_VERSION, TrialStats


def _source_fingerprint() -> str:
    digest = hashlib.sha256()
    package = pathlib.Path(__file__).resolve().parent
    for name in ("cards.py", "evaluator.py", "simulation.py"):
        digest.update(name.encode())
        digest.update((package / name).read_bytes())
    return digest.hexdigest()


class CacheError(RuntimeError):
    pass


@dataclass(frozen=True)
class Metadata:
    global_seed: int
    opponents: int = 1
    schema: str = "plo-equity-v1"
    evaluator: str = "phevaluator-0.6.0-plo4-lower-is-stronger"
    game: str = "PLO4 high; exactly 2 hole and 3 board cards"
    opponent_range: str = "uniform random physical PLO4 hands, disjoint from hero and board"
    board_range: str = "uniform complete five-card board without replacement"
    rng: str = RNG_VERSION
    block_size: int = BLOCK_SIZE
    python_runtime: str = dataclasses.field(
        default_factory=lambda: f"{platform.python_implementation()}-{platform.python_version()}")
    source_fingerprint: str = dataclasses.field(default_factory=_source_fingerprint)

    def __post_init__(self) -> None:
        if isinstance(self.global_seed, bool) or not isinstance(self.global_seed, int):
            raise TypeError("global_seed must be an integer")
        if isinstance(self.opponents, bool) or not isinstance(self.opponents, int):
            raise TypeError("opponents must be an integer")
        if self.opponents != 1:
            raise ValueError("the persisted ranking table is scoped to heads-up equity (opponents=1)")
        if importlib.metadata.version("phevaluator") != "0.6.0":
            raise CacheError("phevaluator==0.6.0 is required for cache compatibility")

    def encoded(self) -> str:
        return json.dumps(dataclasses.asdict(self), sort_keys=True, separators=(",", ":"))


class Cache:
    def __init__(self, path: pathlib.Path, metadata: Metadata):
        self.path = pathlib.Path(path)
        self.metadata = metadata
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.execute("pragma journal_mode=WAL")
        self.connection.execute("create table if not exists metadata (id integer primary key check(id=1), value text not null)")
        self.connection.execute("""create table if not exists sample (
            key text primary key, n integer not null, sum_x real not null, sum_x2 real not null,
            wins integer not null, ties integer not null)""")
        found = self.connection.execute("select value from metadata where id=1").fetchone()
        if found is None:
            self.connection.execute("insert into metadata values (1, ?)", (metadata.encoded(),))
            self.connection.commit()
        elif found[0] != metadata.encoded():
            self.connection.close()
            raise CacheError("cache metadata is incompatible with the requested run")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def load(self) -> dict[str, TrialStats]:
        rows = self.connection.execute("select key,n,sum_x,sum_x2,wins,ties from sample").fetchall()
        result = {key: TrialStats(n, sum_x, sum_x2, wins, ties)
                  for key, n, sum_x, sum_x2, wins, ties in rows}
        for stats in result.values():
            self._validate_hu(stats)
        return result

    @staticmethod
    def _validate_hu(stats: TrialStats) -> None:
        if (not math.isclose(stats.sum_x, stats.wins + .5 * stats.ties, abs_tol=1e-9)
                or not math.isclose(stats.sum_x2, stats.wins + .25 * stats.ties, abs_tol=1e-9)):
            raise CacheError("HU moments disagree with win/tie counts")

    def add(self, key: str, expected_n: int, delta: TrialStats) -> None:
        if delta.n <= 0:
            return
        self._validate_hu(delta)
        try:
            self.connection.execute("begin immediate")
            row = self.connection.execute(
                "select n,sum_x,sum_x2,wins,ties from sample where key=?", (key,)).fetchone()
            current = TrialStats(*row) if row else TrialStats()
            if current.n != expected_n:
                raise CacheError(f"checkpoint conflict for {key}: expected {expected_n}, found {current.n}")
            updated = current + delta
            self.connection.execute("""insert into sample values (?,?,?,?,?,?)
                on conflict(key) do update set n=excluded.n,sum_x=excluded.sum_x,
                sum_x2=excluded.sum_x2,wins=excluded.wins,ties=excluded.ties""",
                                    (key, updated.n, updated.sum_x, updated.sum_x2,
                                     updated.wins, updated.ties))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
