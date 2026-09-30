"""บอท ตามควาย แบบคำสั่ง / รับคำสั่งจาก Discord ทาง HTTP ที่ /api/discord บน Vercel ไม่ต้องมีเครื่องเปิดค้าง

Discord ส่งคำสั่งมาเป็น POST ที่ลงลายเซ็น Ed25519 ต้องตอบภายใน 3 วินาที แต่ solver ตอนเครื่องเย็นช้ากว่านั้น
จึงตอบรับว่า "กำลังคิด" ผ่าน callback ก่อน ตอบ 202 แล้วค่อยคิดต่อหลังส่งคำตอบ (wait_until ของ Vercel)
เสร็จแล้วแก้ข้อความ "กำลังคิด" เป็นคำตอบจริง (slash_answer.py)

ไฟล์นี้ต้องเบา import แค่ของที่ใช้ตอบรับ solver โหลดทีหลังในงานที่ต่อหลังตอบ ไม่งั้นเครื่องเย็นตอบไม่ทัน 3 วินาที

ต้องตั้ง DISCORD_PUBLIC_KEY (Developer Portal > General Information > Public Key)
ลงทะเบียนคำสั่งกับตั้ง URL: make bot-commands (slash_commands.py)
"""

from __future__ import annotations

import asyncio
import dataclasses
import http
import json
import os
import threading
import time
import traceback
from collections.abc import Callable, Mapping

import discord_api
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

PATH = "/api/discord"
PING, COMMAND = 1, 2
PONG = 1
DEFERRED = discord_api.DEFERRED
EPHEMERAL = discord_api.EPHEMERAL
MAX_BODY = 100_000
MAX_SKEW = 300  # วินาที ลายเซ็นเก่ากว่านี้ไม่รับ กันคนดักคำขอไปยิงซ้ำให้ solver กับ AI ทำงานฟรี
# คำถามชาร์ตให้ทั้งห้องเห็นเหมือนบอทเดิม คำสั่งอื่นเห็นเฉพาะคนพิมพ์ ไม่รกห้อง
PUBLIC_COMMANDS = ("chart", "screenshot")


def verify(public_key: str, signature: str, timestamp: str, body: bytes) -> bool:
    """ลายเซ็นของ Discord ถูกต้องไหม ค่าเพี้ยนทุกแบบคือไม่ผ่าน ไม่ใช่ error"""
    try:
        VerifyKey(bytes.fromhex(public_key)).verify(timestamp.encode() + body, bytes.fromhex(signature))
    except (BadSignatureError, ValueError, TypeError):
        return False
    return True


@dataclasses.dataclass(frozen=True)
class Interaction:
    """คำสั่งหนึ่งครั้ง เก็บเฉพาะที่ต้องใช้ตอบ"""

    id: str
    token: str
    application_id: str
    type: int
    command: str | None = None
    options: Mapping[str, object] = dataclasses.field(default_factory=dict)
    attachments: Mapping[str, Mapping] = dataclasses.field(default_factory=dict)
    user_id: str | None = None
    channel_id: str | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> Interaction:
        data = payload.get("data") or {}
        # ในห้องของ server คนพิมพ์อยู่ใน member ใน DM อยู่ใน user
        user = (payload.get("member") or {}).get("user") or payload.get("user") or {}
        channel = payload.get("channel_id") or (payload.get("channel") or {}).get("id")
        return cls(id=str(payload["id"]), token=str(payload["token"]),
                   application_id=str(payload["application_id"]), type=int(payload["type"]),
                   command=data.get("name"),
                   options={item["name"]: item.get("value") for item in data.get("options") or ()},
                   attachments=(data.get("resolved") or {}).get("attachments") or {},
                   user_id=user.get("id"), channel_id=channel)

    def option(self, name: str, default: object = None) -> object:
        return self.options.get(name, default)

    def attachment(self, name: str) -> Mapping | None:
        """ไฟล์ที่แนบในช่อง name ของคำสั่ง (ค่าของช่องคือ id ไฟล์อยู่ใน resolved)"""
        return self.attachments.get(str(self.option(name)))


def schedule_after_response(job: Callable[[], None]) -> None:
    """ทำ job ต่อหลังตอบ Discord แล้ว

    บน Vercel ใช้ wait_until ให้เครื่องไม่หยุดจน job เสร็จ (ไม่เกิน maxDuration ใน vercel.json)
    runtime ของ Vercel ใส่ wait_until ไว้ใน vercel.cache.context ทุกคำขอ vercel.functions.wait_until ก็อ่านจากที่เดียวกัน
    ถ้าบน Vercel ไม่มี wait_until ให้ใช้ ทำเลยก่อนตอบ เธรดจะถูกแช่แข็งพร้อมเครื่องหลังตอบแล้วไม่ได้ทำ
    ตอบรับผ่าน callback ไปแล้ว คำตอบ HTTP ช้าได้ ในเครื่องใช้เธรด
    """
    try:
        from vercel.cache.context import get_context
        wait_until = get_context().wait_until
        if wait_until is not None:
            wait_until(asyncio.to_thread(job))
            return
    except Exception:  # noqa: BLE001 ใช้ wait_until ไม่ได้ด้วยเหตุใดก็ตาม ยังต้องทำงานให้เสร็จ
        traceback.print_exc()
    if os.environ.get("VERCEL"):
        job()
        return
    threading.Thread(target=job, daemon=True).start()


