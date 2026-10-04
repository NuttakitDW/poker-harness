"""Download 2-7 triple draw hand histories from the MixedSolver Arena (arena.sorawit.dev).

The arena's JSON API is public. Each match exposes about 100 "sample" hands (the first hands of the
match, so an unbiased draw) and about 100 "biggest" pots, every one with all hole cards, each
player's discards and the cards they drew. We keep the matches in which a strong bot played other
non-baseline bots and save every exposed hand to tmp/td27_arena/.

    .venv/bin/python research/td27_arena/collect.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / "tmp" / "td27_arena"
API = "https://arena.sorawit.dev/api/matches/"
# The API answers 403 to Python's default User-Agent.
HEADERS = {"User-Agent": "curl/8.7.1", "Accept": "application/json"}
LAST_MATCH_ID = 1206
WORKERS = 6
MAX_MATCHES_PER_LINEUP = 12
MIN_HANDS = 5000

# Strongest bots by hand-weighted win rate against non-baseline opponents (see analyze.py ranking).
ELITE_HU = frozenset({"paul-gandalf200-4bit", "swit-27td-5.1-i048", "2-7-spinel-1", "2-7-astra-1",
                      "2-7-tourmaline-2", "2-7-tourmaline-1"})
ELITE_6MAX = frozenset({"swit-27td-ring3", "swit-27td-ring2", "paul-sauron300-27td-ring-1bit",
                        "paul-sauron301-27td-ring-1bit", "paul-sauron200-27td-1bit",
                        "paul-sauron100-neutral-1bit", "paul-sauron100-exploit-1bit",
                        "paul-sauron100-lite-1bit"})
BASELINE_PREFIXES = ("rand/", "auto")


def get(url: str, tries: int = 3) -> dict | None:
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
    return None


def is_baseline(name: str) -> bool:
    return name.startswith(BASELINE_PREFIXES)


def elite_for(n_players: int) -> frozenset:
    return ELITE_HU if n_players == 2 else ELITE_6MAX


def scan_matches() -> dict[str, dict]:
    with ThreadPoolExecutor(WORKERS) as ex:
        found = ex.map(lambda i: (i, get(f"{API}{i}")), range(1, LAST_MATCH_ID + 1))
        return {str(i): d for i, d in found if d and d["matchInfo"]["game"] == "27td-fl"}


def select_matches(matches: dict[str, dict]) -> list[int]:
    lineups: dict[frozenset, list[int]] = {}
    for key, match in matches.items():
        info = match["matchInfo"]
        names = set(info["players"])
        if info["status"] != "completed" or info["completedHands"] < MIN_HANDS or len(names) < 2:
            continue
        if any(is_baseline(n) for n in names):
            continue
        elite = names & elite_for(len(info["players"]))
        if elite:
            lineups.setdefault(frozenset(elite), []).append(int(key))
    return sorted({m for ids in lineups.values() for m in sorted(ids)[-MAX_MATCHES_PER_LINEUP:]})


def hand_numbers(match_id: int, collection: str) -> list[int]:
    numbers, page = [], 0
    while True:
        listing = get(f"{API}{match_id}/hands?collection={collection}&page={page}")
        if not listing:
            return numbers
        numbers += [h["number"] for h in listing["hands"]]
        page += 1
        if page >= listing.get("pageCount", 1):
            return numbers


def main() -> None:
    hands_dir = CACHE / "hands"
    hands_dir.mkdir(parents=True, exist_ok=True)
    matches_file = CACHE / "matches.json"
    if matches_file.exists():
        matches = json.loads(matches_file.read_text())
    else:
        matches = scan_matches()
        matches_file.write_text(json.dumps(matches))
    selected = select_matches(matches)
    print(f"{len(matches)} triple draw matches, {len(selected)} selected")

    with ThreadPoolExecutor(WORKERS) as ex:
        samples = dict(zip(selected, ex.map(lambda m: hand_numbers(m, "samples"), selected)))
        biggest = dict(zip(selected, ex.map(lambda m: hand_numbers(m, "biggest"), selected)))
    (CACHE / "samples.json").write_text(json.dumps({str(m): v for m, v in samples.items()}))

    jobs = [(m, n) for m in selected for n in sorted(set(samples[m]) | set(biggest[m]))
            if not (hands_dir / f"{m}_{n}.json").exists()]

    def fetch(job: tuple[int, int]) -> bool:
        match_id, number = job
        hand = get(f"{API}{match_id}/hands/{number}")
        if hand is None:
            return False
        hand["match"] = match_id
        hand["players"] = matches[str(match_id)]["matchInfo"]["players"]
        (hands_dir / f"{match_id}_{number}.json").write_text(json.dumps(hand))
        return True

    with ThreadPoolExecutor(WORKERS) as ex:
        ok = sum(ex.map(fetch, jobs))
    print(f"fetched {ok} of {len(jobs)} missing hands; rerun to retry failures")


if __name__ == "__main__":
    main()
