#!/usr/bin/env bash
# อัดเสียงอ่านประโยคทดสอบทีละประโยค พร้อมฟังทวนและอัดใหม่ได้
# ใช้: scripts/voice/record_session.sh [โฟลเดอร์ปลายทาง]
# เสียงจริงพร้อมเฉลยเป็นสินทรัพย์ที่อัดใหม่แพง จึงเก็บถาวรใน tests/fixtures ไม่ใช่ tmp
set -uo pipefail

DEST="${1:-tests/fixtures/voice/real}"
PHRASES="scripts/voice/phrases_th.txt"
DEV="${AUDIO_DEVICE:-:0}"
MAX_SECONDS=30

command -v ffmpeg >/dev/null || { echo "ต้องติดตั้ง ffmpeg ก่อน"; exit 1; }
[ -f "$PHRASES" ] || { echo "ไม่พบ $PHRASES"; exit 1; }

mkdir -p "$DEST"

bold=$(tput bold 2>/dev/null || true)
dim=$(tput dim 2>/dev/null || true)
reset=$(tput sgr0 2>/dev/null || true)

LINES=()
while IFS= read -r phrase; do
  LINES+=("$phrase")
done < <(grep -vE '^[[:space:]]*(#|$)' "$PHRASES")
total=${#LINES[@]}
[ "$total" -gt 0 ] || { echo "ไม่มีประโยคใน $PHRASES"; exit 1; }

cat <<INTRO

${bold}อัดเสียงทดสอบ ${total} ประโยค${reset}
${dim}กด Enter เพื่อเริ่มอัด แล้วกด Enter อีกครั้งเมื่อพูดจบ
พูดให้เป็นธรรมชาติ ศัพท์อังกฤษออกเสียงแบบที่พูดจริง ไม่ต้องดัด${reset}

INTRO

record_one() {
  local out="$1"
  ffmpeg -hide_banner -loglevel error -y \
    -f avfoundation -i "$DEV" -t "$MAX_SECONDS" \
    -ac 1 -ar 16000 -c:a pcm_s16le "$out" &
  local pid=$!
  read -r < /dev/tty
  kill -INT "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  [ -s "$out" ]
}

index=0
for line in "${LINES[@]}"; do
  index=$((index + 1))
  base=$(printf "%s/%02d" "$DEST" "$index")

  while true; do
    printf '\n%s[%d/%d]%s %s\n' "$bold" "$index" "$total" "$reset" "$line"
    printf '%sEnter = เริ่มอัด%s ' "$dim" "$reset"
    read -r < /dev/tty

    printf '  ● กำลังอัด... %sEnter = หยุด%s ' "$dim" "$reset"
    if ! record_one "$base.wav"; then
      printf '\n  อัดไม่สำเร็จ ลองใหม่\n'
      continue
    fi

    printf '\n  กำลังเปิดฟัง...\n'
    afplay "$base.wav" 2>/dev/null

    printf '  %sEnter = ใช้อันนี้  |  r = อัดใหม่  |  s = ข้าม%s ' "$dim" "$reset"
    read -r choice < /dev/tty
    case "$choice" in
      r|R) continue ;;
      s|S) rm -f "$base.wav"; break ;;
      *) printf '%s' "$line" > "$base.txt"; printf '  บันทึก %s.wav\n' "$base"; break ;;
    esac
  done
done

saved=$(ls "$DEST"/*.wav 2>/dev/null | wc -l | tr -d ' ')
printf '\n%sอัดครบแล้ว %s ไฟล์ใน %s%s\n' "$bold" "$saved" "$DEST" "$reset"