def answer_later(interaction: Interaction, api: discord_api.Api) -> None:
    """งานหลังตอบรับ โหลด solver ตรงนี้ ไม่ใช่ตอน import"""
    import slash_answer
    slash_answer.run(interaction, api)


@dataclasses.dataclass(frozen=True)
class Endpoint:
    public_key: str | None
    api: discord_api.Api = dataclasses.field(default_factory=discord_api.Api)
    schedule: Callable[[Callable[[], None]], None] = schedule_after_response
    work: Callable[[Interaction, discord_api.Api], None] = answer_later
    clock: Callable[[], float] = time.time

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Endpoint:
        key = (env.get("DISCORD_PUBLIC_KEY") or "").strip() or None
        if key is None:
            print("ไม่มี DISCORD_PUBLIC_KEY คำสั่ง / ของ Discord จะถูกปฏิเสธทั้งหมด", flush=True)
        return cls(public_key=key)

    def handle(self, method: str, headers: Mapping[str, str], body: bytes) -> tuple[int, dict | None]:
        """(สถานะ HTTP, JSON ที่ตอบ) headers ใช้ชื่อตัวพิมพ์เล็ก"""
        if method != "POST":
            return 405, {"error": "POST only"}
        if not self.public_key:
            return 503, {"error": "DISCORD_PUBLIC_KEY is not set"}
        timestamp = headers.get("x-signature-timestamp", "")
        if not verify(self.public_key, headers.get("x-signature-ed25519", ""), timestamp, body):
            return 401, {"error": "bad signature"}
        if not timestamp.isdigit() or abs(self.clock() - int(timestamp)) > MAX_SKEW:
            return 401, {"error": "stale signature"}
        try:
            payload = json.loads(body)
            if payload["type"] == PING:
                return 200, {"type": PONG}
            interaction = Interaction.from_payload(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
            return 400, {"error": "bad interaction"}
        if interaction.type != COMMAND:
            return 400, {"error": "unsupported interaction"}
        return self._accept(interaction)

    def _accept(self, interaction: Interaction) -> tuple[int, dict | None]:
        """ตอบรับผ่าน callback ก่อน ตอบรับแล้วถึงคำตอบ HTTP จะช้า (เช่น Vercel แบบเก่ารอ wait_until ก่อนส่ง)
        Discord ก็ไม่ตัด ถ้า callback พังตอบรับทางคำตอบ HTTP แทน"""
        ephemeral = interaction.command not in PUBLIC_COMMANDS
        job = lambda: self.work(interaction, self.api)  # noqa: E731
        try:
            self.api.defer(interaction.id, interaction.token, ephemeral)
        except (discord_api.DiscordError, OSError) as error:
            print(f"ตอบรับผ่าน callback ไม่ได้ ตอบทาง HTTP แทน: {error}", flush=True)
            self._start(job)
            return 200, {"type": DEFERRED, **({"data": {"flags": EPHEMERAL}} if ephemeral else {})}
        self._start(job)
        return 202, None

    def _start(self, job: Callable[[], None]) -> None:
        """ตั้งเวลาไม่ได้ก็ทำเลย ตอบรับไปแล้ว ข้อความ "กำลังคิด" ต้องได้คำตอบ"""
        try:
            self.schedule(job)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            job()


def wsgi(endpoint: Endpoint) -> Callable:
    """WSGI app ของ /api/discord api/index.py ส่งคำขอของทางนี้มาที่นี่"""

    def app(environ: dict, start_response: Callable) -> list[bytes]:
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            status, data = 413, {"error": "body too large"}
        else:
            headers = {key[5:].replace("_", "-").lower(): value
                       for key, value in environ.items() if key.startswith("HTTP_")}
            body = environ["wsgi.input"].read(length) if length else b""
            try:
                status, data = endpoint.handle(environ.get("REQUEST_METHOD", ""), headers, body)
            except Exception:  # noqa: BLE001 คำขอเดียวพังต้องไม่ทำให้ทั้งเว็บล่ม
                traceback.print_exc()
                status, data = 500, {"error": "internal error"}
        payload = b"" if data is None else json.dumps(data).encode()
        pairs = [("Content-Length", str(len(payload))), ("Cache-Control", "no-store")]
        if data is not None:
            pairs.append(("Content-Type", "application/json"))
        start_response(f"{status} {http.HTTPStatus(status).phrase}", pairs)
        return [payload]

    return app
