"""คิด equity preflop แบบสองคนไว้ล่วงหน้าครบทุกคู่มือ เก็บลง tmp/equity.sqlite

หลังรันครั้งเดียว range vs range preflop ทุกขนาดตอบได้ทันทีแบบ exact
คู่มือที่เหมือนกันเมื่อสลับดอกคิดครั้งเดียว ใช้หลายคอร์ รันซ้ำได้ ข้ามส่วนที่คิดไว้แล้ว

    .venv/bin/python scripts/build_equity_cache.py
"""

from __future__ import annotations

import argparse
import concurrent.futures
import itertools
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "voice"))

import equity  # noqa: E402
import equity_eval as ev  # noqa: E402

CHUNK = 64


def _work(chunk: list[tuple[str, tuple[tuple[int, int], tuple[int, int]]]]) -> dict[str, equity.Share]:
    return {key: equity.exact_share(holes, ()) for key, holes in chunk}


def missing_matchups() -> list[tuple[str, tuple[tuple[int, int], tuple[int, int]]]]:
    """คู่มือตัวแทนของแต่ละรูปมาตรฐานที่ยังไม่มีในแคช"""
    every = list(itertools.combinations(range(ev.DECK_SIZE), ev.HOLE_SIZE))
    pairs = equity.pair_matchups(every, every)
    keys = equity.canonical_keys(pairs, ())
    known = equity.MEMO.load()
    wanted: dict[str, tuple] = {}
    for key, pair in zip(keys, pairs):
        if key not in known and key not in wanted:
            wanted[key] = tuple(tuple(map(int, hole)) for hole in pair)
    return list(wanted.items())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()

    began = time.perf_counter()
    todo = missing_matchups()
    print(f"ต้องคิด {len(todo):,} รูปคู่มือ ใช้ {args.workers} คอร์", flush=True)
    chunks = [todo[start:start + CHUNK] for start in range(0, len(todo), CHUNK)]
    done = 0
    with concurrent.futures.ProcessPoolExecutor(args.workers) as pool:
        for fresh in pool.map(_work, chunks):
            equity.MEMO.save(fresh)
            done += len(fresh)
            if done % (CHUNK * 50) < CHUNK or done == len(todo):
                spent = time.perf_counter() - began
                print(f"{done:,}/{len(todo):,}  {spent:,.0f}s", flush=True)
    print(f"เสร็จใน {time.perf_counter() - began:,.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
