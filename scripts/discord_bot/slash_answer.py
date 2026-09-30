"""คำตอบของคำสั่ง / ส่วนที่ทำหลังตอบรับ Discord แล้ว (slash.py เรียกผ่าน wait_until)

ใช้ solver, AI และตัวอ่านรูปชุดเดียวกับเว็บ (scripts/web/chat.py)
ความจำของแต่ละคนต่อห้องอยู่ใน Runtime Cache ของ Vercel ไม่เกิน MEMORY_TTL เพราะแต่ละคำสั่งอาจไปเจอเครื่องใหม่
กุญแจในแคชเป็น HMAC ของห้องกับคน ไม่เก็บไอดีตรง ๆ ตามที่บอกใน /privacy
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import functools
import hashlib
import hmac
import os
import pathlib
import secrets
import sys
import traceback
from collections.abc import Callable
from typing import Protocol

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "web"))

import chat  # noqa: E402
import discord_api  # noqa: E402
import question_log  # noqa: E402
import server  # noqa: E402
import spot_chart  # noqa: E402
import state  # noqa: E402

MEMORY_TTL = 24 * 3600
# maxDuration ใน vercel.json คือ 60 วินาที เผื่อเวลาโหลด solver ตอนเครื่องเย็นกับส่งคำตอบ
ANSWER_SECONDS = 40
NAMESPACE = "tamkwai-discord"
PLACE = {"server": "discord", "channel": None}  # ตั้งใจไม่เก็บว่าใครถาม server หรือห้องไหน
SLOW_DOWN = server.SLOW_DOWN
BUSY = server.BUSY
BAD_IMAGE = "แนบรูปโต๊ะเป็น PNG, JPEG, WebP หรือ GIF ไม่เกิน 10 MB นะ"
NOT_DOWNLOADED = "โหลดรูปจาก Discord ไม่ได้ ลองส่งใหม่อีกทีนะ"
UNKNOWN = "ไม่รู้จักคำสั่งนี้ ดูคำสั่งทั้งหมดได้ที่ /help"
TOO_SLOW = "คิดนานเกินไป ลองถามใหม่อีกทีนะ"
NO_PICTURE = "(ส่งรูปชาร์ตไม่สำเร็จ ลองถามใหม่อีกทีนะ)"
LANGS = ("th", "en")
SLASH_HELP = {
    "th": """ตามควาย · วิธีใช้ใน Discord
ชาร์ต chip EV push/fold, AoF และ PLO; ICM preflop สแตกเท่ากัน open/3-bet/jam ถึง 30bb

Commands
  /chart <คำถาม>        ถามชาร์ต
  /screenshot <รูป>     แนบรูปโต๊ะให้บอทอ่าน
  /new                  ลืม spot เดิม
  /ai on|off            เปิด/ปิด AI
  /help [th|en]         วิธีใช้นี้
  /contact              อีเมลผู้พัฒนา
  /privacy              บอทเก็บข้อมูลอะไรบ้าง

ตัวอย่าง: /chart 3 handed BTN open 15bb icm 50/30/20 no ante""",
    "en": """ตามควาย · How to use in Discord
Chip-EV push/fold, AoF and PLO; equal-stack ICM open/3-bet/jam to 30bb

Commands
  /chart <question>     ask for a chart
  /screenshot <image>   attach the table
  /new                  forget the spot
  /ai on|off            AI on/off
  /help [th|en]         this help
  /contact              developer email
  /privacy              what the bot keeps

Example: /chart 3 handed BTN open 15bb icm 50/30/20 no ante""",
}
PRIVACY = {
    "th": f"""ตามควาย · ความเป็นส่วนตัว (คำสั่ง /)
