"""The Briefing: builds each agent's system prompt from its SOUL, TEAM.md and the roster."""

from __future__ import annotations

from typing import Iterable

from swarm.router import Mail
from swarm.roster import USER_ID, Member

LEAD_DUTIES = """## Your extra duties as lead

- You are the only agent the user talks to. Use `tell_user` for everything the user should read:
  answers, plans, progress on long work, questions, and final results. Plain text is not shown.
- When the user gives you a research question, restate it as a concrete plan, assign parts to
  teammates with `send_message`, and tell the user who is doing what in one short message.
- Do small things yourself. Delegate when a teammate's papers make them the right person.
- Do not relay every teammate message to the user; summarize when a piece of work lands, when
  there is a disagreement the user should decide, or when you are blocked.
- Before reporting a result as settled, check it meets the finding standard in TEAM.md.
"""


def roster_table(roster: Iterable[Member]) -> str:
    rows = ["| id | persona | role |", "|---|---|---|"]
    rows += [f"| `{m.id}` | {m.name} | {m.role} |" for m in roster]
    return "## The team\n\n" + "\n".join(rows) + "\n"


def system_prompt(member: Member, roster: Iterable[Member], team_rules: str) -> str:
    parts = [
        member.soul(),
        team_rules,
        roster_table(roster),
        f"## You\n\nYour id is `{member.id}`.\n",
    ]
    if member.is_lead:
        parts.append(LEAD_DUTIES)
    return "\n\n".join(parts)


def inbox_prompt(batch: Iterable[Mail]) -> str:
    blocks = []
    for mail in batch:
        if mail.sender == USER_ID:
            head = "[from user] (direct from the user)" if mail.direct else "[from user]"
        else:
            head = f"[from {mail.sender}]"
        blocks.append(f"{head}\n{mail.text}")
    return "\n\n".join(blocks)
