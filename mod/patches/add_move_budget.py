"""Cap how many programs the balancer may move in total (idempotent).

The M12 run showed four moves were enough to cut recompute by 72%. To find where
the marginal move stops paying we need to vary that number, so the budget is an
environment knob rather than a code edit per run.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("executor/app.py")
s = p.read_text(encoding="utf-8")

if "EXECUTOR_BALANCE_MOVE_BUDGET" not in s:
    s = s.replace(
        'BALANCE_MAX_MOVES = int(os.environ.get("EXECUTOR_BALANCE_MAX_MOVES", "200"))',
        'BALANCE_MAX_MOVES = int(os.environ.get("EXECUTOR_BALANCE_MAX_MOVES", "200"))\n'
        '# 0 means "no budget": keep balancing until nothing is worth moving.\n'
        'BALANCE_MOVE_BUDGET = int(os.environ.get("EXECUTOR_BALANCE_MOVE_BUDGET", "0"))',
        1,
    )
    s = s.replace(
        "    async def _balance_once(self) -> int:\n        usable",
        "    async def _balance_once(self) -> int:\n"
        "        if BALANCE_MOVE_BUDGET and self.moves >= BALANCE_MOVE_BUDGET:\n"
        "            return 0\n"
        "        usable",
        1,
    )
    s = s.replace(
        '        "balance_thresholds": {"hot": BALANCE_HOT, "cold": BALANCE_COLD, "mode": BALANCE_MODE},',
        '        "balance_thresholds": {"hot": BALANCE_HOT, "cold": BALANCE_COLD, "mode": BALANCE_MODE,\n'
        '                               "move_budget": BALANCE_MOVE_BUDGET},',
        1,
    )
    p.write_text(s, encoding="utf-8")
    print("patched move budget")
else:
    print("already patched")
