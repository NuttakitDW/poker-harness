#!/usr/bin/env bash
# อัดเสียงจากไมค์เป็น wav 16k mono สำหรับทดสอบ STT
# ใช้: scripts/voice/record.sh <ชื่อไฟล์> [วินาที]
set -euo pipefail

OUT="${1:?ใช้: record.sh <ชื่อไฟล์> [วินาที]}"
SECS="${2:-8}"
DEV="${AUDIO_DEVICE:-:0}"

mkdir -p "$(dirname "$OUT")"
echo "อัด ${SECS} วินาที -> ${OUT}  (พูดได้เลย)"
ffmpeg -hide_banner -loglevel error -y \
  -f avfoundation -i "$DEV" -t "$SECS" \
  -ac 1 -ar 16000 -c:a pcm_s16le "$OUT"
echo "เสร็จ: $OUT"
