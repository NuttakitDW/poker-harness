"""เรียก OpenThai-SystemOne ของ iApp โมเดลที่ตอบเป็นการตัดสินใจอย่างเดียว ไม่เขียนข้อความ

ส่งสถานะกับคำถามแบบเลือกตอบไป ได้ตัวเลือกพร้อมความน่าจะเป็นของทุกตัวเลือกกลับมา
ใช้เวลาราว 0.2 วินาที จึงเร็วพอจะคั่นระหว่างคำถามกับการวาดตาราง

คู่มือ: https://iapp.co.th/th/docs/llm/openthai-systemone
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import NamedTuple

import keys

URL = "https://api.iapp.co.th/v3/store/openthai/systemone"
KEY_NAMES = ("IAPP_API", "IAPP_API_KEY")
TIMEOUT_SECONDS = 5.0


class SystemOneError(RuntimeError):
    """เรียกบริการไม่สำเร็จ ผู้เรียกควรถอยไปใช้วิธีที่ไม่ต้องพึ่งเครือข่าย"""


class Choice(NamedTuple):
    """คำตอบของคำถามแบบเลือกหนึ่งข้อ"""

    choice: str
    probabilities: dict[str, float]
    confidence: float

    @property
    def probability(self) -> float:
        """ความน่าจะเป็นของตัวที่เลือก"""
        return self.probabilities.get(self.choice, 0.0)


def available() -> bool:
    """มีคีย์ให้เรียกหรือไม่"""
    return keys.find(*KEY_NAMES) is not None


def _post(body: dict, key: str, timeout: float) -> dict:
    request = urllib.request.Request(
        URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"apikey": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemOneError(f"SystemOne ตอบ {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise SystemOneError(f"เรียก SystemOne ไม่ได้: {error}") from error


def choose(state: dict | str, questions: dict[str, tuple[str, dict[str, str]]],
           key: str | None = None, timeout: float = TIMEOUT_SECONDS) -> dict[str, Choice]:
    """ถามคำถามแบบเลือกตอบหลายข้อในครั้งเดียว

    questions คือ {ชื่อคำถาม: (คำสั่ง, {ตัวเลือก: คำอธิบาย})}
    """
    key = key or keys.find(*KEY_NAMES)
    if not key:
        raise SystemOneError("ไม่พบ IAPP_API ใน environment หรือ .env")
    body = {
        "state": state,
        # ตัวเลือกเรียงแบบไหนก็ต้องได้คำตอบเดิม ถามสองรอบสลับลำดับแล้วเฉลี่ย
        "order_invariant": True,
        "permutations": 2,
        "questions": {
            name: {"type": "choice", "instructions": instructions, "criteria": criteria}
            for name, (instructions, criteria) in questions.items()
        },
    }
    answers = _post(body, key, timeout).get("answers")
    if not isinstance(answers, dict):
        raise SystemOneError("SystemOne ไม่ได้ส่งคำตอบกลับมา")
    chosen = {}
    for name in questions:
        answer = answers.get(name) or {}
        if "choice" not in answer:
            raise SystemOneError(f"SystemOne ไม่ได้ตอบข้อ {name}")
        chosen[name] = Choice(str(answer["choice"]),
                              {str(k): float(v) for k, v in answer.get("probabilities", {}).items()},
                              float(answer.get("confidence", 0.0)))
    return chosen
