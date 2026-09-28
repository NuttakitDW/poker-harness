"""Terminal colours: Ravenclaw sapphire and bronze on the terminal's dark ground."""

from __future__ import annotations

from prompt_toolkit.styles import Style
from rich.text import Text

SIGNAL = "#5D9BFF"   # bright sapphire: the accent, live values
DEPTH = "#0F2A6B"    # deep blue fills
BRONZE = "#B08D4F"   # supporting accent: rules, labels
PALE = "#E8ECF5"     # body text
ASH = "#6B7488"      # muted text
EDGE = "#1F2740"     # hairlines
ERROR = "#E0605A"
LEAD = f"bold {SIGNAL}"


def prompt_style() -> Style:
    """The status bar keeps our own colours instead of prompt_toolkit's reversed grey."""
    return Style.from_dict({"bottom-toolbar": "noreverse bg:#0B0E16"})


def banner(run_name: str, members: int) -> Text:
    return Text.assemble(
        ("\n  DEEPSTACK", f"bold {PALE}"),
        (" / ", ASH),
        ("SWARM", f"bold {SIGNAL}"),
        (f"   run {run_name}", BRONZE),
        (f"   {members} agents\n", ASH),
    )
