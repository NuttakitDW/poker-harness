"""บอท Discord ชื่อ ตามควาย สำหรับทดสอบว่าเครื่องนี้คุยกับ Discord ได้สองทาง

บอทเป็นฝ่ายต่อออกไปหา Discord เอง ไม่ต้องเปิด port ไม่ต้องมี server สาธารณะ
ข้อความที่คนพิมพ์ในห้องที่บอทเห็นจะขึ้นในเทอร์มินัลนี้
พิมพ์ในเทอร์มินัลแล้วกด Enter จะส่งไปห้องล่าสุดที่มีคนพิมพ์มา หรือห้อง DISCORD_CHANNEL_ID
ในห้อง Discord พิมพ์ ping บอทตอบ pong

ถามชาร์ต push/fold จาก Discord ได้ ตอบเป็นรูปชาร์ตแบบเดียวกับ make chart
    @TamKwai BTN shove 10bb     หรือ   !chart BTN shove 10bb
    ใน DM พิมพ์คำถามตรง ๆ ได้เลย
    ข้อความเสียง (กดไมค์ค้างในแอปมือถือ) ถอดเป็นข้อความด้วย Soniox แล้วตอบเป็นชาร์ต
    ทุกคำถามชาร์ตถูกบันทึกลง tmp/logs/discord-YYYYMMDD.jsonl ดูที่พลาดด้วย make bot-review
    ไฟล์เสียงที่แนบในห้องต้องมี @TamKwai หรือ !chart กำกับ ใน DM ไม่ต้อง
    !new       ลืมตำแหน่งกับสแตกที่จำไว้ (จำแยกตามคนและห้อง)
    !ai-off    โหมดพื้นฐาน อ่านคำถามเองไม่ผ่าน AI   !ai-on กลับโหมด AI (ค่าเริ่ม คุยภาษาคนได้)
    !help      วิธีใช้   !help en ภาษาอังกฤษ
    !privacy   เก็บข้อมูลอะไรบ้าง   !privacy en ภาษาอังกฤษ

ต้องมี DISCORD_BOT_TOKEN ใน .env (DISCORD_CHANNEL_ID ไม่ใส่ก็ได้)

ใช้:
    make bot

คำสั่งในเทอร์มินัล:
    /channels     ห้องที่บอทส่งข้อความได้ พร้อม id
    /to <id>      เปลี่ยนห้องที่จะส่ง
    /q, /quit     ออก
"""

from __future__ import annotations

import asyncio
import io
import pathlib
import re
import sys
import threading
import traceback

import discord

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "voice"))

import assistant  # noqa: E402
import chart_image  # noqa: E402
import mario  # noqa: E402
import question_log  # noqa: E402
import keys  # noqa: E402
import soniox_api  # noqa: E402
import spot_chart  # noqa: E402
import table_image  # noqa: E402

