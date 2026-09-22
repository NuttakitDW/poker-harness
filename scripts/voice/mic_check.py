"""ตรวจว่าไมโครโฟนส่งเสียงเข้ามาจริงและ VAD ตัดสินถูก

ใช้ก่อนเปิดโหมดสนทนาสด เพื่อแยกว่าปัญหาอยู่ที่การรับเสียง ที่สิทธิ์ไมโครโฟน
หรือที่การตัดสินขอบเขตประโยค

ใช้: .venv-whisper/bin/python scripts/voice/mic_check.py [วินาที]
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import listen  # noqa: E402

BAR_WIDTH = 30


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    use_aec = "--echo-cancel" in sys.argv

    import numpy

    detector = listen.Detector()
    started = time.perf_counter()
    frames = 0
    silent_frames = 0
    peak = 0.0
    turns = 0

    print(f"พูดใส่ไมค์ได้เลย จะฟัง {seconds:.0f} วินาที\n")
    announced = False
    for frame in listen.frames(echo_cancel=use_aec):
        if not announced:
            announced = True
            print("ทางรับเสียง: ตัวตัดเสียงสะท้อนของระบบ (เปิดลำโพงได้ พูดแทรกได้)"
                  if listen.echo_cancel_active()
                  else "ทางรับเสียง: ไมค์ปกติ ไม่มีตัวตัดเสียงสะท้อน (ต้องผลัดกันพูด)")
        frames += 1
        level = float(numpy.abs(frame).max())
        peak = max(peak, level)
        if level < 1e-6:
            silent_frames += 1

        probability = detector._probability(frame)
        if frames % 6 == 0:
            filled = int(min(level * 8, 1.0) * BAR_WIDTH)
            state = "พูด " if probability >= listen.SPEECH_THRESHOLD else "เงียบ"
            line = (f"{state} [{'#' * filled}{'.' * (BAR_WIDTH - filled)}] "
                    f"ระดับ {level:.3f}  vad {probability:.2f}  ประโยคที่ปิดได้ {turns}")
            print(f"\r{line:<80}", end="", flush=True)

        if detector.push(frame):
            turns += 1

        if time.perf_counter() - started > seconds:
            break

    print("\n")
    if frames == 0:
        print("ไม่ได้รับเฟรมเสียงเลย — ตัวจับเสียงไม่ทำงาน")
        return 1
    if silent_frames == frames:
        print("ได้รับเฟรมแต่เป็นศูนย์ทั้งหมด — น่าจะไม่ได้รับสิทธิ์ไมโครโฟน")
        print("เปิด System Settings > Privacy & Security > Microphone แล้วอนุญาตให้ Terminal")
        return 1

    mode = "มีตัวตัดเสียงสะท้อน" if listen.echo_cancel_active() else "ไม่มีตัวตัดเสียงสะท้อน"
    print(f"รับเฟรม {frames} เฟรม  ระดับสูงสุด {peak:.3f}  ปิดประโยคได้ {turns} ครั้ง  [{mode}]")
    if peak < 0.01:
        print("เสียงเบามาก ลองพูดใกล้ไมค์ขึ้นหรือเพิ่มระดับอินพุตในระบบ")
    elif turns == 0:
        print("ได้ยินเสียงแต่ไม่เคยปิดประโยค ลองพูดให้ยาวขึ้นแล้วเงียบสักครู่")
    else:
        print("ไมโครโฟนและการตัดประโยคทำงานปกติ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
