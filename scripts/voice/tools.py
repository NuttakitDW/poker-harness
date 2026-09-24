"""เครื่องมือที่ลูกชุบเรียกใช้เองระหว่างตอบ ผ่าน function calling ของโมเดล

ตัวเลขที่ต้องแม่น เช่น equity ห้ามให้โมเดลเดา ให้โมเดลแปลงสิ่งที่ได้ยินเป็นข้อมูลเข้า
แล้วโค้ดคำนวณจริงส่งผลกลับไปให้พูด ทุกครั้งที่เรียกจะพิมพ์บอกบนจอแชต
"""

from __future__ import annotations

import json
import sys
import threading

import equity
import journal

EQUITY_TOOL = "poker_equity"

SCHEMAS = [{
    "type": "function",
    "function": {
        "name": EQUITY_TOOL,
        "description": (
            "คำนวณ equity ของ No-Limit Hold'em แบบไล่ทุกบอร์ดที่เป็นไปได้ด้วย pokerkit "
            "ใช้ได้ทั้ง hand vs hand, hand vs range, range vs range และหลายทาง (2-6 คน) "
            "ต้องเรียกทุกครั้งที่ผู้ใช้ถาม equity เปอร์เซ็นต์ชนะ หรือใครเป็นต่อเท่าไหร่ ห้ามเดาตัวเลขเอง "
            "ผลที่ได้มี equity_pct win_pct tie_pct ของแต่ละคน และ exact บอกว่าเป็นค่าแน่นอนหรือประมาณ"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "players": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": equity.MAX_PLAYERS,
                    "items": {"type": "string"},
                    "description": (
                        "มือหรือ range ของผู้เล่นแต่ละคน เรียงตามที่ผู้ใช้พูด หนึ่งช่องต่อหนึ่งคน "
                        "แต้ม: A K Q J T 9-2 (สิบใช้ T) ดอก: s=โพดำ h=โพแดง d=ข้าวหลามตัด c=ดอกจิก "
                        "มือเจาะจงเขียนแต้มตามด้วยดอก เช่น 'KsKc', 'AhKh' "
                        "ถ้าผู้ใช้ไม่บอกดอก ให้ใช้ range แทน เช่น 'KK', 'AKs' (suited), 'AKo' (offsuit), 'AK' (ทั้งสองแบบ) "
                        "range รวมหลายส่วนด้วยจุลภาค: 'QQ+' (QQ ขึ้นไป), 'ATs+' (ATs ถึง AKs), "
                        "'JJ-99', 'A7s-A2s' (A7s ลงไปถึง A2s), 'QQ+,AK' และ 'any' แทนไพ่สองใบใดก็ได้ "
                        "ห้ามเขียนเป็นเปอร์เซ็นต์อย่าง 'top 10%'"
                    ),
                },
                "board": {
                    "type": "string",
                    "description": "ไพ่กลางที่เปิดแล้ว 0, 3, 4 หรือ 5 ใบ เช่น 'Th9h2c' ถ้ายังเป็น preflop ให้เว้นว่าง",
                },
            },
            "required": ["players"],
        },
    },
}]

RULES = f"""# เครื่องมือ

ถ้าผู้ใช้ถาม equity หรือเปอร์เซ็นต์ชนะระหว่างมือหรือ range ให้เรียก {EQUITY_TOOL} ทันที
ก่อนเขียนข้อความใด ๆ ห้ามประมาณตัวเลขเองจากความจำ แล้วพูดตัวเลขตามผลที่ได้
ปัดเป็นทศนิยมหนึ่งตำแหน่งตอนพูดได้ ถ้าผล exact เป็น false ให้บอกว่าเป็นค่าประมาณ
ตอนพูดชื่อมือห้ามใช้สัญลักษณ์ดอกอย่าง ♠ ให้พูดแต้มกับชื่อดอกภาษาไทยแทน
ถ้าผลมี made_hand_now ให้ยึดตามนั้นเวลาพูดว่าใครทำอะไรได้แล้วบนบอร์ด
ถ้าเครื่องมือตอบว่าข้อมูลผิดรูป ให้ถามผู้ใช้ให้ชัด อย่าเดามือเอง"""