# ดูห้อง ส่งข้อความ ฝังลิงก์ แนบไฟล์ อ่านประวัติ พอสำหรับส่งชาร์ตเป็นรูปในขั้นต่อไป
PERMISSIONS = 1024 | 2048 | 16384 | 32768 | 65536
QUIT_COMMANDS = ("/q", "/quit")
PING, PONG = "ping", "pong"
CHART_PREFIX, NEW_COMMAND, HELP_PREFIX = "!chart", "!new", "!help"
CONTACT_COMMANDS = ("!contact", "/contact")
PRIVACY_COMMANDS = ("!privacy", "/privacy")
DISCORD_HELP = {
    "th": """ตามควาย · วิธีใช้ใน Discord
ถามตำแหน่งกับสแตก ได้รูปชาร์ต push/fold ที่ solver แก้สด

Commands
  @TamKwai <คำถาม>    ถามในห้อง
  !chart <คำถาม>       ถามในห้องโดยไม่ต้อง mention
  DM                  ส่งคำถามมาตรง ๆ ได้เลย ไม่ต้องมีคำนำหน้า
  ข้อความเสียง          กดไมค์ค้างในแอปมือถือแล้วพูดคำถาม
  รูปหน้าจอ            แนบรูปโต๊ะ บอทอ่านตำแหน่ง สแตก ไพ่ให้
  !new                ลืม spot เดิม (จำแยกตามคนและห้อง)
  !ai-off / !ai-on    ปิด/เปิด AI (เปิดอยู่: คุยภาษาคนได้)
  !help [th|en]       วิธีใช้นี้
  !contact · ping     อีเมลผู้พัฒนา · บอทออนไลน์ไหม
  !privacy            บอทเก็บข้อมูลอะไรบ้าง

ตัวอย่างข้างล่าง ใส่หลัง @TamKwai หรือ !chart""",
    "en": """ตามควาย · How to use in Discord
Name a seat and a stack, get a solved push/fold chart

Commands
  @TamKwai <question>  ask in a channel
  !chart <question>    ask in a channel without a mention
  DM                   ask with no prefix
  voice message        hold the mic in the app and ask
  screenshot           attach a picture of the table
  !new                 forget the spot
  !ai-off / !ai-on     AI off/on (on: just talk)
  !help [th|en]        this help
  !contact · ping      developer email · is the bot up
  !privacy             what the bot keeps

Examples go after @TamKwai or !chart""",
}
PRIVACY = {
    "th": f"""ตามควาย · ความเป็นส่วนตัว
เก็บอะไร: ข้อความที่ถามบอท กับคำถามชาร์ตที่ AI เขียนให้ (ถ้าเป็นเสียงคือข้อความที่ถอดได้ ถ้าเป็นรูปคือคำถามที่อ่านได้) เวลา ชื่อ server กับห้อง และ spot ที่อ่านได้
ไม่เก็บ: ชื่อหรือไอดีของคนถาม ข้อความอื่นในห้อง ไฟล์เสียง และรูป
spot ล่าสุดจำไว้ในหน่วยความจำเท่านั้น หายเมื่อพิมพ์ !new หรือบอทรีสตาร์ท

เพื่ออะไร: ตอบคำถาม และหาคำถามที่บอทยังอ่านไม่ออกเพื่อปรับปรุง (ประโยชน์โดยชอบด้วยกฎหมาย ตาม PDPA มาตรา 24(5))
เก็บนานเท่าไร: {question_log.KEEP_DAYS} วัน แล้วลบอัตโนมัติ

ส่งต่อให้ใคร:
  Discord  ข้อความทั้งหมดผ่าน Discord อยู่แล้ว
  Soniox   ไฟล์เสียงส่งไปถอดเป็นข้อความ แล้วบอทสั่งลบไฟล์กับผลถอดที่ Soniox ทันที
  DeepSeek คำถาม (โหมด AI ปิดได้ด้วย !ai-off) และรูปหน้าจอ ส่งไปอ่าน เซิร์ฟเวอร์อยู่ในจีน บอทไม่เก็บรูป
  Railway  เครื่องที่บอทรัน อยู่นอกประเทศไทย
ไม่ขาย ไม่ใช้โฆษณา

สิทธิ์ของคุณ: ขอดู ขอลบ หรือคัดค้านการเก็บ ส่งอีเมลมาที่ {spot_chart.CONTACT}
ถ้าไม่ต้องการให้เก็บ อย่าถามบอท ข้อความทั่วไปในห้องบอทไม่ได้บันทึก""",
    "en": f"""ตามควาย · Privacy
What we keep: the text of questions to the bot and the chart query the AI wrote (for voice, the transcript; for a screenshot, the question read from it), the time, the server and channel name, and the spot the bot read
What we don't keep: your name or user ID, other messages in the channel, audio files or images
Your last spot is held in memory only, and is gone after !new or a restart

Why: to answer you, and to find questions the bot could not read so it can improve (legitimate interest, Thai PDPA s.24(5))
How long: {question_log.KEEP_DAYS} days, then deleted automatically

Who else sees it:
  Discord  every message already passes through Discord
  Soniox   voice messages are sent for transcription; the bot deletes the file and transcript there right after
  DeepSeek questions (AI mode, turn off with !ai-off) and screenshots are sent to be read, on servers in China; the bot keeps no images
  Railway  hosts the bot, outside Thailand
Never sold, never used for ads

Your rights: ask to see, delete, or object, by email to {spot_chart.CONTACT}
If you don't want anything kept, don't ask the bot; ordinary chat is not recorded""",
}
WARM_UP_QUESTIONS = ("BTN shove 10bb", "aof CO", "aof 3 handed BTN", "aof heads-up SB")
FAILED = "ขอโทษ ทำชาร์ตไม่สำเร็จ ลองถามใหม่อีกทีนะ"
NOT_HEARD = "ถอดเสียงไม่ออก ลองพูดใหม่ชัด ๆ หรือพิมพ์มาแทนนะ"
NOT_READ = "อ่านรูปนี้เป็นโต๊ะไม่ออก ลองแคปจอให้เห็นทั้งโต๊ะ หรือพิมพ์มาแทนนะ"
NO_VISION = "ตอนนี้ยังอ่านรูปไม่ได้ พิมพ์คำถามมาแทนนะ"
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_IMAGE_BYTES = 10_000_000
AUDIO_EXTENSIONS = (".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".webm", ".aac", ".flac")
FORGOT = "ลืม spot เดิมแล้ว ถามใหม่ได้เลย"
NO_TARGET = "ยังไม่รู้จะส่งไปห้องไหน พิมพ์อะไรก็ได้ใน Discord ก่อน หรือ /channels แล้ว /to <id>"


def invite_url(app_id: int) -> str:
    """ลิงก์เชิญบอทเข้า server พร้อมสิทธิ์ที่ต้องใช้"""
    return (f"https://discord.com/oauth2/authorize?client_id={app_id}"
            f"&scope=bot&permissions={PERMISSIONS}")


def incoming(guild: str | None, channel: str | None, author: str, content: str) -> str:
    """บรรทัดที่พิมพ์ในเทอร์มินัลเมื่อมีข้อความเข้ามา"""
    where = f"{guild} #{channel}" if guild else "DM"
    return f"[{where}] {author}: {content}"


def chart_question(content: str, bot_id: int, direct: bool) -> str | None:
    """คำถามชาร์ตในข้อความ ต้อง mention บอท ขึ้นต้นด้วย !chart หรือเป็น DM ไม่งั้นไม่ใช่คำถาม"""
    text = content.strip()
    mention = re.compile(rf"<@!?{bot_id}>")
    if mention.search(text):
        question = mention.sub(" ", text)
    elif text.lower().startswith(CHART_PREFIX):
        question = text[len(CHART_PREFIX):]
    elif direct:
        question = text
    else:
        return None
    return question.strip() or None


def audio_attachment(attachments) -> object | None:
    """ไฟล์เสียงไฟล์แรกในข้อความ ดูจากชนิดไฟล์ก่อน ถ้าไม่บอกชนิดดูจากนามสกุล"""
    return next((item for item in attachments
                 if (item.content_type or "").startswith("audio/")
                 or item.filename.lower().endswith(AUDIO_EXTENSIONS)), None)


def answers_audio(voice: bool, direct: bool, text: str, bot_id: int) -> bool:
    """ตอบเสียงนี้ไหม ข้อความเสียงของ Discord กับเสียงใน DM ตอบเสมอ ไฟล์เสียงในห้องต้องเรียกบอท"""
    if voice or direct:
        return True
    return bool(re.search(rf"<@!?{bot_id}>", text)) or text.lower().startswith(CHART_PREFIX)


def image_attachment(attachments) -> object | None:
    """รูปแรกในข้อความ ดูจากชนิดไฟล์ก่อน ถ้าไม่บอกชนิดดูจากนามสกุล รูปใหญ่เกินไม่อ่าน"""
    return next((item for item in attachments
                 if ((item.content_type or "").startswith("image/")
                     or item.filename.lower().endswith(IMAGE_EXTENSIONS))
                 and item.size <= MAX_IMAGE_BYTES), None)


def read_line(question: str) -> str:
    """บอกผู้ถามว่าอ่านรูปได้ว่าอะไร อ่านผิดจะได้พิมพ์แก้ต่อได้"""
    return f"อ่านจากรูปได้ว่า: {question}"


def heard_line(text: str) -> str:
    return f"ได้ยินว่า: {text}"


def help_message(text: str) -> str | None:
    """วิธีใช้ใน Discord ถ้าข้อความเป็น !help, !help th หรือ !help en"""
    words = text.strip().lower().split()
    if not words or words[0] != HELP_PREFIX or words[1:] not in ([], ["th"], ["en"]):
        return None
    lang = words[1] if len(words) == 2 else "th"
    # ตัวอย่างกับข้อจำกัดมาจาก make chart ส่วนคำสั่งเป็นของ Discord ใส่ code block ให้คอลัมน์ตรง
    return (f"```\n{DISCORD_HELP[lang]}\n\n{spot_chart.HELP_GUIDE[lang]}\n\n"
            f"{spot_chart.COPYRIGHT}\n```")


def privacy_message(text: str) -> str | None:
    """ประกาศความเป็นส่วนตัว ถ้าข้อความเป็น !privacy หรือ /privacy ตามด้วย th หรือ en ได้"""
    words = text.strip().lower().split()
    if not words or words[0] not in PRIVACY_COMMANDS or words[1:] not in ([], ["th"], ["en"]):
        return None
    return f"```\n{PRIVACY[words[1] if len(words) == 2 else 'th']}\n```"


def log_place(message) -> dict:
    """ที่มาของคำถามสำหรับบันทึก ตั้งใจไม่เก็บว่าใครถาม"""
    return {"server": message.guild.name if message.guild else None,
            "channel": getattr(message.channel, "name", None)}


def terminal_command(line: str) -> tuple[str, str]:
    """แปลบรรทัดที่พิมพ์ในเทอร์มินัลเป็น (คำสั่ง, ค่า)"""
    text = line.strip()
    if not text:
        return "skip", ""
    if text.lower() in QUIT_COMMANDS:
        return "quit", ""
    if text == "/channels":
        return "channels", ""
    if text.startswith("/to "):
        return "to", text[4:].strip()
    return "send", text


class Bridge(discord.Client):
    """ส่งต่อข้อความระหว่างห้อง Discord กับเทอร์มินัลของเครื่องนี้"""

    def __init__(self, channel_id: int | None) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # ต้องเปิด Message Content Intent ใน Developer Portal ด้วย
        super().__init__(intents=intents)
        self.target = channel_id
        self._reading = False
        self.terminal = has_terminal(sys.stdin)
        self.memory: dict[tuple[int, int], object] = {}  # (ห้อง, คน) -> สิ่งที่บอกไว้ตาก่อน
        self.ai_off: set[tuple[int, int]] = set()          # คนที่ปิดโหมด AI ไว้ ไม่อยู่ในนี้คือเปิด
        self.history: dict[tuple[int, int], tuple] = {}     # ประวัติคุยกับ AI

    async def on_ready(self) -> None:
        print(f"ตามควาย ออนไลน์แล้ว ({self.user}) อยู่ใน {len(self.guilds)} server", flush=True)
        print(f"ลิงก์เชิญบอท: {invite_url(self.application_id)}", flush=True)
        # ต่อใหม่หลังเน็ตหลุดก็เรียก on_ready อีก เปิดตัวอ่านเทอร์มินัลครั้งเดียวพอ
        # บนคลาวด์ไม่มีเทอร์มินัล stdin ว่างทันที ถ้าอ่านจะปิดบอทตั้งแต่เริ่ม
        if not self._reading and self.terminal:
            self._reading = True
            threading.Thread(target=self._read_terminal, daemon=True).start()

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return
        guild = message.guild.name if message.guild else None
        channel = getattr(message.channel, "name", None)
        # บนเซิร์ฟเวอร์ไม่มีใครอ่าน และ log ของ Railway จะเก็บข้อความทุกคนไว้ จึงพิมพ์เฉพาะตอนมีเทอร์มินัล
        if self.terminal:
            print(incoming(guild, channel, message.author.display_name, message.content), flush=True)
        self.target = message.channel.id
        text = message.content.strip()
        key = (message.channel.id, message.author.id)
        if text.lower() == PING:
            await message.channel.send(PONG)
        elif text.lower() == NEW_COMMAND:
            self.memory.pop(key, None)
            self.history.pop(key, None)
            await message.reply(FORGOT)
        elif assistant.toggle(text) is not None:
            await message.reply(self._toggle_ai(key, assistant.toggle(text)))
        elif text.lower() in CONTACT_COMMANDS:
            await message.reply(f"{spot_chart.CONTACT}\n{spot_chart.COPYRIGHT}")
        elif help_message(text):
            await message.reply(help_message(text))
        elif privacy_message(text):
            await message.reply(privacy_message(text))
        else:
            audio = audio_attachment(message.attachments)
            direct = message.guild is None
            if audio and answers_audio(message.flags.voice, direct, text, self.user.id):
                await self._voice(message, audio, key)
                return
            image = image_attachment(message.attachments)
            if image and answers_audio(False, direct, text, self.user.id):
                await self._image(message, image, key, chart_question(text, self.user.id, True))
                return
            question = chart_question(text, self.user.id, direct)
            if question:
                await self._chart(message, question, key)

    def _toggle_ai(self, key: tuple[int, int], on: bool) -> str:
        if on:
            self.ai_off.discard(key)
        else:
            self.ai_off.add(key)
            self.history.pop(key, None)
        return assistant.TURNED[on]

    async def _voice(self, message: discord.Message, audio, key: tuple[int, int]) -> None:
        """ถอดข้อความเสียงด้วย Soniox แล้วถามชาร์ตเหมือนพิมพ์มา"""
        try:
            async with message.channel.typing():
                data = await audio.read()
                result = await asyncio.to_thread(soniox_api.transcribe_bytes, data,
                                                 soniox_api.load_api_key(), audio.filename,
                                                 "spot")
        except Exception:  # noqa: BLE001 ถอดเสียงพังก็ต้องตอบ ไม่ใช่เงียบหาย
            traceback.print_exc()
            self._log(message, "", "voice", "not_heard", audio=audio.filename)
            await message.reply(NOT_HEARD)
            return
        print(f"  ถอดเสียงได้: {result.text!r} ({result.seconds:.1f}s)", flush=True)
        if not result.text:
            self._log(message, "", "voice", "not_heard", audio=audio.filename)
            await message.reply(NOT_HEARD)
            return
        await self._chart(message, result.text, key, heard=heard_line(result.text),
                          audio=audio.filename)

    async def _image(self, message: discord.Message, image, key: tuple[int, int],
                     extra: str | None) -> None:
        """อ่านรูปโต๊ะด้วย DeepSeek เป็นคำถาม แล้วถามชาร์ตเหมือนพิมพ์มา ข้อความที่แนบมาต่อท้ายคำถาม"""
        api_key = keys.find(*table_image.KEY_NAMES)
        if not api_key:
            await message.reply(NO_VISION)
            return
        try:
            async with message.channel.typing():
                data = await image.read()
                table = await asyncio.to_thread(table_image.read, data,
                                                image.content_type or "image/png", api_key)
        except Exception:  # noqa: BLE001 อ่านรูปพังก็ต้องตอบ ไม่ใช่เงียบหาย
            traceback.print_exc()
            self._log(message, "", "image", "not_read", image=image.filename)
            await message.reply(NOT_READ)
            return
        question = " ".join(filter(None, (table_image.question(table), extra)))
        print(f"  อ่านรูปได้: {question!r}", flush=True)
        # รูปคือ spot ใหม่ทั้งโต๊ะ ไม่ยืมตำแหน่งหรือคนที่ all-in จากคำถามก่อน
        self.memory.pop(key, None)
        await self._chart(message, question, key, heard=read_line(question),
                          image=image.filename, ai=False)

    def _log(self, message: discord.Message, question: str, source: str, kind: str,
             request=None, **fields) -> None:
        """จดคำถามลงบันทึก พังก็แค่เตือน ไม่ให้การจดทำให้ตอบไม่ได้"""
        try:
            question_log.record(question_log.entry(
                question=question, source=source, kind=kind, request=request,
                **log_place(message), **fields))
        except OSError as error:
            print(f"จดบันทึกคำถามไม่ได้: {error}", flush=True)

    async def _ask(self, question: str, key: tuple[int, int], ai: bool) -> tuple[object, list[str], dict]:
        """(ผลจาก solver หรือ None, บรรทัดข้อความของ AI, ช่องเพิ่มในบันทึก)

        โหมด AI ให้ DeepSeek เขียนคำถามก่อน ปิด AI หรือรูปหน้าจอส่งเข้า solver ตรง ๆ
        """
        memory = self.memory.get(key)
        if not ai or key in self.ai_off:
            return await asyncio.to_thread(spot_chart.reply, question, memory=memory), [], {}
        result = await asyncio.to_thread(assistant.answer, question, spot_chart.reply,
                                         self.history.get(key, ()), memory)
        self.history[key] = result.history
        lines = [result.say]
        if result.query and result.query != question:
            lines.append(assistant.QUERY_LINE.format(query=result.query))
        return result.made, lines, {"ai_query": result.query}

    async def _chart(self, message: discord.Message, question: str, key: tuple[int, int],
                     heard: str | None = None, audio: str | None = None,
                     image: str | None = None, ai: bool = True) -> None:
        """แก้ชาร์ตในเธรดแยก gateway จะได้ไม่ค้างระหว่าง solver คิด แล้วตอบเป็นรูป

        heard คือบรรทัดบอกว่าถอดเสียงได้ว่าอะไร ให้ผู้ถามเห็นถ้าบอทได้ยินผิด
        """
        source = "voice" if audio else "image" if image else "text"
        extra = {"audio": audio} if audio else {"image": image} if image else {}
        try:
            async with message.channel.typing():
                made, said, logged = await self._ask(question, key, ai)
                heard = "\n".join(filter(None, (heard, *said))) or None
                if made is None:
                    self._log(message, question, source, "talk", **extra, **logged)
                    await message.reply(heard)
                    return
                self._log(message, question, source, made.kind,
                          made.found.request if made.found else None, **extra, **logged)
                if made.found is not None:
                    self.memory[key] = made.found.request
                if made.kind == "mario":
                    png = await asyncio.to_thread(mario.png)
                    await message.reply(heard,
                                        file=discord.File(io.BytesIO(png), filename="mario.png"))
                    return
                if made.message is not None:
                    await message.reply("\n".join(filter(None, (heard, made.message))))
                    return
                found = made.found
                png = await asyncio.to_thread(chart_image.render, found.book, found.chart,
                                              found.hands, found.lang, (made.note,))
                await message.reply(heard,
                                    file=discord.File(io.BytesIO(png), filename="chart.png"))
        except Exception as error:  # noqa: BLE001 บอทต้องไม่ตายเพราะคำถามเดียว เก็บรายละเอียดไว้ในเทอร์มินัล
            traceback.print_exc()
            self._log(message, question, source, "error", error=repr(error), **extra)
            await message.reply(FAILED)

    def _read_terminal(self) -> None:
        for line in sys.stdin:
            kind, value = terminal_command(line)
            asyncio.run_coroutine_threadsafe(self._handle(kind, value), self.loop)
            if kind == "quit":
                return
        asyncio.run_coroutine_threadsafe(self.close(), self.loop)

    async def _handle(self, kind: str, value: str) -> None:
        if kind == "quit":
            await self.close()
        elif kind == "channels":
            self._list_channels()
        elif kind == "to":
            self._switch(value)
        elif kind == "send":
            await self._send(value)

    def _list_channels(self) -> None:
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    print(f"  {channel.id}  {guild.name} #{channel.name}", flush=True)

    def _switch(self, value: str) -> None:
        channel = self.get_channel(int(value)) if value.isdigit() else None
        if channel is None:
            print(f"ไม่เจอห้อง {value} ดู id ได้จาก /channels", flush=True)
            return
        self.target = channel.id
        print(f"ส่งไป #{getattr(channel, 'name', channel.id)} แล้วนะ", flush=True)

    async def _send(self, text: str) -> None:
        if self.target is None:
            print(NO_TARGET, flush=True)
            return
        try:
            channel = self.get_channel(self.target) or await self.fetch_channel(self.target)
            await channel.send(text)
        except discord.Forbidden:
            print("บอทไม่มีสิทธิ์ส่งข้อความในห้องนี้", flush=True)
        except discord.HTTPException as error:
            print(f"ส่งไม่สำเร็จ: {error}", flush=True)


def has_terminal(stream) -> bool:
    """มีคนนั่งพิมพ์อยู่หน้าเทอร์มินัลหรือไม่ (บน Railway หรือ systemd จะไม่มี)"""
    return stream is not None and stream.isatty()


def warm_up() -> None:
    """โหลดตารางและแก้ชาร์ตหนึ่งครั้งก่อนต่อ Discord คนแรกจะได้ไม่รอ และเห็นความเร็วเครื่องใน log"""
    import os
    import time
    started = time.perf_counter()
    for question in WARM_UP_QUESTIONS:
        spot_chart.reply(question)
    print(f"อุ่นเครื่อง: แก้ {len(WARM_UP_QUESTIONS)} โต๊ะใน {time.perf_counter() - started:.2f}s "
          f"(cpu {os.cpu_count()}, ใช้ได้ {len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else '?'}, "
          f"OPENBLAS_NUM_THREADS={os.environ.get('OPENBLAS_NUM_THREADS', '-')})", flush=True)


def main() -> int:
    token = keys.require("DISCORD_BOT_TOKEN")
    warm_up()
    channel_id = keys.find("DISCORD_CHANNEL_ID")
    bridge = Bridge(int(channel_id) if channel_id and channel_id.isdigit() else None)
    try:
        bridge.run(token)
    except discord.LoginFailure:
        print("token ไม่ถูกต้อง ไป Reset Token ใน Developer Portal แล้วใส่ DISCORD_BOT_TOKEN ใหม่",
              file=sys.stderr)
        return 1
    except discord.PrivilegedIntentsRequired:
        print("ยังไม่ได้เปิด Message Content Intent: Developer Portal > Bot > Privileged Gateway Intents",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
