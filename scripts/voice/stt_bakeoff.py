"""เทียบคุณภาพ STT ไทยสลับอังกฤษระหว่างหลาย engine

ใช้:
    .venv-whisper/bin/python scripts/voice/stt_bakeoff.py --engine whisper-biased \
        tests/fixtures/voice/real/*.wav --json tmp/stt/whisper-biased.json

engine typhoon ต้องติดตั้ง typhoon-asr ใน virtualenv แยก เพราะ dependency ชนกับ mlx

ไฟล์เสียงที่มี .txt ชื่อเดียวกันวางข้าง ๆ จะถูกใช้เป็นเฉลยอัตโนมัติ
ผลลัพธ์ JSON เอาไปเทียบกันด้วย scripts/voice/stt_compare.py ได้
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import engines  # noqa: E402
import metrics  # noqa: E402


def load_reference(audio: pathlib.Path, override: str | None) -> str | None:
    """เฉลยจากอาร์กิวเมนต์ก่อน แล้วค่อยหาไฟล์ .txt ชื่อเดียวกัน"""
    if override:
        return override
    sidecar = audio.with_suffix(".txt")
    return sidecar.read_text(encoding="utf-8").strip() if sidecar.exists() else None


def score(audio: pathlib.Path, engine: str, device: str, override: str | None) -> dict:
    """ถอดเสียงหนึ่งไฟล์แล้วคืนผลพร้อมคะแนนถ้ามีเฉลย"""
    result = engines.ENGINES[engine](str(audio), device=device)
    row = {
        "engine": engine,
        "file": audio.name,
        "hypothesis": result.text,
        "seconds": round(result.seconds, 3),
        "rtf": round(result.audio_seconds / result.seconds, 1)
        if result.audio_seconds and result.seconds
        else None,
    }
    reference = load_reference(audio, override)
    if reference:
        row["reference"] = reference
        row["cer"] = round(metrics.character_error_rate(reference, result.text), 4)
        row["english_recall"] = round(metrics.english_recall(reference, result.text), 3)
    return row


def report(rows: list[dict]) -> None:
    """พิมพ์ผลแบบอ่านง่าย แล้วสรุปค่าเฉลี่ย"""
    for row in rows:
        print(f"\n[{row['file']}]  {row['seconds']}s  RTF {row['rtf']}x")
        if "reference" in row:
            print(f"  เฉลย  : {row['reference']}")
        print(f"  ถอดได้ : {row['hypothesis']}")
        if "cer" in row:
            print(f"  CER {row['cer']}   ศัพท์อังกฤษที่ถอดติด {row['english_recall']}")

    scored = [r for r in rows if "cer" in r]
    if scored:
        mean_cer = sum(r["cer"] for r in scored) / len(scored)
        mean_en = sum(r["english_recall"] for r in scored) / len(scored)
        print(f"\n[{rows[0]['engine']}] สรุป {len(scored)} ไฟล์: "
              f"CER เฉลี่ย {mean_cer:.4f}  ศัพท์อังกฤษเฉลี่ย {mean_en:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="เทียบ STT ไทยสลับอังกฤษ")
    parser.add_argument("audio", nargs="+", type=pathlib.Path)
    parser.add_argument("--engine", default="typhoon", choices=sorted(engines.ENGINES))
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    parser.add_argument("--reference", help="เฉลยสำหรับไฟล์เดียว")
    parser.add_argument("--json", type=pathlib.Path, help="บันทึกผลเป็น JSON")
    args = parser.parse_args()

    missing = [p for p in args.audio if not p.exists()]
    if missing:
        print(f"ไม่พบไฟล์: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 1
    if args.reference and len(args.audio) > 1:
        print("--reference ใช้ได้กับไฟล์เดียวเท่านั้น", file=sys.stderr)
        return 1

    try:
        rows = [score(path, args.engine, args.device, args.reference)
                for path in sorted(args.audio)]
    except RuntimeError as error:
        # บริการบนคลาวด์ปฏิเสธ เช่นคีย์หมดอายุหรือเครดิตหมด ไม่ต้องพ่น traceback ใส่หน้า
        print(f"{args.engine} ถอดเสียงไม่สำเร็จ: {error}", file=sys.stderr)
        return 1
    report(rows)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nบันทึกผล: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
