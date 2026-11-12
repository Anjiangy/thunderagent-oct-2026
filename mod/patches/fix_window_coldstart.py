"""Treat "no history yet" as "probably a long window", not as "no window".

First version returned 0.0 for a program with fewer than two recorded gaps, so the
gate refused to move exactly the programs that had never been seen idle.  In a
four-turn session that means the move only becomes legal at turn 3 - by which point
the source card has already thrashed for two turns (measured: hits 58,880 -> 0 -> 20,096
against 101,632 for the ungated arm).

An unknown window is now reported as -1.0 (unknown) and the gate treats it as
permission: we only refuse a move once we have evidence that this program comes
back quickly.

Idempotent.
"""
from __future__ import annotations

import pathlib
import sys

PROGRAMS = pathlib.Path(__file__).resolve().parents[1] / "executor" / "programs.py"
APP = pathlib.Path(__file__).resolve().parents[1] / "executor" / "app.py"

PROGRAM_EDITS = [
    (
        "            if entry is None or len(entry.gaps) < 2:\n                return 0.0\n",
        "            if entry is None or len(entry.gaps) < 2:\n"
        "                return -1.0  # unknown, not zero: see module docstring\n",
    ),
    (
        '        """Median inter-turn gap, or 0.0 while there is nothing to go on."""',
        '        """Median inter-turn gap, or -1.0 while there is nothing to go on."""',
    ),
]

APP_EDITS = [
    (
        "            keep = [c for c in candidates if self.table.idle_estimate(c) >= want]\n",
        "            keep = [c for c in candidates\n"
        "                    if self.table.idle_estimate(c) < 0\n"
        "                    or self.table.idle_estimate(c) >= want]\n",
    ),
]


def apply(path: pathlib.Path, edits) -> int:
    text = path.read_text(encoding="utf-8")
    applied = skipped = 0
    for old, new in edits:
        if new in text:
            skipped += 1
            continue
        if old not in text:
            print(f"{path.name}: anchor not found:\n{old[:90]}...")
            return -1
        text = text.replace(old, new, 1)
        applied += 1
    if applied:
        path.write_text(text, encoding="utf-8")
    print(f"{path.name}: applied={applied} skipped={skipped}")
    return applied


def main() -> int:
    if apply(PROGRAMS, PROGRAM_EDITS) < 0 or apply(APP, APP_EDITS) < 0:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
