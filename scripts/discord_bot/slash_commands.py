"""ลงทะเบียนคำสั่ง / ของ ตามควาย กับ Discord และตั้ง URL ที่ Discord ส่งคำสั่งมา

ใช้ DISCORD_BOT_TOKEN ใน .env ตัวเดียวกับ make bot คำสั่งทั่วโลกอาจใช้เวลาสักพักกว่าจะขึ้นในทุก server

ใช้:
    make bot-commands                                              ลงทะเบียนคำสั่ง แล้วพิมพ์ Public Key
    make bot-commands ARGS="--endpoint https://tamkwai.com/api/discord"   ตั้ง URL ด้วย

ตั้ง URL ได้หลัง deploy แล้วเท่านั้น Discord ยิงทดสอบทันทีตอนตั้ง ต้องมี DISCORD_PUBLIC_KEY บน Vercel ก่อน
ตั้งแล้วบอท make bot เดิมยังรับข้อความในห้องได้ตามเดิม คำสั่ง / จะไปที่ URL นี้แทน
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "voice"))

import discord_api  # noqa: E402
import keys  # noqa: E402

STRING, ATTACHMENT = 3, 11
GUILD_INSTALL = 0
GUILD, BOT_DM = 0, 1
LANG = {"name": "lang", "description": "Language", "type": STRING,
        "description_localizations": {"th": "ภาษา"},
        "choices": [{"name": "ไทย", "value": "th"}, {"name": "English", "value": "en"}]}


def _command(name: str, description: str, thai: str, options: list | None = None) -> dict:
    return {"name": name, "type": 1, "description": description,
            "description_localizations": {"th": thai}, "options": options or [],
            "integration_types": [GUILD_INSTALL], "contexts": [GUILD, BOT_DM]}


COMMANDS = [
    _command("chart", "Preflop chart for a spot, e.g. BTN shove 10bb", "ถามชาร์ต preflop เช่น BTN shove 10bb", [
        {"name": "question", "description": "Position and stack, e.g. BB vs BTN shove 8bb", "type": STRING,
         "description_localizations": {"th": "ตำแหน่งกับสแตก เช่น BB เจอ BTN ออลอิน 8bb"},
         "required": True, "max_length": 500}]),
    _command("screenshot", "Read a table screenshot and chart it", "แนบรูปโต๊ะให้บอทอ่านแล้วตอบเป็นชาร์ต", [
        {"name": "image", "description": "Screenshot of the table", "type": ATTACHMENT,
         "description_localizations": {"th": "รูปหน้าจอโต๊ะ"}, "required": True},
        {"name": "note", "description": "Anything the picture misses, e.g. hold AJo", "type": STRING,
         "description_localizations": {"th": "สิ่งที่รูปไม่บอก เช่น ถือ AJo"}, "max_length": 500}]),
    _command("new", "Forget the last spot", "ลืม spot เดิม"),
    _command("ai", "Turn the AI on or off", "เปิดหรือปิดโหมด AI", [
        {"name": "mode", "description": "on or off", "type": STRING, "required": True,
         "description_localizations": {"th": "เปิดหรือปิด"},
         "choices": [{"name": "on", "value": "on"}, {"name": "off", "value": "off"}]}]),
    _command("help", "How to use the bot", "วิธีใช้", [LANG]),
    _command("privacy", "What the bot keeps", "บอทเก็บข้อมูลอะไรบ้าง", [LANG]),
    _command("contact", "Developer email", "อีเมลผู้พัฒนา"),
]


def register(api: discord_api.Api, token: str, endpoint: str | None = None) -> dict:
    """ลงทะเบียนคำสั่งทั้งหมดแทนของเดิม ตั้ง URL ถ้าให้มา คืนข้อมูลแอปล่าสุด"""
    app = api.bot("GET", "/applications/@me", token)
    api.bot("PUT", f"/applications/{app['id']}/commands", token, COMMANDS)
    if endpoint:
        app = api.bot("PATCH", "/applications/@me", token, {"interactions_endpoint_url": endpoint})
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", help="Interactions Endpoint URL เช่น https://tamkwai.com/api/discord")
    args = parser.parse_args(argv)
    token = keys.require("DISCORD_BOT_TOKEN")
    try:
        app = register(discord_api.Api(), token, args.endpoint)
    except discord_api.DiscordError as error:
        print(f"Discord ไม่รับ: {error}", file=sys.stderr)
        return 1
    print(f"ลงทะเบียน {len(COMMANDS)} คำสั่งให้ {app.get('name')} แล้ว")
    print(f"DISCORD_PUBLIC_KEY={app.get('verify_key')}")
    print(f"Interactions Endpoint URL: {app.get('interactions_endpoint_url') or '(ยังไม่ได้ตั้ง)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
