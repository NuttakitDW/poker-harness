"""สตรีมเหตุการณ์ระหว่างสนทนา โชว์บนจอทันทีและเก็บลงไฟล์ไว้ย้อนดู

ระหว่างคุยต้องเห็นว่าอะไรเกิดขึ้นตอนไหนแบบสด ๆ ไม่ใช่มาเดาทีหลังว่าทำไมมันค้าง
จึงพิมพ์ทุกเหตุการณ์ออกจอเป็นบรรทัดสั้น ๆ พร้อมเวลา และเขียนเป็น JSONL ควบคู่กันไว้
วิเคราะห์ย้อนหลัง การบันทึกห้ามทำให้บทสนทนาล้ม ทุกข้อผิดพลาดจึงถูกกลืนไว้ที่นี่
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "tmp" / "logs"

DIM = "\033[2m"
RESET = "\033[0m"

_active: "Journal | None" = None


def _seconds(fields: dict, name: str) -> str:
    value = fields.get(name)
    return f"{float(value):.2f}s" if isinstance(value, (int, float)) else "-"


def describe(kind: str, fields: dict) -> str:
    """ข้อความหนึ่งบรรทัดสำหรับเหตุการณ์หนึ่ง เขียนแยกไว้เพื่อทดสอบได้"""
    if kind == "start":
        mode = "พูดแทรกได้" if fields.get("full_duplex") else "ผลัดกันพูด"
        aec = "เปิด" if fields.get("echo_cancel") else "ปิด"
        return (f"เริ่มฟัง โหมด {mode} | ตัดเสียงสะท้อน {aec} | "
                f"ถอดเสียงด้วย {fields.get('engine')} | เสียง {fields.get('voice')}")
    if kind == "utterance":
        cut = " | ตัดเพราะยาวชนเพดาน" if fields.get("cut_short") else ""
        return (f"ได้ยิน {_seconds(fields, 'seconds')} ระดับ {fields.get('peak')} | "
                f"เงียบก่อนพูด {_seconds(fields, 'silence_before')} | "
                f"รับช้า {_seconds(fields, 'lag')}{cut}")
    if kind == "heard":
        text = (fields.get("text") or "").strip()
        return f"ถอดเสียง {_seconds(fields, 'stt')} ได้ว่า {text!r}" if text \
            else f"ถอดเสียง {_seconds(fields, 'stt')} แต่ไม่ได้คำเลย"
    if kind == "question":
        return f"รวมกับท่อนก่อนเป็น {fields.get('text')!r}"
    if kind == "continuation":
        return f"ยังพูดไม่จบ รอฟังต่อ (รวมแล้ว {_seconds(fields, 'merged')})"
    if kind == "answer":
        cards = ", ".join(fields.get("cards") or []) or "ไม่มีการ์ด"
        return (f"ตอบ {fields.get('sentences')} ประโยค | เปิดสตรีม {_seconds(fields, 'opened')} | "
                f"คำแรกจากโมเดล {_seconds(fields, 'first_token')} | "
                f"เสียงแรก {_seconds(fields, 'first_audio')} | "
                f"สังเคราะห์ประโยคแรก {_seconds(fields, 'synth_first')} | "
                f"รวม {_seconds(fields, 'total')} | {cards}")
    if kind == "reasoning":
        lines = [line.strip() for line in (fields.get("text") or "").splitlines() if line.strip()]
        return "คิด:\n         " + "\n         ".join(lines) if lines else "คิด: ไม่ได้คิดอะไร"
    if kind == "barge-in":
        where = "ระหว่างเล่นเสียง" if fields.get("during") == "playback" else "ระหว่างกำลังตอบ"
        return f"ถูกพูดแทรก {where} หยุดพูดแล้ว"
    if kind == "model-retry":
        return f"เรียกโมเดลใหม่ ครั้งที่ {fields.get('attempt')}: {fields.get('detail')}"
    if kind == "model-failed":
        return f"เรียกโมเดลไม่สำเร็จ: {fields.get('detail')}"
    if kind == "speech-retry":
        return f"สังเคราะห์เสียงใหม่ ครั้งที่ {fields.get('attempt')}: {fields.get('detail')}"
    if kind == "speech-failed":
        return f"สังเคราะห์เสียงไม่สำเร็จ: {fields.get('detail')}"
    if kind == "sentence-skipped":
        return f"ข้ามประโยคนี้เพราะพูดไม่ได้: {fields.get('detail')}"
    if kind == "brain-error":
        return f"ตอบไม่ได้รอบนี้: {fields.get('detail')}"
    if kind == "duplex":
        return f"ตัวช่วยเสียง: {fields.get('message')}"
    if kind == "duplex-ended":
        return f"ตัวช่วยเสียงหยุดทำงาน (รหัสจบ {fields.get('code')})"
    if kind == "usage":
        guess = " (ประมาณ)" if fields.get("estimated") else ""
        amount = f"{float(fields.get('quantity') or 0):g} {fields.get('unit') or '-'}"
        return (f"ค่าใช้จ่าย {fields.get('api')} ${float(fields.get('usd') or 0):.5f}{guess} | "
                f"{amount} | ใช้เวลา {_seconds(fields, 'seconds')}")
    if kind == "cost":
        usd = float(fields.get("total_usd") or 0)
        baht = float(fields.get("total_thb") or 0)
        label = "ค่าใช้จ่ายรอบนี้" if fields.get("final", True) else "ค่าใช้จ่ายสะสม"
        parts = ", ".join(f"{name} ${value:.4f}"
                          for name, value in (fields.get("by_api") or {}).items())
        return (f"{label} ${usd:.4f} (ราว ฿{baht:.2f}) | "
                f"เปิดคุย {_seconds(fields, 'session_seconds')} | "
                f"${float(fields.get('usd_per_hour') or 0):.3f}/ชม. | {parts or '-'}")
    if kind == "stopped":
        return f"หยุด: {fields.get('reason')}"
    if kind == "end":
        return "ปิดบันทึก"
    extra = " ".join(f"{name}={value}" for name, value in fields.items())
    return f"{kind} {extra}".strip()


class Journal:
    """ตัวบันทึก พิมพ์ออกจอและเขียนไฟล์ JSONL พร้อมกัน"""

    def __init__(self, path: pathlib.Path | None = None, echo: bool = True) -> None:
        self.path = path
        self.echo = echo
        self._lock = threading.Lock()
        self._began = time.monotonic()
        self._handle = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("a", encoding="utf-8")

    def note(self, kind: str, **fields) -> None:
        """บันทึกหนึ่งเหตุการณ์ ไม่โยนข้อผิดพลาดออกไปไม่ว่ากรณีใด"""
        elapsed = time.monotonic() - self._began
        try:
            if self.echo:
                line = f"{elapsed:6.1f}s  {describe(kind, fields)}"
                if sys.stdout.isatty():
                    line = f"{DIM}{line}{RESET}"
                print(line, flush=True)
            if self._handle is not None:
                record = {
                    "at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "since": round(elapsed, 3),
                    "kind": kind,
                    **fields,
                }
                with self._lock:
                    self._handle.write(
                        json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    self._handle.flush()
        except (OSError, ValueError, TypeError):
            pass

    def close(self) -> None:
        """ปิดไฟล์บันทึก"""
        if self._handle is None:
            return
        try:
            with self._lock:
                self._handle.close()
        except OSError:
            pass
        self._handle = None


def default_path() -> pathlib.Path:
    """ชื่อไฟล์บันทึกของรอบนี้ ตั้งตามเวลาที่เริ่ม"""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return LOG_DIR / f"live-{stamp}.jsonl"


def start(path: pathlib.Path | None = None, echo: bool = True) -> "Journal":
    """เริ่มบันทึก ถ้าเขียนไฟล์ไม่ได้ก็ยังพิมพ์ออกจอต่อไป"""
    global _active
    try:
        _active = Journal(path, echo=echo)
    except OSError as error:
        print(f"เขียนไฟล์บันทึกไม่ได้ {path}: {error}", file=sys.stderr)
        _active = Journal(None, echo=echo)
    return _active


def note(kind: str, **fields) -> None:
    """บันทึกเหตุการณ์ ถ้ายังไม่ได้เริ่มบันทึกก็ไม่ทำอะไร"""
    if _active is not None:
        _active.note(kind, **fields)


def stop() -> None:
    """ปิดบันทึกของรอบนี้"""
    global _active
    if _active is not None:
        _active.close()
        _active = None
