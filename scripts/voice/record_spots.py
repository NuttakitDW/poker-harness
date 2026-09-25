"""พาอัดเสียงคำถาม spot ทีละข้อ เพื่อสร้างชุดเสียงจริงไว้วัดตัวถอดเสียงกับตัวอ่าน

แต่ละข้อโชว์การ์ดสถานการณ์กับคำแนะนำวิธีพูด ผู้อัดพูดด้วยคำของตัวเอง ไม่ต้องอ่านตามบท
เฉลยมาจากการ์ดเอง อัดเสร็จถอดเสียงด้วย Soniox (context spot) แล้วโชว์ว่าตัวอ่านได้อะไร ถูกไหม

ไฟล์เสียงเก็บเป็น .ogg ที่ tests/fixtures/spot/voice/ เฉลยกับข้อความที่ถอดได้ต่อท้าย
tests/fixtures/spot/recorded.jsonl ปิดกลางคันได้ รอบหน้าทำต่อจากข้อที่ยังไม่ได้อัด

ใช้:
    make record-spots
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import random
import subprocess
import sys
import tempfile
import threading

import spot_eval

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "spot"
LABELS = FIXTURE_DIR / "recorded.jsonl"
VOICE_DIR = FIXTURE_DIR / "voice"
SAMPLE_RATE = 16_000
SEED = 7
EIGHT_MAX = ("UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "BB")
STACKS = (3, 4, 5, 6.5, 7, 7.5, 8, 9, 10, 11, 12, 12.5, 13, 14, 15)
HANDS = (["QQ"], ["55"], ["AKs"], ["K9s"], ["76s"], ["A5s"], ["J2o"], ["KTo"], ["Q9o"], ["A8o"],
         ["KQs", "KQo"], ["T9s"], ["A2o"], ["JJ"])
STYLES = (
    "พูดสั้น ๆ ภาษาไทย",
    "ผสมไทยอังกฤษแบบที่คุยกับเพื่อน",
    "เล่าสถานการณ์ยาว ๆ เหมือนเล่าให้เพื่อนฟัง",
    "พูดชื่อตำแหน่งกับ action เป็นอังกฤษทั้งหมด",
    "พูดเร็ว ๆ แบบรีบถามกลางโต๊ะ",
    "เริ่มด้วยมือที่ถือก่อน แล้วค่อยบอกสถานการณ์",
)
ANTES = (  # (คำบนการ์ด, เฉลย)
    ("ante 12.5% ของ BB ทุกคน", {"ante": 0.125, "ante_mode": "each"}),
    ("ante 0.2bb ทุกคน", {"ante": 0.2, "ante_mode": "each"}),
    ("ไม่มี ante", {"ante": 0.0}),
    ("BB ante (BB จ่ายแทนทั้งโต๊ะ)", {"ante_mode": "bb"}),
    ("live tournament (BB ante)", {"ante_mode": "bb"}),
    ("BB ante 1.5bb", {"ante": 1.5, "ante_mode": "bb"}),
    ("ante 15% ของ BB ทุกคน", {"ante": 0.15, "ante_mode": "each"}),
    ("ante 0.25bb ทุกคน", {"ante": 0.25, "ante_mode": "each"}),
)


@dataclasses.dataclass(frozen=True)
class Scenario:
    id: str
    group: str
    expected: dict
    style: str
    notes: tuple[str, ...] = ()  # สิ่งที่ต้องพูดเพิ่ม เช่นคำบอก ante หรือใครคอล


def table_seats(players: int) -> tuple[str, ...]:
    """ที่นั่งตามลำดับการเล่น heads-up ใช้ BTN กับ BB แบบที่คนพูด (ตัวอ่านแปลง BTN เป็น SB เอง)"""
    from pushfold.spot import position_names

    return ("BTN", "BB") if players == 2 else position_names(players)


def hand_words(hands: list[str]) -> str:
    """มือบนการ์ดเป็นคำที่พูดได้"""
    if len(hands) == 2:
        return f"{hands[0][:2]} (ไม่ต้องบอกดอก)"
    hand = hands[0]
    if len(hand) == 2:
        return f"pocket {hand}"
    return f"{hand[:2]} {'suited' if hand.endswith('s') else 'offsuit'}"


def _stack(rng: random.Random, low: float = 3, high: float = 15) -> float:
    return rng.choice([s for s in STACKS if low <= s <= high])


def _maybe_hand(rng: random.Random, expected: dict, chance: float = 0.5) -> dict:
    return {**expected, "hands": rng.choice(HANDS)} if rng.random() < chance else expected


def scenarios() -> list[Scenario]:
    """การ์ดทุกใบ เรียงแบบเดิมทุกครั้ง (สุ่มด้วย seed คงที่) id จึงไม่เปลี่ยน"""
    rng = random.Random(SEED)
    cards: list[tuple[str, dict, tuple[str, ...]]] = []
    for hero in ("UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "CO", "BTN", "SB"):
        cards.append(("first-in", _maybe_hand(rng, {"hero": hero, "stack": _stack(rng), "shovers": []}), ()))
    for _ in range(12):
        hero = rng.choice(EIGHT_MAX[2:])
        shover = rng.choice(EIGHT_MAX[:EIGHT_MAX.index(hero)])
        cards.append(("facing-one", _maybe_hand(rng, {"hero": hero, "stack": _stack(rng),
                                                      "shovers": [shover]}), ()))
    for index in range(8):
        hero = rng.choice(("CO", "BTN", "SB", "BB"))
        first, second = sorted(rng.sample(EIGHT_MAX[:EIGHT_MAX.index(hero)], 2), key=EIGHT_MAX.index)
        notes = (f"{second} call (ไม่ใช่ all-in เอง)",) if index % 2 else ()
        cards.append(("multiway", _maybe_hand(rng, {"hero": hero, "stack": _stack(rng),
                                                    "shovers": [first, second]}), notes))
    for players, hero, shovers in ((2, "BTN", []), (2, "BB", ["BTN"]), (6, "CO", []),
                                   (6, "BB", ["HJ"]), (3, "BTN", []), (3, "SB", ["BTN"])):
        cards.append(("table-size", _maybe_hand(rng, {"hero": hero, "stack": _stack(rng),
                                                      "shovers": shovers, "players": players}), ()))
    for words, ante in ANTES:
        hero = rng.choice(("CO", "BTN", "SB"))
        cards.append(("ante", {"hero": hero, "stack": _stack(rng), "shovers": [], **ante},
                      (f"บอก ante: {words}",)))
    for stack, hero, shovers in ((1.5, "UTG", []), (2, "BTN", []), (2.5, "BB", ["SB"])):
        cards.append(("tiny-stack", {"hero": hero, "stack": stack, "shovers": shovers}, ()))
    for stack, hero in ((16, "BTN"), (18, "CO"), (20, "SB")):
        cards.append(("deep-push-fold", {"hero": hero, "stack": stack, "shovers": []},
                      ("พูดคำว่า push/fold หรือ jam ด้วย (สแตกเกิน 15bb)",)))
    for hands in (["AKs"], ["J2o"], ["QQ"], ["A5s"], ["KQs", "KQo"], ["T9s"]):
        hero = rng.choice(("HJ", "CO", "BTN", "SB"))
        cards.append(("hand", {"hero": hero, "stack": _stack(rng), "shovers": [], "hands": hands},
                      ("เรียกไพ่เป็นคำ เช่น Ace King, แจ็คทู",)))
    return [Scenario(f"s{index:03d}", group, expected, STYLES[index % len(STYLES)], notes)
            for index, (group, expected, notes) in enumerate(cards, start=1)]


def _ante_words(expected: dict) -> str | None:
    for words, ante in ANTES:
        if ante == {key: expected[key] for key in ("ante", "ante_mode") if key in expected}:
            return words
    return None


def card(scenario: Scenario) -> str:
    """การ์ดสถานการณ์ที่โชว์ก่อนอัด"""
    expected = scenario.expected
    shovers = expected.get("shovers") or []
    called = next((note.split()[0] for note in scenario.notes if "call" in note), None)
    before = ", ".join(f"{seat} {'call' if seat == called else 'all-in'}" for seat in shovers)
    lines = [f"[{scenario.id}] {scenario.group}",
             f"  คุณอยู่:      {expected['hero']}",
             f"  สแตก:       {expected['stack']:g}bb (ที่เหลือหลังจ่าย ante)",
             f"  ก่อนหน้าคุณ:  {before or 'ไม่มีใครลงมา คุณเป็นคนแรกที่ตัดสินใจ'}"]
    if expected.get("players"):
        lines.append(f"  โต๊ะ:        {expected['players']} คน"
                     + (" (heads-up)" if expected["players"] == 2 else ""))
    spoken_ante = next((note.split(": ", 1)[1] for note in scenario.notes
                        if note.startswith("บอก ante")), None)
    ante = spoken_ante or _ante_words(expected)
    if ante:
        lines.append(f"  ante:       {ante}  (พูดออกมาด้วย)")
    if expected.get("hands"):
        lines.append(f"  มือที่ถือ:     {hand_words(expected['hands'])}")
    for note in scenario.notes:
        if "call" not in note and not note.startswith("บอก ante"):
            lines.append(f"  อย่าลืม:     {note}")
    lines.append(f"  วิธีพูด:      {scenario.style}")
    return "\n".join(lines)


def review_line(scenario: Scenario, read: dict) -> str:
    """สิ่งที่ตัวอ่านได้ เทียบกับเฉลยทีละฟิลด์"""
    parts = []
    for field, ok in spot_eval.check(scenario.expected, read).items():
        got = read.get(field)
        shown = got if not isinstance(got, float) else f"{got:g}"
        parts.append(f"{field} {shown} ✓" if ok
                     else f"{field} {shown} ✗ (ต้องได้ {scenario.expected[field]})")
    return "  ".join(parts)


def done(labels: pathlib.Path = LABELS) -> set[str]:
    if not labels.exists():
        return set()
    return {json.loads(line)["id"] for line in labels.read_text(encoding="utf-8").splitlines() if line}


def save(labels: pathlib.Path, scenario: Scenario, audio: str, heard: str) -> None:
    labels.parent.mkdir(parents=True, exist_ok=True)
    row = {"id": scenario.id, "group": scenario.group, "style": scenario.style,
           "expected": scenario.expected, "audio": audio, "heard": heard,
           "recorded_at": datetime.datetime.now().isoformat(timespec="seconds")}
    with labels.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _record(wav: pathlib.Path) -> float:
    """อัดจากไมค์ Enter เริ่ม Enter หยุด คืนความยาวเป็นวินาที"""
    import numpy
    import sounddevice
    import wave

    chunks: list = []
    stop = threading.Event()

    def collect(data, _frames, _time, _status):
        chunks.append(data.copy())

    input("  Enter เพื่อเริ่มอัด ")
    with sounddevice.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                 callback=collect):
        print("  กำลังอัด... พูดได้เลย แล้วกด Enter เมื่อพูดจบ", flush=True)
        input()
        stop.set()
    audio = numpy.concatenate(chunks) if chunks else numpy.zeros((0, 1), dtype="int16")
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(audio.tobytes())
    return len(audio) / SAMPLE_RATE


def _to_ogg(wav: pathlib.Path, ogg: pathlib.Path) -> None:
    ogg.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
                    "-c:a", "libopus", "-b:a", "24k", str(ogg)], check=True)


def _transcribe(ogg: pathlib.Path) -> str:
    import soniox_api

    return soniox_api.transcribe_bytes(ogg.read_bytes(), soniox_api.load_api_key(), ogg.name,
                                       "spot").text


def _take(scenario: Scenario, scratch: pathlib.Path) -> str:
    """อัดหนึ่งข้อจนผู้อัดพอใจ คืน keep, skip หรือ quit"""
    wav = scratch / f"{scenario.id}.wav"
    ogg = VOICE_DIR / f"{scenario.id}.ogg"
    while True:
        seconds = _record(wav)
        if seconds < 0.5:
            print("  สั้นเกินไป อัดใหม่อีกครั้ง")
            continue
        _to_ogg(wav, ogg)
        print("  กำลังถอดเสียง...", flush=True)
        try:
            heard = _transcribe(ogg)
        except Exception as error:  # noqa: BLE001 ถอดไม่ได้ก็ยังเก็บเสียงได้ ไว้ถอดทีหลัง
            heard = ""
            print(f"  ถอดเสียงไม่สำเร็จ: {error}")
        print(f"  ได้ยินว่า: {heard or '(ว่าง)'}  [{seconds:.1f}s]")
        print(f"  อ่านได้:  {review_line(scenario, spot_eval.regex_reader(heard))}")
        while True:
            choice = input("  [Enter] เก็บแล้วไปต่อ  [r] อัดใหม่  [p] ฟัง  [s] ข้าม  [q] ออก > ").strip().lower()
            if choice == "p":
                subprocess.run(["afplay", str(wav)], check=False)
                continue
            if choice == "r":
                break
            if choice in ("s", "q"):
                ogg.unlink(missing_ok=True)
                return "skip" if choice == "s" else "quit"
            save(LABELS, scenario, audio=str(ogg.relative_to(FIXTURE_DIR)), heard=heard)
            return "keep"


def main() -> int:
    pending = [s for s in scenarios() if s.id not in done()]
    total = len(scenarios())
    print(f"อัดคำถาม spot  เหลือ {len(pending)}/{total} ข้อ  (ปิดได้ทุกเมื่อ รอบหน้าทำต่อ)")
    print("พูดด้วยคำของตัวเองตามการ์ด ไม่ต้องอ่านตามตัวอักษร ให้ครบทุกอย่างบนการ์ด\n")
    with tempfile.TemporaryDirectory() as folder:
        for number, scenario in enumerate(pending, start=total - len(pending) + 1):
            print(f"\n({number}/{total})")
            print(card(scenario))
            try:
                result = _take(scenario, pathlib.Path(folder))
            except (KeyboardInterrupt, EOFError):
                print("\nหยุดแล้ว ข้อที่เก็บไปแล้วอยู่ครบ")
                return 0
            if result == "quit":
                break
    print(f"\nเก็บแล้ว {len(done())}/{total} ข้อ ที่ {LABELS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
