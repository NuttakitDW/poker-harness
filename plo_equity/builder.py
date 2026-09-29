"""Parallel, deterministic and resumable construction of every PLO4 suit class."""

from __future__ import annotations

import concurrent.futures
import pathlib
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from .cache import Cache, Metadata
from .cards import HandClass, enumerate_classes
from .simulation import TrialStats, simulate_range


@dataclass(frozen=True)
class BuildResult:
    classes_total: int
    classes_updated: int
    target_samples: int
    elapsed_seconds: float


def _work(task: tuple[HandClass, int, int, int, int]) -> tuple[str, int, TrialStats]:
    hand, start, stop, seed, opponents = task
    return hand.key, start, simulate_range(hand.cards, start, stop, seed, opponents)


def build(path: pathlib.Path, samples: int, global_seed: int, opponents: int = 1,
          workers: int = 1, classes: Iterable[HandClass] | None = None,
          progress: Callable[[int, int, float], None] | None = None) -> BuildResult:
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 2:
        raise ValueError("samples must be an integer of at least two")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
        raise ValueError("workers must be a positive integer")
    hands = tuple(classes) if classes is not None else enumerate_classes()
    began = time.perf_counter()
    with Cache(path, Metadata(global_seed, opponents)) as cache:
        known = cache.load()
        tasks = []
        for hand in hands:
            start = known.get(hand.key, TrialStats()).n
            if start > samples:
                raise ValueError(f"cache already has {start} samples for {hand.text}, above target {samples}")
            if start < samples:
                tasks.append((hand, start, samples, global_seed, opponents))
        if workers == 1:
            results: Iterator[tuple[str, int, TrialStats]] = map(_work, tasks)
            executor = None
        else:
            executor = concurrent.futures.ProcessPoolExecutor(max_workers=workers)
            results = executor.map(_work, tasks, chunksize=1)
        try:
            for done, (key, start, delta) in enumerate(results, 1):
                cache.add(key, start, delta)
                if progress is not None:
                    progress(done, len(tasks), time.perf_counter() - began)
        finally:
            if executor is not None:
                executor.shutdown(cancel_futures=True)
    return BuildResult(len(hands), len(tasks), samples, time.perf_counter() - began)
