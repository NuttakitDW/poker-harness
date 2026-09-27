"""ความจำของผู้ใช้แต่ละคน เก็บไว้ที่เบราว์เซอร์แทนเซิร์ฟเวอร์

บน Vercel แต่ละคำขออาจไปเจอเครื่องใหม่ ความจำในหน่วยความจำจึงหายได้ทุกครั้ง
เซิร์ฟเวอร์ส่ง state กลับไปกับทุกคำตอบ หน้าเว็บส่งกลับมากับคำถามถัดไป
ลงลายเซ็น HMAC ไว้ แก้เองไม่ได้ เก่ากว่า MAX_AGE หรือลายเซ็นไม่ตรงก็เริ่มความจำใหม่
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import hmac
import json
import time
from typing import Callable

import assistant
import chat
import preflop

MAX_AGE = 7 * 24 * 3600
REQUEST_FIELDS = {field.name for field in dataclasses.fields(preflop.Request)}
TUPLE_FIELDS = ("shovers", "payouts")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _request(data: dict | None) -> preflop.Request | None:
    if data is None:
        return None
    fields = {key: value for key, value in data.items() if key in REQUEST_FIELDS}
    for key in TUPLE_FIELDS:
        if isinstance(fields.get(key), list):
            fields[key] = tuple(fields[key])
    return preflop.Request(**fields)


class Codec:
    """แปลง Session เป็น token ที่ลงลายเซ็น และแปลงกลับ"""

    def __init__(self, secret: bytes, max_age: float = MAX_AGE,
                 clock: Callable[[], float] = time.time) -> None:
        self._secret = secret
        self._max_age = max_age
        self._clock = clock

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._secret, body.encode(), hashlib.sha256).digest())

    def encode(self, session: chat.Session) -> str:
        memory = session.memory
        turns = session.history[-assistant.MAX_HISTORY_TURNS:]
        data = {"m": dataclasses.asdict(memory) if isinstance(memory, preflop.Request) else None,
                "h": [[turn.user, turn.assistant] for turn in turns],
                "a": session.ai, "t": int(self._clock())}
        body = _b64(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())
        return f"{body}.{self._sign(body)}"

    def decode(self, token: object) -> chat.Session:
        """Session จาก token ใช้ไม่ได้ด้วยเหตุใดก็ตามคือเริ่มความจำใหม่ ไม่ใช่ error"""
        if not isinstance(token, str) or token.count(".") != 1:
            return chat.Session()
        body, signature = token.split(".")
        if not hmac.compare_digest(signature, self._sign(body)):
            return chat.Session()
        try:
            data = json.loads(_unb64(body))
            if self._clock() - data["t"] > self._max_age:
                return chat.Session()
            history = tuple(assistant.Turn(user, said) for user, said in data["h"])
            return chat.Session(memory=_request(data["m"]), ai=bool(data["a"]),
                                history=history[-assistant.MAX_HISTORY_TURNS:])
        except (binascii.Error, ValueError, KeyError, TypeError):
            return chat.Session()
