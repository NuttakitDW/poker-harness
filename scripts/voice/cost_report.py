"""สรุปค่าใช้จ่ายจากบันทึกการคุย แล้วฉายเป็นต้นทุนต่อชั่วโมงและต่อผู้ใช้ต่อปี

บันทึกรุ่นใหม่มีเหตุการณ์ usage ที่ตีราคาไว้แล้วทุกครั้ง ใช้ยอดนั้นตรง ๆ
บันทึกรุ่นเก่าก่อนมีตัวนับ ต้องเดาจากจำนวนคำตอบและความยาวข้อความที่พูด

ใช้:
    python scripts/voice/cost_report.py
    python scripts/voice/cost_report.py tmp/logs/live-20260923-*.jsonl
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import NamedTuple

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import costs  # noqa: E402
import journal  # noqa: E402

# ค่าเฉลี่ยจากการเรียกจริง ใช้เดาต้นทุนโมเดลของบันทึกที่ยังไม่มียอด token
TYPICAL_PROMPT_TOKENS = 8000
TYPICAL_CACHE_HIT_SHARE = 0.4
TYPICAL_OUTPUT_TOKENS = 280
# ข้อความที่ส่งไปสังเคราะห์ยาวกว่าที่โชว์ เพราะตัวเลขและคำย่อถูกแปลงเป็นคำอ่าน
SPOKEN_EXPANSION = 1.15
# engine ทางสตรีม -> ชื่อที่ใช้คิดเงิน บันทึกเก่าใช้ Soniox ตั้งแต่ 2026-09-25 เป็น Paxa
STREAMING_ENGINES = {"soniox-rt": "soniox-stt-rt", "paxa-rt": "paxa-stt-rt"}
# ตัวอย่างการใช้งานต่อผู้ใช้ ชั่วโมงต่อปี
USAGE_PROFILES = (
    ("เบา: 15 นาที 3 วันต่อสัปดาห์", 15 / 60 * 3 * 52),
    ("ปกติ: 30 นาที 5 วันต่อสัปดาห์", 30 / 60 * 5 * 52),
    ("หนัก: 2 ชั่วโมงทุกวัน", 2 * 365),
)


class Session(NamedTuple):
    """ยอดของการคุยหนึ่งรอบ"""

    name: str
    minutes: float
    answers: int
    by_api: dict
    estimated: bool

    @property
    def usd(self) -> float:
        return sum(self.by_api.values())


def _guess(records: list[dict], minutes: float) -> dict:
    """เดาค่าใช้จ่ายของบันทึกรุ่นก่อนมีตัวนับ จากคำตอบและเวลาที่เปิดสาย"""
    answers = [r for r in records if r.get("kind") == "answer"]
    hit = round(TYPICAL_PROMPT_TOKENS * TYPICAL_CACHE_HIT_SHARE)
    per_answer = costs.deepseek_usd(hit, TYPICAL_PROMPT_TOKENS - hit, TYPICAL_OUTPUT_TOKENS)
    chars = sum(len(r.get("text") or "") for r in answers) * SPOKEN_EXPANSION
    start = next((r for r in records if r.get("kind") == "start"), {})
    guessed = {"deepseek": per_answer * len(answers)}
    guessed[f"{start.get('tts', 'paxa')}-tts"] = (
        costs.soniox_tts_usd(round(chars)) if start.get("tts") == "soniox"
        else costs.paxa_usd(round(chars)))
    api = STREAMING_ENGINES.get(start.get("engine"))
    if api:
        guessed[api] = costs.stream_usd(api, minutes * 60)
    return guessed


def summarize(path: pathlib.Path) -> Session | None:
    """อ่านบันทึกหนึ่งไฟล์ คืน None ถ้าไฟล์ว่างหรืออ่านไม่ได้"""
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
    except (OSError, json.JSONDecodeError) as error:
        print(f"ข้าม {path.name}: {error}", file=sys.stderr)
        return None
    if not records:
        return None
    minutes = float(records[-1].get("since") or 0) / 60
    answers = sum(1 for r in records if r.get("kind") == "answer")
    usage = [r for r in records if r.get("kind") == "usage"]
    if not usage:
        return Session(path.name, minutes, answers, _guess(records, minutes), True)
    by_api: dict[str, float] = {}
    for item in usage:
        by_api = {**by_api, item["api"]: by_api.get(item["api"], 0.0) + float(item["usd"])}
    return Session(path.name, minutes, answers, by_api, False)


def report(sessions: list[Session]) -> str:
    """ตารางต่อรอบ ยอดรวม และต้นทุนฉายต่อชั่วโมงกับต่อปี"""
    lines = [f"{'บันทึก':<28}{'นาที':>7}{'คำตอบ':>7}{'USD':>10}  ที่มา"]
    for s in sessions:
        source = "เดา" if s.estimated else "นับจริง"
        lines.append(f"{s.name:<28}{s.minutes:7.1f}{s.answers:7d}{s.usd:10.4f}  {source}")
    minutes = sum(s.minutes for s in sessions)
    usd = sum(s.usd for s in sessions)
    totals: dict[str, float] = {}
    for s in sessions:
        for api, value in s.by_api.items():
            totals = {**totals, api: totals.get(api, 0.0) + value}
    lines.append(f"\nรวม {minutes:.1f} นาที ${usd:.4f} (฿{usd * costs.THB_PER_USD:.2f})")
    for api, value in sorted(totals.items(), key=lambda pair: -pair[1]):
        share = value / usd * 100 if usd else 0
        lines.append(f"  {api:<18}${value:.4f}  {share:4.0f}%")
    if minutes:
        per_hour = usd / minutes * 60
        lines.append(f"\nต่อชั่วโมงที่เปิดคุย ${per_hour:.3f} (฿{per_hour * costs.THB_PER_USD:.1f})")
        for label, hours in USAGE_PROFILES:
            yearly = per_hour * hours
            lines.append(f"  {label:<32}{hours:6.0f} ชม./ปี  ${yearly:8.2f}"
                         f"  ฿{yearly * costs.THB_PER_USD:9,.0f}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="สรุปค่าใช้จ่ายจากบันทึกการคุย")
    parser.add_argument("logs", nargs="*", type=pathlib.Path,
                        help="ไฟล์บันทึก ค่าเริ่มต้นคือทุกไฟล์ใน tmp/logs")
    args = parser.parse_args()
    paths = args.logs or sorted(journal.LOG_DIR.glob("*.jsonl"))
    sessions = [s for s in (summarize(path) for path in paths) if s is not None]
    if not sessions:
        print("ไม่พบบันทึกที่มีข้อมูล", file=sys.stderr)
        return 1
    print(report(sessions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
