"""เทียบผล bakeoff ของหลาย engine แบบเรียงข้างกัน

ใช้:
    python scripts/voice/stt_compare.py tmp/stt/whisper.json tmp/stt/whisper-biased.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import metrics  # noqa: E402


def rescore(row: dict) -> dict:
    """คำนวณคะแนนใหม่จากข้อความดิบ เพื่อให้แก้ตัววัดแล้วมีผลย้อนหลัง"""
    reference = row.get("reference")
    if not reference:
        return row
    return {
        **row,
        "cer": round(metrics.character_error_rate(reference, row["hypothesis"]), 4),
        "english_recall": round(metrics.english_recall(reference, row["hypothesis"]), 3),
    }


def load(path: pathlib.Path) -> tuple[str, dict[str, dict]]:
    """คืนชื่อ engine และผลที่จัดทำดัชนีด้วยชื่อไฟล์เสียง"""
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not rows:
        raise SystemExit(f"{path} ไม่มีข้อมูล")
    return rows[0].get("engine", path.stem), {row["file"]: rescore(row) for row in rows}


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarise(name: str, rows: dict[str, dict]) -> dict:
    scored = [r for r in rows.values() if "cer" in r]
    return {
        "engine": name,
        "files": len(scored),
        "cer": mean([r["cer"] for r in scored]),
        "english_recall": mean([r["english_recall"] for r in scored]),
        "rtf": mean([r["rtf"] for r in rows.values() if r.get("rtf")]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="เทียบผล STT หลาย engine")
    parser.add_argument("results", nargs="+", type=pathlib.Path)
    parser.add_argument("--per-file", action="store_true", help="แสดงข้อความถอดของทุกไฟล์")
    args = parser.parse_args()

    missing = [p for p in args.results if not p.exists()]
    if missing:
        print(f"ไม่พบไฟล์: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 1

    loaded = [load(path) for path in args.results]

    if args.per_file:
        for filename in sorted(loaded[0][1]):
            reference = loaded[0][1][filename].get("reference", "")
            print(f"\n[{filename}]\n  เฉลย    : {reference}")
            for name, rows in loaded:
                row = rows.get(filename)
                if not row:
                    continue
                print(f"  {name:<9}: {row['hypothesis']}")
                if "cer" in row:
                    print(f"  {'':<9}  CER {row['cer']:.4f}  อังกฤษ {row['english_recall']:.2f}")

    print(f"\n{'engine':<10}{'ไฟล์':>6}{'CER':>10}{'อังกฤษ':>10}{'RTF':>8}")
    print("-" * 44)
    for name, rows in loaded:
        s = summarise(name, rows)
        print(f"{s['engine']:<10}{s['files']:>6}{s['cer']:>10.4f}"
              f"{s['english_recall']:>10.3f}{s['rtf']:>8.1f}")
    print("\nCER ต่ำกว่าดีกว่า  อังกฤษสูงกว่าดีกว่า  RTF สูงกว่าเร็วกว่า")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
