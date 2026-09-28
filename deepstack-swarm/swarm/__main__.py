"""python -m swarm chat|monitor [options]"""

from __future__ import annotations

import sys


def main() -> None:
    command, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if command == "chat":
        from swarm import chat

        chat.run(rest)
    elif command == "monitor":
        from swarm import monitor

        monitor.run(rest)
    else:
        sys.exit("usage: python -m swarm chat|monitor [--help]")


main()
