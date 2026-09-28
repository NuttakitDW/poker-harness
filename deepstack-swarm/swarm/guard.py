"""The Guard: what an agent may do without asking.

Reading the repo and the web is always fine. Writing is fine only inside the
swarm workspace, so a persona can never overwrite pushfold/ or the website;
it proposes changes as files there instead. Bash is allowed for running
experiments, minus anything that commits, rewrites git history, installs
packages or deletes recursively.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

_BASH_BLOCKED = (
    (re.compile(r"\bgit\s+(commit|push|reset|rebase|checkout|restore|clean|stash|merge|tag|branch\s+-[dD])\b"),
     "git write commands are off limits; the user commits"),
    (re.compile(r"\b(pip|pip3)\s+install\b|\buv\s+(add|remove|sync|pip)\b|\bbrew\s+install\b"),
     "installing packages is off limits; ask the lead to ask the user"),
    (re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*|--recursive)\b"),
     "recursive delete is off limits"),
    (re.compile(r"\bsudo\b"), "sudo is off limits"),
    (re.compile(r"(curl|wget)[^|]*\|\s*(ba|z)?sh\b"), "piping downloads into a shell is off limits"),
)


@dataclasses.dataclass(frozen=True)
class Verdict:
    allow: bool
    reason: str = ""


def inside(path: str | Path, root: Path, cwd: Path) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def judge(tool: str, tool_input: dict[str, Any], workspace: Path, cwd: Path) -> Verdict:
    if tool in WRITE_TOOLS:
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if target and inside(target, workspace, cwd):
            return Verdict(True)
        return Verdict(False, f"write outside the swarm workspace ({workspace}); put files there instead")
    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        for pattern, reason in _BASH_BLOCKED:
            if pattern.search(command):
                return Verdict(False, reason)
        return Verdict(True)
    return Verdict(True)