เก็บอะไร: คำถามที่ถามบอท กับคำถามชาร์ตที่ AI เขียนให้ (ถ้าเป็นรูปคือคำถามที่อ่านได้) เวลา และ spot ที่อ่านได้
ไม่เก็บ: ชื่อหรือไอดีของคนถาม ชื่อ server หรือห้อง ข้อความอื่นในห้อง และรูป
spot ล่าสุดกับบทสนทนากับ AI อยู่ในแคชชั่วคราวไม่เกิน {MEMORY_TTL // 3600} ชั่วโมง ผูกกับรหัสที่ย้อนกลับเป็นไอดีไม่ได้ ลบทันทีด้วย /new

เพื่ออะไร: ตอบคำถาม และหาคำถามที่บอทยังอ่านไม่ออกเพื่อปรับปรุง (ประโยชน์โดยชอบด้วยกฎหมาย ตาม PDPA มาตรา 24(5))
เก็บนานเท่าไร: ไม่เกิน {question_log.KEEP_DAYS} วัน

ส่งต่อให้ใคร:
  Discord  ข้อความทั้งหมดผ่าน Discord อยู่แล้ว
  DeepSeek คำถาม (โหมด AI ปิดได้ด้วย /ai off) และรูปหน้าจอ ส่งไปอ่าน เซิร์ฟเวอร์อยู่ในจีน บอทไม่เก็บรูป
  Vercel   เครื่องที่บอทรันกับแคชความจำ อยู่นอกประเทศไทย
ไม่ขาย ไม่ใช้โฆษณา

สิทธิ์ของคุณ: ขอดู ขอลบ หรือคัดค้านการเก็บ ส่งอีเมลมาที่ {spot_chart.CONTACT}
ถ้าไม่ต้องการให้เก็บ อย่าถามบอท""",
    "en": f"""ตามควาย · Privacy (slash commands)
What we keep: the text of questions to the bot and the chart query the AI wrote (for a screenshot, the question read from it), the time, and the spot the bot read
What we don't keep: your name or user ID, the server or channel name, other messages in the channel, or images
Your last spot and AI conversation sit in a temporary cache for up to {MEMORY_TTL // 3600} hours under a code that can't be turned back into your ID; /new deletes them at once

Why: to answer you, and to find questions the bot could not read so it can improve (legitimate interest, Thai PDPA s.24(5))
How long: at most {question_log.KEEP_DAYS} days

Who else sees it:
  Discord  every message already passes through Discord
  DeepSeek questions (AI mode, turn off with /ai off) and screenshots are sent to be read, on servers in China; the bot keeps no images
  Vercel   hosts the bot and the memory cache, outside Thailand
Never sold, never used for ads

Your rights: ask to see, delete, or object, by email to {spot_chart.CONTACT}
If you don't want anything kept, don't ask the bot""",
}


class Store(Protocol):
    def get(self, key: str) -> object: ...
    def set(self, key: str, value: object, options: dict | None = None) -> None: ...
    def delete(self, key: str) -> None: ...


@dataclasses.dataclass(frozen=True)
class Reply:
    content: str
    file: tuple[str, bytes] | None = None


class Memory:
    """chat.Session ของแต่ละคนในแต่ละห้อง เก็บเป็น token ที่ลงลายเซ็นแบบเดียวกับเว็บ

    แคชพังหรือหายก็แค่เริ่มความจำใหม่ ไม่ทำให้ตอบไม่ได้
    """

    def __init__(self, store: Store, codec: state.Codec, secret: bytes, ttl: int = MEMORY_TTL) -> None:
        self._store = store
        self._codec = codec
        self._secret = secret
        self._ttl = ttl

    def key(self, interaction) -> str:
        who = f"discord:{interaction.channel_id}:{interaction.user_id}".encode()
        return hmac.new(self._secret, who, hashlib.sha256).hexdigest()[:40]

    def load(self, interaction) -> chat.Session:
        try:
            return self._codec.decode(self._store.get(self.key(interaction)))
        except Exception:  # noqa: BLE001 แคชพังก็เริ่มความจำใหม่
            traceback.print_exc()
            return chat.Session()

    def save(self, interaction, session: chat.Session) -> None:
        try:
            self._store.set(self.key(interaction), self._codec.encode(session), {"ttl": self._ttl})
        except Exception:  # noqa: BLE001 จำไม่ได้ก็ยังตอบได้
            traceback.print_exc()

    def forget(self, interaction) -> None:
        self._store.delete(self.key(interaction))


@dataclasses.dataclass(frozen=True)
class Context:
    tools: chat.Tools
    memory: Memory
    limit: chat.RateLimit
    site_limit: chat.RateLimit


@functools.cache
def default_context() -> Context:
    """หนึ่งชุดต่อเครื่อง เพดานความถี่จึงนับต่อเนื่องระหว่างคำสั่งที่มาเจอเครื่องเดียวกัน"""
    from vercel.cache import RuntimeCache

    secret = (os.environ.get("WEB_STATE_SECRET") or "").encode()
    if not secret:
        print("ไม่มี WEB_STATE_SECRET สุ่มกุญแจใหม่ ถามต่อจะจำ spot ได้เฉพาะตอนเจอเครื่องเดิม", flush=True)
        secret = secrets.token_bytes(32)
    memory = Memory(RuntimeCache(namespace=NAMESPACE), state.Codec(secret), secret)
    return Context(tools=chat.Tools(place=dict(PLACE)), memory=memory, limit=chat.RateLimit(),
                   site_limit=chat.RateLimit(per_window=server.SITE_PER_MINUTE))


def _lang(interaction) -> str:
    lang = interaction.option("lang", "th")
    return lang if lang in LANGS else "th"


def _limited(interaction, context: Context) -> str | None:
    """นับเฉพาะคำสั่งที่ใช้ solver หรือ AI"""
    if not context.limit.allow(str(interaction.user_id)):
        return SLOW_DOWN
    if not context.site_limit.allow("site"):
        return BUSY
    return None


def _result(result: chat.Result, quote: str | None = None) -> Reply:
    lines = ((f"> {quote}",) if quote else ()) + result.lines
    file = None
    if result.chart:
        file = ("mario.png" if result.kind == "mario" else "chart.png", result.chart)
    return Reply("\n".join(lines), file)


def _chart(interaction, context: Context, api) -> Reply:
    question = interaction.option("question")
    problem = chat.invalid_question(question) if isinstance(question, str) else chat.EMPTY
    if problem:
        return Reply(problem)
    limited = _limited(interaction, context)
    if limited:
        return Reply(limited)
    result, after = chat.ask(question.strip(), context.memory.load(interaction), context.tools)
    context.memory.save(interaction, after)
    return _result(result, question.strip())


def _screenshot(interaction, context: Context, api) -> Reply:
    attached = interaction.attachment("image") or {}
    mime = str(attached.get("content_type") or "").split(";")[0].strip().lower()
    size = attached.get("size")
    if not chat.accepts_image(mime) or not isinstance(size, int) or size > chat.MAX_IMAGE_BYTES:
        return Reply(BAD_IMAGE)
    note = interaction.option("note")
    if note is not None and (not isinstance(note, str) or len(note) > chat.MAX_QUESTION_CHARS):
        return Reply(chat.TOO_LONG)
    limited = _limited(interaction, context)
    if limited:
        return Reply(limited)
    try:
        data = api.download(str(attached.get("url")))
    except (discord_api.DiscordError, OSError):
        traceback.print_exc()
        return Reply(NOT_DOWNLOADED)
    if len(data) > chat.MAX_IMAGE_BYTES:
        return Reply(BAD_IMAGE)
    result, after = chat.ask_image(data, mime, (note or "").strip() or None,
                                   context.memory.load(interaction), context.tools)
    context.memory.save(interaction, after)
    return _result(result)


def _new(interaction, context: Context, api) -> Reply:
    context.memory.forget(interaction)
    return Reply(chat.FORGOT)


def _ai(interaction, context: Context, api) -> Reply:
    said, after = chat.toggle_ai(context.memory.load(interaction), interaction.option("mode") != "off")
    context.memory.save(interaction, after)
    return Reply(said)


def _help(interaction, context: Context, api) -> Reply:
    lang = _lang(interaction)
    # คำสั่งเป็นของ Discord ตัวอย่างกับข้อจำกัดมาจาก make chart ใส่ code block ให้คอลัมน์ตรง
    return Reply(f"```\n{SLASH_HELP[lang]}\n\n{spot_chart.HELP_GUIDE[lang]}\n\n{spot_chart.COPYRIGHT}\n```")


def _privacy(interaction, context: Context, api) -> Reply:
    return Reply(f"```\n{PRIVACY[_lang(interaction)]}\n```")


def _contact(interaction, context: Context, api) -> Reply:
    return Reply(f"{spot_chart.CONTACT}\n{spot_chart.COPYRIGHT}")


ROUTES: dict[str, Callable] = {"chart": _chart, "screenshot": _screenshot, "new": _new, "ai": _ai,
                               "help": _help, "privacy": _privacy, "contact": _contact}


def answer(interaction, context: Context, api) -> Reply:
    route = ROUTES.get(interaction.command)
    return route(interaction, context, api) if route else Reply(UNKNOWN)


def _answer_within(interaction, context: Context, api, seconds: float) -> Reply:
    """คำตอบภายในเวลา เกินแล้วบอกว่าช้าไป ก่อน Vercel ตัดเครื่องทิ้งจนไม่ได้แก้ข้อความ "กำลังคิด" """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(answer, interaction, context, api)
    try:
        return future.result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        print(f"ตอบ /{interaction.command} ไม่ทันใน {seconds:.0f}s", flush=True)
        return Reply(TOO_SLOW)
    finally:
        pool.shutdown(wait=False)


def _deliver(interaction, api, reply: Reply) -> None:
    """แก้ข้อความ "กำลังคิด" พังก็ลองอีกครั้งเป็นข้อความอย่างเดียว (รูปใหญ่เกินหรือเน็ตสะดุด)"""
    try:
        api.edit_original(interaction.application_id, interaction.token, reply.content, reply.file)
        return
    except (discord_api.DiscordError, OSError):
        traceback.print_exc()
    content = "\n".join(filter(None, (reply.content, NO_PICTURE if reply.file else None)))
    try:
        api.edit_original(interaction.application_id, interaction.token, content, None)
    except (discord_api.DiscordError, OSError):
        traceback.print_exc()


def run(interaction, api, context: Context | None = None, seconds: float = ANSWER_SECONDS) -> None:
    """ตอบหนึ่งคำสั่งแล้วแก้ข้อความ "กำลังคิด" ไม่ว่าจะพังตรงไหน ข้อความนั้นต้องไม่ค้างไว้เฉย ๆ"""
    try:
        reply = _answer_within(interaction, context or default_context(), api, seconds)
    except Exception:  # noqa: BLE001 คำสั่งเดียวพังต้องยังได้คำขอโทษ
        traceback.print_exc()
        reply = Reply(chat.FAILED)
    _deliver(interaction, api, reply)
