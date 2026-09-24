"""คลื่นเสียงในเทอร์มินัลระหว่างที่ผู้ใช้พูด ให้เห็นว่าเสียงไปถึงลูกชุบแล้วจริง

ถ้าไม่มีอะไรขยับตอนพูด ผู้ใช้จะไม่แน่ใจว่าไมค์ติดไหม แล้วพูดซ้ำทับประโยคเดิม
บรรทัดคลื่นวาดทับตัวเองด้วย \\r อยู่บรรทัดล่างสุด ข้อความอื่นที่พิมพ์ออกมาจะลบบรรทัดนี้ก่อน
แล้วบรรทัดคลื่นค่อยวาดใหม่ใต้ข้อความนั้น จึงไม่ปนกัน
"""

from __future__ import annotations

import collections
import math
import shutil
import sys
import threading
import time
import unicodedata

BARS = " ▁▂▃▄▅▆▇█"
WAVE_WIDTH = 28
# เสียงพูดปกติจากไมค์โน้ตบุ๊กอยู่ราว -40 ถึง -15 dBFS ช่วงนี้จึงกินความสูงของแท่งทั้งหมด
FLOOR_DB = -55.0
CEILING_DB = -12.0
# ต่ำกว่านี้ถือเป็นเสียงห้องหรือเสียงสะท้อนที่เหลือ ไม่ใช่คนพูด
ACTIVE_LEVEL = 0.25
# ค้างคลื่นไว้ครู่หนึ่งหลังเสียงเงียบ ช่วงหยุดหายใจกลางประโยคจะได้ไม่ทำให้คลื่นกะพริบ
HOLD_SECONDS = 1.2
FRAMES_PER_SECOND = 20
LABEL = "ลูกชุบกำลังฟัง"
ELLIPSIS = "…"

CLEAR = "\r\033[K"
BLUE = "\033[1;34m"
DIM = "\033[2m"
RESET = "\033[0m"


def level_of(frame) -> float:
    """ความดังของเฟรมเป็นสเกล 0 ถึง 1 ตามเดซิเบล หูคนรับรู้ความดังแบบลอการิทึม"""
    if len(frame) == 0:
        return 0.0
    rms = math.sqrt(float((frame.astype("float64") ** 2).mean()))
    if rms <= 0.0:
        return 0.0
    db = 20.0 * math.log10(rms)
    return min(1.0, max(0.0, (db - FLOOR_DB) / (CEILING_DB - FLOOR_DB)))


def bar(level: float) -> str:
    """แท่งหนึ่งช่องตามความดัง"""
    return BARS[round(min(1.0, max(0.0, level)) * (len(BARS) - 1))]


def display_width(text: str) -> int:
    """ความกว้างบนจอ สระบนล่างและวรรณยุกต์ไทยซ้อนบนตัวอักษรอื่น จึงไม่กินช่อง"""
    return sum(0 if unicodedata.category(char) in ("Mn", "Me", "Cf") else 1 for char in text)


def tail_fit(text: str, width: int) -> str:
    """ตัดข้อความให้พอดีช่อง เก็บท้ายไว้ เพราะคำล่าสุดที่เพิ่งพูดคือสิ่งที่อยากเห็น"""
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    kept: list[str] = []
    used = 0
    for char in reversed(text):
        step = display_width(char)
        if used + step > width - 1:
            break
        kept.append(char)
        used += step
    # อย่าให้บรรทัดเริ่มด้วยสระหรือวรรณยุกต์ที่ไม่มีตัวอักษรให้เกาะ
    while kept and display_width(kept[-1]) == 0:
        kept.pop()
    return ELLIPSIS + "".join(reversed(kept))


