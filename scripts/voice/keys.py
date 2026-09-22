"""อ่านคีย์ของบริการภายนอกจาก environment ก่อน แล้วค่อยถอยไปอ่าน .env

ทุกบริการที่เรียกใช้ต้องการคีย์คนละชื่อ แต่วิธีหาเหมือนกันหมด
รวมไว้ที่เดียวเพื่อให้เพิ่มบริการใหม่ได้โดยไม่ต้องคัดลอกตรรกะเดิม
"""

from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def find(*names: str) -> str | None:
    """คืนค่าคีย์ตัวแรกที่พบตามชื่อที่ให้มา หรือ None ถ้าไม่มีสักชื่อ"""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    env_file = ROOT / ".env"
    if not env_file.exists():
        return None
    wanted = set(names)
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() in wanted:
            return value.strip().strip("'\"") or None
    return None


def require(*names: str) -> str:
    """เหมือน find แต่จบโปรแกรมพร้อมบอกชื่อตัวแปรที่ต้องตั้ง"""
    value = find(*names)
    if value:
        return value
    raise SystemExit(f"ไม่พบ {names[0]} ใน environment หรือ .env")