def _log(text: str) -> None:
    """ขึ้นบนจอแชตทันที แยกจากคำตอบด้วยวงเล็บเหลี่ยมแบบเดียวกับข้อความระบบอื่น"""
    print(f"[tool] {text}", file=sys.stderr, flush=True)


def _describe_call(arguments: dict) -> str:
    players = " vs ".join(str(player) for player in arguments.get("players", []))
    board = arguments.get("board") or "preflop"
    return f"{players} | board: {board}"


def _describe_result(result: dict) -> str:
    hands = " | ".join(f"{p['hand']} {p['equity_pct']:.2f}%" for p in result["players"])
    method = "exact" if result["exact"] else f"approx ±{result['margin_pct']:.2f}%"
    return (f"{hands}  ({method}, {result['matchups']:,} matchup, "
            f"{result['runouts_per_matchup']:,} runouts, {result['seconds']:.2f}s)")


def _equity(arguments: dict) -> dict:
    players = arguments.get("players")
    if not isinstance(players, list) or not all(isinstance(p, str) for p in players):
        raise equity.EquityError("players ต้องเป็นรายการของข้อความ เช่น ['KsKc', 'AcAh']")
    board = arguments.get("board") or ""
    if not isinstance(board, str):
        raise equity.EquityError("board ต้องเป็นข้อความ เช่น 'Th9h2c'")
    return equity.calculate(players, board).as_dict()


HANDLERS = {EQUITY_TOOL: (_equity, _describe_call, _describe_result)}


def _fail(name: str, reason: str) -> str:
    _log(f"{name} ข้อมูลเข้าไม่ถูก: {reason}")
    journal.note("tool-error", name=name, error=reason)
    return json.dumps({"error": reason}, ensure_ascii=False)


def run(name: str, raw_arguments: str) -> str:
    """เรียกเครื่องมือตามชื่อ คืนผลเป็น JSON ให้โมเดลอ่าน ข้อผิดพลาดก็คืนเป็น JSON เช่นกัน"""
    if name not in HANDLERS:
        return _fail(name, f"ไม่มีเครื่องมือชื่อ {name}")
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as error:
        return _fail(name, f"อ่าน arguments ไม่ออก: {error}")
    if not isinstance(arguments, dict):
        return _fail(name, "arguments ต้องเป็น object")

    handler, describe_call, describe_result = HANDLERS[name]
    _log(f"ลูกชุบกำลังเรียก {name}: {describe_call(arguments)}")
    journal.note("tool-call", name=name, arguments=arguments)
    try:
        result = handler(arguments)
    except equity.EquityError as error:
        return _fail(name, str(error))
    except Exception as error:  # noqa: BLE001 ผลต้องกลับถึงโมเดลเสมอ ไม่ให้คำตอบค้าง
        _log(f"{name} พัง: {type(error).__name__}: {error}")
        journal.note("tool-error", name=name, error=f"{type(error).__name__}: {error}")
        return json.dumps({"error": "คำนวณไม่สำเร็จ บอกผู้ใช้ตรง ๆ ว่าเครื่องมือขัดข้อง"},
                          ensure_ascii=False)
    _log(f"{name} ได้ผล: {describe_result(result)}")
    journal.note("tool-result", name=name, result=result)
    return json.dumps(result, ensure_ascii=False)


def warm_up() -> None:
    """โหลดตารางและบอร์ดทั้งหมดไว้ก่อนในเบื้องหลัง คำถาม equity แรกจะได้ไม่ช้า"""
    def load() -> None:
        try:
            equity.warm()
        except Exception as error:  # noqa: BLE001 อุ่นไม่ติดก็แค่ช้าครั้งแรก
            _log(f"อุ่นเครื่อง equity ไม่สำเร็จ: {error}")
    threading.Thread(target=load, name="equity-warm-up", daemon=True).start()
