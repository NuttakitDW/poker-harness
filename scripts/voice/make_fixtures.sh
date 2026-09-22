#!/usr/bin/env bash
# สร้างไฟล์เสียงทดสอบจาก phrases_th.txt ด้วย Paxa TTS แล้วแปลงเป็น wav 16k mono
# ใช้: scripts/voice/make_fixtures.sh [เสียง] [โฟลเดอร์ปลายทาง]
set -euo pipefail

VOICE="${1:-foithong}"
DEST="${2:-tmp/stt/synth}"
PHRASES="scripts/voice/phrases_th.txt"

mkdir -p "$DEST"
n=0
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  n=$((n + 1))
  base=$(printf "%s/%02d-%s" "$DEST" "$n" "$VOICE")
  python3 scripts/voice/speak.py "$line" --voice "$VOICE" --no-play --out "$base.mp3" >/dev/null
  ffmpeg -hide_banner -loglevel error -y -i "$base.mp3" -ac 1 -ar 16000 -c:a pcm_s16le "$base.wav"
  rm -f "$base.mp3"
  printf '%s' "$line" > "$base.txt"
  echo "[$n] $base.wav"
done < "$PHRASES"
echo "สร้างไฟล์ทดสอบ $n ไฟล์ใน $DEST"
