"""โหมด AI ของ spot chart: คุยกับผู้ใช้แบบผู้ช่วย แล้วให้ DeepSeek เขียนคำถามชาร์ตแทน

ผู้ใช้พูดภาษาคนได้เลย เช่น "เหลือ 6 คนจะเข้าเงินแล้ว ผมอยู่ BB มี 10bb SB ยัดมา ควร call ไหม"
โมเดลตอบเป็น JSON สองช่อง: say คือข้อความคุยกับผู้ใช้ query คือคำถามแบบที่ตัวอ่าน preflop อ่านออก
query ว่างแปลว่ายังไม่ต้องทำชาร์ต เช่นถามกลับว่าสแตกเท่าไร หรือเรื่องที่ชาร์ตตอบไม่ได้
ส่วนการแก้ชาร์ตยังเป็น spot_chart.reply เหมือนโหมดพื้นฐาน (ส่งเข้ามาเป็น solve) โมเดลไม่ได้คิดคำตอบโป๊กเกอร์เอง

เรียกโมเดลไม่สำเร็จหรือไม่มีคีย์ ถอยไปโหมดพื้นฐานกับข้อความเดิม แล้วบอกผู้ใช้ว่าถอย
/ai-off ปิดโหมดนี้ /ai-on เปิด ค่าเริ่มคือเปิด
"""

from __future__ import annotations

import dataclasses
import json
import time
import urllib.error
import urllib.request

import costs
import keys

URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
KEY_NAMES = ("DEEPSEEK_API_KEY", "DEEPSEEK_API")
TIMEOUT_SECONDS = 20
MAX_TOKENS = 400
MAX_HISTORY_TURNS = 6
ON_COMMANDS = ("/ai-on", "!ai-on")
OFF_COMMANDS = ("/ai-off", "!ai-off")
TURNED = {
    True: "เปิดโหมด AI แล้ว คุยได้ตามสบาย เดี๋ยวแปลงเป็นคำถามชาร์ตให้ (/ai-off กลับโหมดพื้นฐาน)",
    False: "ปิดโหมด AI แล้ว พิมพ์คำถามแบบสั้นตรง ๆ เช่น BB vs BTN shove 10bb (/ai-on เปิดกลับ)",
}
FELL_BACK = "AI ไม่ตอบตอนนี้ ใช้โหมดพื้นฐานอ่านข้อความเดิมแทน"
QUERY_LINE = "query: {query}"

SYSTEM = """You are TamKwai (ตามควาย), a friendly poker assistant in a chat that draws
push/fold charts. The chart solver is separate; your job is to understand the player and
write ONE query for it. Never invent chart results or percentages yourself.

Reply with ONLY a JSON object: {"say": str, "query": str | null}
- say: a short, warm reply in the user's language (Thai or English), one or two sentences.
  When you write a query, say what you are looking up. When something vital is missing,
  ask for it. Never paste the query into say.
- query: the solver query, or null when no chart should be drawn yet.

What the solver can do (anything else: say so kindly and set query to null):
- tournament push/fold, stacks above 0 up to 15bb (or say "push/fold"), chip EV or ICM
- GGPoker All-in or Fold cash game ("aof")

Query grammar (English words, space separated, only what the user gave or clearly meant):
  seat            UTG UTG1 UTG2 LJ HJ CO BTN SB BB     e.g. "BTN shove 10bb"
  facing a shove  "BB vs BTN shove 8bb"; several: "SB vs UTG and BTN 5bb"
  table size      "heads-up", "6-max", "3 handed" (unstated = 8-handed)
  hand            "hold K5s", "hold AJo", "hold 77"
  ICM             "icm" alone = live-game bubble (defaults below);
                  own payouts "icm 50/30/20"; back to chip EV: "chip ev"
  stage           "bubble", "final table", "50% left", "120 left", "field 500",
                  "paid 12%", "avg 25bb"
  money (THB)     "buy-in 1000", "pool 15000" (total prize pool / total buy-ins)
Payouts are computed from the real numbers: entries pick the payout column (live table up
to 47 entries: 2-7 pay 3, 8-15 pay 4, 16-23 pay 5, 24-31 pay 6, 32-47 pay 7; bigger fields pay
15% on an MTT curve), and pool = entries x buy-in unless a pool is given. With a pool but no
entries, entries = pool / buy-in. Defaults: 20 entries, 500 THB buy-in. So when the user gives
entries, buy-in or a prize pool, put them in the query ("field 30 buy-in 1000 icm") and redraw.
  ante            "ante 0.2bb", "no ante", "bb ante", "live"
  AoF             "aof BB vs CO", "aof 3 handed BTN"
Rules:
- A stack is needed for tournaments (AoF defaults to 10bb). If it is missing and not in the
  remembered spot, ask for it instead of guessing.
- A seat is needed. Map "button/ปุ่ม" -> BTN, "small blind" -> SB, "big blind" -> BB,
  "cutoff" -> CO, "hijack" -> HJ, "under the gun" -> UTG.
- "on the bubble / ใกล้เข้าเงิน / จะเข้าเงิน" -> "bubble"; "final table / โต๊ะสุดท้าย" -> "final table".
- Follow-ups: the solver remembers the last spot, so a short query that only changes one thing
  ("12bb", "vs CO shove") is fine. The remembered spot is given below when there is one.
- Small talk or thanks: reply briefly and set query to null."""