def render(levels, heard: str, columns: int, color: bool = True, label: str = LABEL) -> str:
    """บรรทัดคลื่นหนึ่งบรรทัด: ป้าย คลื่น แล้วคำที่ถอดได้ระหว่างพูด"""
    wave = "".join(bar(level) for level in levels).rjust(WAVE_WIDTH)
    lead = f"  {label}  "
    room = columns - display_width(lead) - WAVE_WIDTH - 2
    words = tail_fit(heard, room) if heard else ""
    if not color:
        return f"{lead}{wave}  {words}".rstrip()
    return f"{DIM}{lead}{RESET}{BLUE}{wave}{RESET}  {words}".rstrip()


class _Guarded:
    """ห่อ stdout ไว้ ข้อความอื่นจะลบบรรทัดคลื่นก่อนเขียนเสมอ"""

    def __init__(self, meter: "Meter", stream) -> None:
        self._meter = meter
        self._stream = stream

    def write(self, text: str) -> int:
        with self._meter.lock:
            self._meter.erase()
            return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


class Meter:
    """รับระดับเสียงและคำที่ถอดได้จากเธรดฟังไมค์ แล้ววาดคลื่นจากเธรดของตัวเอง

    วาดเฉพาะตอนมีเสียงพูดหรือมีคำกำลังทยอยเข้ามา เงียบเมื่อไรก็ลบบรรทัดทิ้ง
    ถ้า stdout ไม่ใช่เทอร์มินัล เช่นส่งต่อเข้าไฟล์ จะไม่ทำอะไรเลย
    """

    def __init__(self, stream=None, clock=time.monotonic, label: str = LABEL) -> None:
        self._label = label
        self._stream = stream if stream is not None else sys.stdout
        self._clock = clock
        self._levels: collections.deque = collections.deque(maxlen=WAVE_WIDTH)
        self._heard = ""
        self._loud_at = -math.inf
        self._drawn = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._saved = None
        self.lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._stream, "isatty", lambda: False)())

    def feed(self, frame) -> None:
        """รับเฟรมเสียงหนึ่งเฟรมจากไมค์"""
        level = level_of(frame)
        with self.lock:
            self._levels.append(level)
            if level >= ACTIVE_LEVEL:
                self._loud_at = self._clock()

    def hear(self, text: str) -> None:
        """รับคำที่ถอดได้แล้วระหว่างที่ยังพูดไม่จบ สตริงว่างคือพูดจบแล้ว"""
        with self.lock:
            self._heard = text

    @property
    def active(self) -> bool:
        """มีเสียงพูดหรือคำที่ยังพูดไม่จบอยู่ตอนนี้"""
        with self.lock:
            return bool(self._heard) or self._clock() - self._loud_at < HOLD_SECONDS

    def erase(self) -> None:
        """ลบบรรทัดคลื่นออกจากจอ ถ้าวาดไว้อยู่"""
        with self.lock:
            if self._drawn:
                self._stream.write(CLEAR)
                self._drawn = False

    def draw(self) -> None:
        """วาดบรรทัดคลื่นหนึ่งรอบ หรือลบทิ้งถ้าไม่มีใครพูด"""
        with self.lock:
            if not self.active:
                self.erase()
                self._stream.flush()
                return
            columns = shutil.get_terminal_size((80, 24)).columns
            line = render(tuple(self._levels), self._heard, columns, label=self._label)
            self._stream.write(CLEAR + line)
            self._stream.flush()
            self._drawn = True

    def _run(self) -> None:
        while not self._stop.wait(1.0 / FRAMES_PER_SECOND):
            try:
                self.draw()
            except (OSError, ValueError):
                return

    def start(self) -> "Meter":
        """เริ่มวาด และให้ข้อความอื่นที่พิมพ์ผ่าน stdout ลบบรรทัดคลื่นก่อนเขียน"""
        if not self.enabled or self._thread is not None:
            return self
        self._saved = sys.stdout
        sys.stdout = _Guarded(self, self._stream)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """หยุดวาด ลบบรรทัดที่ค้าง แล้วคืน stdout เดิม"""
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._thread = None
        with self.lock:
            self.erase()
            self._stream.flush()
        if self._saved is not None:
            sys.stdout = self._saved
            self._saved = None

    def __enter__(self) -> "Meter":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()
