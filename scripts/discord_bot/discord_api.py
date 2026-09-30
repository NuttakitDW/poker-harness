"""เรียก REST API ของ Discord ด้วยไลบรารีมาตรฐาน สำหรับบอทคำสั่ง / ที่รันบน Vercel (slash.py)

ตอบรับคำสั่งผ่าน callback แก้ข้อความ "กำลังคิด" เป็นคำตอบพร้อมรูปชาร์ต โหลดรูปที่แนบมากับคำสั่ง
และคำขอทั่วไปที่ต้องใช้ bot token (ลงทะเบียนคำสั่งใน slash_commands.py)
ของที่ส่งออกเน็ตจริงอยู่ใน send ตัวเดียว test แทนด้วยของปลอมได้
"""

from __future__ import annotations

import dataclasses
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

API = "https://discord.com/api/v10"
# Discord ปฏิเสธ User-Agent ของ urllib ต้องขึ้นต้นแบบนี้
USER_AGENT = "DiscordBot (https://tamkwai.com, 1.0)"
TIMEOUT = 15
DEFER_TIMEOUT = 2.0  # การตอบรับต้องถึง Discord ใน 3 วินาที รอนานกว่านี้ก็ไม่มีประโยชน์
MAX_CONTENT = 2000  # ข้อความหนึ่งข้อความของ Discord ยาวได้เท่านี้
MAX_READ = 16_000_000
DEFERRED = 5
EPHEMERAL = 64  # เห็นเฉพาะคนที่พิมพ์คำสั่ง
# รูปที่แนบมากับคำสั่งอยู่ที่ CDN ของ Discord เท่านั้น ไม่โหลดจากที่อื่น กันถูกใช้ยิงเข้าเครือข่ายภายใน
CDN_HOSTS = ("cdn.discordapp.com", "media.discordapp.net")
FENCE = "```"

Send = Callable[[str, str, dict, "bytes | None", float], "tuple[int, bytes]"]


class DiscordError(Exception):
    """Discord ตอบว่าไม่รับ หรือขอสิ่งที่ไม่ควรขอ"""


def on_discord(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and parts.hostname in (*CDN_HOSTS, "discord.com")


class _DiscordOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """ตามการย้ายที่เฉพาะไปที่ของ Discord เอง ย้ายไปที่อื่นคือไม่รับ"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 ลายเซ็นของ urllib
        if not on_discord(newurl):
            raise urllib.error.HTTPError(newurl, code, "redirect outside Discord", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_DiscordOnlyRedirect)


def urllib_send(method: str, url: str, headers: dict, body: bytes | None,
                timeout: float = TIMEOUT) -> tuple[int, bytes]:
    """ส่งจริง สถานะ 4xx/5xx คืนเป็นค่า ไม่ใช่ exception เน็ตหลุดยังเป็น OSError เหมือนเดิม"""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read(MAX_READ)
    except urllib.error.HTTPError as error:
        return error.code, error.read(MAX_READ)


def truncate(text: str, limit: int = MAX_CONTENT) -> str:
    """ตัดให้พอดีข้อความเดียว ถ้าตัดกลาง code block ปิดให้ด้วย"""
    if len(text) <= limit:
        return text
    cut = text[:limit - 1] + "…"
    if cut.count(FENCE) % 2 == 0:
        return cut
    return text[:limit - len(FENCE) - 2] + "…\n" + FENCE


def message_payload(content: str, filename: str | None = None) -> dict:
    """ข้อความที่จะส่ง ห้ามแท็กใครเสมอ เพราะมีส่วนที่คนนอกบังคับได้ (คำถาม คำตอบ AI ข้อความจากรูป)"""
    attachments = [{"id": 0, "filename": filename}] if filename else []
    return {"content": truncate(content), "allowed_mentions": {"parse": []}, "attachments": attachments}


def multipart(payload: dict, filename: str, data: bytes) -> tuple[str, bytes]:
    """(Content-Type, body) แบบ multipart/form-data ที่ Discord ใช้แนบไฟล์"""
    boundary = secrets.token_hex(16)
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
            f"Content-Type: application/json\r\n\r\n{json.dumps(payload, ensure_ascii=False)}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{filename}\"\r\n"
            f"Content-Type: image/png\r\n\r\n")
    return f"multipart/form-data; boundary={boundary}", head.encode() + data + f"\r\n--{boundary}--\r\n".encode()


@dataclasses.dataclass(frozen=True)
class Api:
    send: Send = urllib_send
    base: str = API

    def _call(self, method: str, path: str, content_type: str | None = None, body: bytes | None = None,
              token: str | None = None, timeout: float = TIMEOUT) -> bytes:
        headers = {"User-Agent": USER_AGENT}
        if content_type:
            headers["Content-Type"] = content_type
        if token:
            headers["Authorization"] = f"Bot {token}"
        status, reply = self.send(method, self.base + path, headers, body, timeout)
        if status >= 300:
            # path มี token ของคำสั่งอยู่ เอาไปใช้ตอบแทนบอทได้ จึงไม่พิมพ์ทั้งเส้นลง log
            raise DiscordError(f"{method} {path.split('/')[1]} -> {status}: {reply[:300]!r}")
        return reply

    def defer(self, interaction_id: str, token: str, ephemeral: bool) -> None:
        """ตอบรับคำสั่งว่า "กำลังคิด" ภายใน 3 วินาที คำตอบจริงตามมาด้วย edit_original"""
        data = {"type": DEFERRED, **({"data": {"flags": EPHEMERAL}} if ephemeral else {})}
        self._call("POST", f"/interactions/{interaction_id}/{token}/callback", "application/json",
                   json.dumps(data).encode(), timeout=DEFER_TIMEOUT)

    def edit_original(self, application_id: str, token: str, content: str,
                      file: tuple[str, bytes] | None = None) -> None:
        """แทนข้อความ "กำลังคิด" ด้วยคำตอบ file คือ (ชื่อไฟล์, PNG) ใช้ได้ 15 นาทีหลังคนพิมพ์คำสั่ง"""
        path = f"/webhooks/{application_id}/{token}/messages/@original"
        if file is None:
            self._call("PATCH", path, "application/json", json.dumps(message_payload(content)).encode())
            return
        filename, data = file
        content_type, body = multipart(message_payload(content, filename), filename, data)
        self._call("PATCH", path, content_type, body)

    def download(self, url: str) -> bytes:
        """ไฟล์ที่แนบมากับคำสั่ง จาก CDN ของ Discord เท่านั้น"""
        if urllib.parse.urlsplit(url).hostname not in CDN_HOSTS or not on_discord(url):
            raise DiscordError("attachment is not on the Discord CDN")
        status, data = self.send("GET", url, {"User-Agent": USER_AGENT}, None, TIMEOUT)
        if status != 200:
            raise DiscordError(f"attachment -> {status}")
        return data

    def bot(self, method: str, path: str, token: str, payload: object = None) -> object:
        """คำขอที่ใช้ bot token คืน JSON ที่ Discord ตอบ"""
        body = None if payload is None else json.dumps(payload).encode()
        reply = self._call(method, path, "application/json" if body else None, body, token)
        return json.loads(reply) if reply else None
