"""หยุดพูดทันทีที่ผู้ใช้เริ่มพูดแทรก

ตัวฟังจะส่งช่วงเสียงออกมาก็ต่อเมื่อผู้ใช้พูดจบและเงียบไปพักหนึ่งแล้ว ถ้ารอจังหวะนั้น
ลูกชุบจะพูดทับผู้ใช้ไปตลอดประโยค จึงต้องเฝ้าสัญญาณ "กำลังมีคนพูด" แยกในเธรดของตัวเอง
แล้วตัดเสียงตั้งแต่พยางค์แรกที่ได้ยิน
"""

from __future__ import annotations

import threading
import time

POLL_SECONDS = 0.03
# คนที่เพิ่งพูดแทรกมักเว้นจังหวะคิดแล้วพูดต่อ ต้องเงียบนานเท่านี้ก่อนลูกชุบจะเปิดปาก
# เคยตั้ง 1.2 วินาที ซึ่งสั้นกว่าเวลารอโมเดลอยู่แล้ว จึงไม่ได้รอเพิ่มเลย
HOLD_SECONDS = 2.0
# ตอบคนที่เพิ่งพูดแทรกแค่นี้พอ ยาวกว่านี้จะกลายเป็นพูดสวนกันไปมา
# ภาษาไทยไม่มีจุดจบประโยค ประโยคเดียวจึงยาวได้ถึง 70 ตัว ต้องคุมจำนวนตัวอักษรด้วย
BRIEF_MAX_SENTENCES = 1
BRIEF_MAX_CHARS = 40


class BargeWatch:
    """เฝ้าไมค์ระหว่างที่ลูกชุบกำลังตอบ ได้ยินเสียงคนเมื่อไรสั่งหยุดเสียงทันที"""

    def __init__(self, listener, player, poll: float = POLL_SECONDS) -> None:
        self._listener = listener
        self._player = player
        self._poll = poll
        self._stopped = threading.Event()
        self._fired = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stopped.wait(self._poll):
            # พูดตอนลูกชุบพูดจบไปแล้วไม่ใช่การแทรก เป็นแค่ตาของเขา
            if self._listener.speaking and self._player.busy:
                self._fired.set()
                self._player.interrupt()
                return

    @property
    def fired(self) -> bool:
        """ถูกพูดแทรกจนต้องหยุดเสียงไปแล้วหรือยัง"""
        return self._fired.is_set()

    def stop(self) -> None:
        """เลิกเฝ้า ใช้เมื่อคำตอบนี้จบหรือถูกแทนด้วยคำตอบใหม่"""
        self._stopped.set()
        self._thread.join()


def hold_for_more(listener, since: float, hold: float = HOLD_SECONDS,
                  poll: float = POLL_SECONDS) -> bool:
    """รอให้ผู้ใช้เงียบครบ hold วินาทีนับจาก since แบบ monotonic

    คืน True ถ้าเขาพูดต่อระหว่างรอ แปลว่ายังพูดไม่จบ ลูกชุบควรฟังต่อแทนที่จะตอบ
    """
    while time.monotonic() - since < hold:
        if listener.speaking or listener.waiting:
            return True
        time.sleep(poll)
    return bool(listener.speaking or listener.waiting)


def clip(sentence: str, limit: int = BRIEF_MAX_CHARS) -> str:
    """ตัดคำตอบให้สั้น ตัดที่ช่องว่างระหว่างวลีเท่านั้น ไม่ตัดกลางคำ"""
    if len(sentence) <= limit:
        return sentence
    cut = sentence.rfind(" ", 0, limit + 1)
    return sentence[:cut].rstrip() if cut > 0 else sentence
