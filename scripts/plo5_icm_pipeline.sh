#!/bin/zsh
# PLO5 (or PLO4) tournament review: per-hand ICM solves -> option values -> range charts -> private dashboard page.
# Resumable: rerun the same command and finished solves are kept.
#
#   scripts/plo5_icm_pipeline.sh <hand-history.txt> <session-tag> <payouts 1st,2nd,...> <entries> <finish> <first-left> [start-stack]
#
# Writes tmp/plo5/sessions/<tag>/review (solves) and tmp/plo5/sessions/<tag>/dashboard.html, log in .../pipeline.log.
set -u
HH="$1"; TAG="$2"; PAYOUTS="$3"; ENTRIES="$4"; FINISH="$5"; FIRST="$6"; START="${7:-10000}"
cd "$(dirname "$0")/.."
ROOT="$PWD"
OUT="tmp/plo5/sessions/$TAG"
mkdir -p "$OUT"
ARGS=(--hh "$HH" --payouts "$PAYOUTS" --entries "$ENTRIES" --finish "$FINISH" --first-left "$FIRST" --start-stack "$START" --out "$OUT/review")
LOG="$OUT/pipeline.log"
echo "== $(date) start $TAG" >> "$LOG"
# Solver: bounds checking and its own compile cache (shared caches and the plain build segfaulted rarely);
# a crash costs that spot one of its two attempts and the loop carries on.
for round in {1..20}; do
  NUMBA_CACHE_DIR="$ROOT/tmp/numba/solve" NUMBA_BOUNDSCHECK=1 .venv/bin/python -X faulthandler -u \
    -m plo_premium_proof.review solve "${ARGS[@]}" >> "$LOG" 2>&1 && break
  echo "== solver exited with an error (round $round); restarting" >> "$LOG"
done
NUMBA_CACHE_DIR="$ROOT/tmp/numba/eval" .venv/bin/python -u -m plo_premium_proof.review evaluate "${ARGS[@]}" >> "$LOG" 2>&1
NUMBA_CACHE_DIR="$ROOT/tmp/numba/chart" .venv/bin/python -u -m plo_premium_proof.review charts "${ARGS[@]}" >> "$LOG" 2>&1
.venv/bin/python scripts/plo5_dashboard.py --hh "$HH" --out "$OUT/dashboard.html" --review "$OUT/review" \
  --title "$TAG" --entries "$ENTRIES" --finish "$FINISH" --payouts "$PAYOUTS" >> "$LOG" 2>&1
echo "== $(date) ALL DONE $TAG" >> "$LOG"
