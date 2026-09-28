"""The Roster: who is on the team, read straight from the SOUL files.

Each souls/<first>-<last>.md becomes one member. The id is the surname
(`bowling`, `johanson`, ...) because two members share the first name Michael.
The role is the bold "**Role: ...**" line under "## Identity in the swarm".
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

LEAD_ID = "bowling"
USER_ID = "user"

_NAME = re.compile(r"^# SOUL\s*[—-]\s*(.+?)\s*$", re.MULTILINE)
_ROLE = re.compile(r"\*\*Role:\s*(.+?)\*\*")
_ROLE_CUT = re.compile(r"\s*(?:\(|—|\.\s)")


@dataclasses.dataclass(frozen=True)
class Member:
    id: str
    name: str
    role: str        # full role line
    short_role: str  # role up to the first "(", "—" or sentence end
    soul_path: Path

    @property
    def is_lead(self) -> bool:
        return self.id == LEAD_ID

    def soul(self) -> str:
        return self.soul_path.read_text(encoding="utf-8")


def parse_member(path: Path) -> Member:
    text = path.read_text(encoding="utf-8")
    name = _NAME.search(text)
    role = _ROLE.search(text)
    if not name or not role:
        raise ValueError(f"{path.name}: needs a '# SOUL — Name' title and a '**Role: ...**' line")
    full_role = role.group(1).strip().rstrip(".")
    short_role = _ROLE_CUT.split(full_role, maxsplit=1)[0].strip()
    member_id = path.stem.split("-", 1)[-1].replace("-", "_")
    return Member(member_id, name.group(1), full_role, short_role, path)


def load_roster(souls_dir: Path) -> tuple[Member, ...]:
    """All members, lead first, the rest alphabetical by id."""
    members = [parse_member(p) for p in sorted(souls_dir.glob("*.md"))]
    ids = [m.id for m in members]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate member ids in {souls_dir}: {ids}")
    if LEAD_ID not in ids:
        raise ValueError(f"no lead soul ({LEAD_ID}) in {souls_dir}")
    return tuple(sorted(members, key=lambda m: (not m.is_lead, m.id)))
