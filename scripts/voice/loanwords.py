"""คำทับศัพท์ที่เขียนด้วยอักษรไทย กับรูปอังกฤษที่ควรส่งให้เครื่องอ่านออกเสียงแทน

ตัวอ่านออกเสียงอ่านคำทับศัพท์ที่สะกดด้วยอักษรไทยเพี้ยน เช่น "ทัวร์นาเมนต์"
ออกมาเป็นคำที่ฟังไม่ออก แต่ถ้าเขียน tournament ตรง ๆ มันอ่านถูก
SOUL.md สั่งให้ผู้ช่วยเขียนรูปอังกฤษอยู่แล้ว ที่นี่คือตาข่ายรับกรณีที่ยังหลุดมา

รายการนี้เก็บเฉพาะคำที่คนโป๊กเกอร์พูดทับศัพท์จริง ไม่ใช่คำไทยที่แปลได้อยู่แล้ว
"""

from __future__ import annotations

import re

SPOKEN_IN_ENGLISH = {
    # ชื่อเกมและรูปแบบการเล่น
    "โป๊กเกอร์": "Poker",
    "โปกเกอร์": "Poker",
    "โพกเกอร์": "Poker",
    "ทัวร์นาเมนต์": "tournament",
    "ทัวร์นาเม้นท์": "tournament",
    "ทัวร์นาเมนท์": "tournament",
    "แคชเกม": "cash game",
    "ซิทแอนด์โก": "sit and go",
    "โฮลเด็ม": "hold'em",
    "โอมาฮา": "Omaha",
    # ช่วงของมือ
    "พรีฟลอป": "preflop",
    "ฟลอป": "flop",
    "เทิร์น": "turn",
    "ริเวอร์": "river",
    "โชว์ดาวน์": "showdown",
    # การกระทำที่โต๊ะ
    "เช็คเรส": "check-raise",
    "เช็กเรส": "check-raise",
    "ออลอิน": "all-in",
    "บลัฟ": "bluff",
    "คอนติเนชั่นเบต": "continuation bet",
    "ซีเบต": "c-bet",
    "คอล": "call",
    "เรส": "raise",
    "เบต": "bet",
    "โฟลด์": "fold",
    "โฟล์ด": "fold",
    # "เช็ค" ในบทสนทนานี้หมายถึงการเช็คที่โต๊ะเสมอ ไม่ใช่การตรวจสอบ
    "เช็ค": "check",
    "เช็ก": "check",
    "ทรีเบต": "three-bet",
    "โฟร์เบต": "four-bet",
    "ลิมพ์": "limp",
    # ตำแหน่งบนโต๊ะ
    "คัตออฟ": "cutoff",
    "ไฮแจ็ค": "hijack",
    "บัตตัน": "button",
    "บิ๊กบลายด์": "big blind",
    "สมอลบลายด์": "small blind",
    # ศัพท์เชิงกลยุทธ์
    "เรนจ์": "range",
    "อิควิตี้": "equity",
    "เอควิตี้": "equity",
    "พอตออดส์": "pot odds",
    "พอต": "pot",
    "พ็อต": "pot",
    "ออดส์": "odds",
    "ดรอว์": "draw",
    "บอร์ด": "board",
    "แวลู": "value",
    "สแตก": "stack",
    "สเตก": "stakes",
    "สเต็ก": "stakes",
    "สเตค": "stakes",
    "แบงค์โรล": "bankroll",
    "แบงก์โรล": "bankroll",
    "บับเบิล": "bubble",
    "บับเบิ้ล": "bubble",
    "ทิลต์": "tilt",
    "แบดบีท": "bad beat",
    "วาเรียนซ์": "variance",
    "บลายด์": "blind",
    "แอนที": "ante",
    # เงิน paxa อ่าน "ดอลลาร์" เพี้ยนเป็น "ดอลลาห์"
    "ดอลลาร์": "dollar",
    "ดอลล่าร์": "dollar",
}

# คำยาวต้องถูกแทนก่อน ไม่งั้นคำสั้นที่ซ้อนอยู่ข้างในจะกินไปก่อนแล้วเหลือเศษ
_PATTERN = re.compile("|".join(
    re.escape(word) for word in sorted(SPOKEN_IN_ENGLISH, key=len, reverse=True)))

_THAI = re.compile(r"[ก-๙]")
_SPACES = re.compile(r"[ \t]{2,}")


def prefer_english(text: str) -> str:
    """แทนคำทับศัพท์ด้วยรูปอังกฤษ พร้อมเว้นวรรคกันคำติดกับอักษรไทยข้างเคียง"""
    def replace(match: re.Match) -> str:
        return f" {SPOKEN_IN_ENGLISH[match.group(0)]} "

    return _SPACES.sub(" ", _PATTERN.sub(replace, text))
