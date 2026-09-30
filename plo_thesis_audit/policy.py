"""Observable-input boundary for the only constrained BB thesis action."""

from __future__ import annotations


class ThesisBBPolicy:
    """Trash checks for free; non-Trash behavior is deliberately unspecified."""

    def action(self, bb_tier: str) -> str | None:
        return "check" if bb_tier == "Trash" else None