class AssistantError(RuntimeError):
    """เรียกโมเดลไม่สำเร็จ หรือคำตอบไม่ใช่ JSON ที่ตกลงกันไว้"""


@dataclasses.dataclass(frozen=True)
class Crafted:
    say: str
    query: str | None


@dataclasses.dataclass(frozen=True)
class Turn:
    user: str
    assistant: str


@dataclasses.dataclass(frozen=True)
class Answer:
    """ผลของหนึ่งข้อความในโหมด AI"""

    say: str                         # ข้อความคุยจากโมเดล หรือข้อความบอกว่าถอยไปโหมดพื้นฐาน
    query: str | None                # คำถามที่ส่งให้ solver None คือไม่ได้ทำชาร์ต
    made: object | None              # spot_chart.Reply จาก solve None คือไม่ได้ทำชาร์ต
    history: tuple[Turn, ...]        # ประวัติคุยใหม่ ใช้ส่งกลับมาตาถัดไป


def api_key() -> str | None:
    return keys.find(*KEY_NAMES)


def toggle(text: str) -> bool | None:
    """True ถ้าเป็นคำสั่งเปิด False ถ้าปิด None ถ้าไม่ใช่คำสั่ง"""
    word = text.strip().lower()
    if word in ON_COMMANDS:
        return True
    if word in OFF_COMMANDS:
        return False
    return None


def remembered(memory) -> str:
    """spot ที่จำไว้เป็นข้อความสั้นให้โมเดลรู้ว่าคุยถึงอะไรอยู่ เฉพาะช่องที่มีค่า"""
    if memory is None:
        return "none"
    fields = dataclasses.asdict(memory)
    return json.dumps({name: value for name, value in fields.items()
                       if value not in (None, False, ())}, ensure_ascii=False)


def build_messages(text: str, history: tuple[Turn, ...], memory) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM}]
    for turn in history[-MAX_HISTORY_TURNS:]:
        messages += [{"role": "user", "content": turn.user},
                     {"role": "assistant", "content": turn.assistant}]
    messages.append({"role": "user",
                     "content": f"[remembered spot: {remembered(memory)}]\n{text}"})
    return messages


def parse(content: str) -> Crafted:
    """JSON จากโมเดล say ต้องมี query ว่างหรือไม่ใช่ข้อความถือว่าไม่ทำชาร์ต"""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as error:
        raise AssistantError(f"ไม่ใช่ JSON: {str(content)[:80]!r}") from error
    say = data.get("say") if isinstance(data, dict) else None
    if not isinstance(say, str) or not say.strip():
        raise AssistantError(f"ไม่มี say: {str(content)[:80]!r}")
    query = data.get("query")
    query = query.strip() if isinstance(query, str) and query.strip() else None
    return Crafted(say.strip(), query)


def _charge(usage: dict | None, seconds: float) -> None:
    usage = usage or {}
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    miss = int(usage.get("prompt_cache_miss_tokens", int(usage.get("prompt_tokens") or 0) - hit))
    output = int(usage.get("completion_tokens") or 0)
    peak = costs.is_peak()
    costs.record("deepseek", costs.deepseek_usd(hit, miss, output, peak),
                 quantity=hit + miss + output, seconds=seconds, model=MODEL,
                 hit=hit, miss=miss, output=output, peak=peak, estimated=not usage)


def craft(text: str, history: tuple[Turn, ...], memory, key: str) -> Crafted:
    """ถามโมเดลหนึ่งครั้ง ได้ข้อความคุยกับคำถามชาร์ต"""
    body = {"model": MODEL, "temperature": 0.3, "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
            "messages": build_messages(text, history, memory)}
    request = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            reply = json.loads(response.read())
        content = reply["choices"][0]["message"]["content"]
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError,
            KeyError, IndexError) as error:
        raise AssistantError(f"DeepSeek ไม่ตอบ: {error}") from error
    try:
        _charge(reply.get("usage"), time.perf_counter() - started)
    except OSError:
        pass  # จดค่าใช้จ่ายไม่ได้ไม่ควรทำให้ตอบไม่ได้
    return parse(content)


def answer(text: str, solve, history: tuple[Turn, ...] = (), memory=None,
           key: str | None = None, crafter=None) -> Answer:
    """หนึ่งข้อความในโหมด AI โมเดลพังก็ยังได้คำตอบจากโหมดพื้นฐาน

    solve(query, memory=...) คือ spot_chart.reply
    """
    key = key or api_key()
    try:
        if not key:
            raise AssistantError("ไม่มี DEEPSEEK_API_KEY")
        crafted = (crafter or craft)(text, history, memory, key)
    except AssistantError:
        return Answer(FELL_BACK, text, solve(text, memory=memory), history)
    made = solve(crafted.query, memory=memory) if crafted.query else None
    # เก็บคำตอบเป็น JSON แบบที่โมเดลตอบ ตาถัดไปโมเดลจะรู้ว่าเคยขอชาร์ตอะไรไปและตอบรูปแบบเดิม
    said = json.dumps({"say": crafted.say, "query": crafted.query}, ensure_ascii=False)
    turns = (*history, Turn(text, said))[-MAX_HISTORY_TURNS:]
    return Answer(crafted.say, crafted.query, made, turns)
