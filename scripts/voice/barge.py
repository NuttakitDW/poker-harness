"""หยุดพูดทันทีที่ผู้ใช้เริ่มพูดแทรก

ตัวฟังจะส่งช่วงเสียงออกมาก็ต่อเมื่อผู้ใช้พูดจบและเงียบไปพักหนึ่งแล้ว ถ้ารอจังหวะนั้น
ลูกชุบจะพูดทับผู้ใช้ไปตลอดประโยค จึงต้องเฝ้าสัญญาณ "กำลังมีคนพูด" แยกในเธรดของตัวเอง
แล้วตัดเสียงตั้งแต่พยางค์แรกที่ได้ยิน
"""

from __future__ import annotations

import threading

POLL_SECONDS = 0.03


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
            if self._listener.speaking:
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
