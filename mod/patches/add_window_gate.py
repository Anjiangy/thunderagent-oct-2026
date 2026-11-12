"""Only move a program when its own idle window is long enough.

A move is only free if it finishes before the program comes back.  The executor
already knows how long each program normally idles (the gaps between its turns)
and how long recent moves took, so the decision can be made per program instead
of "always move as soon as a card looks hot".

`EXECUTOR_WINDOW_MIN` turns the gate on (seconds).  A candidate is skipped until

    median(its recent inter-turn gaps) >= max(WINDOW_MIN, 1.2 * recent move cost)

so a 4 s workload declines to move and a 15 s one moves.  `EXECUTOR_WINDOW_MIN=0`
restores the old behaviour.

Idempotent.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROGRAMS = ROOT / "executor" / "programs.py"
APP = ROOT / "executor" / "app.py"

PROGRAM_EDITS = [
    # remember when the previous turn ended and how long the gaps usually are
    (
        "    pending_kvp: Optional[Dict[str, Any]] = None\n",
        "    pending_kvp: Optional[Dict[str, Any]] = None\n"
        "    # Inter-turn gaps, newest last. Used to guess how long this program will\n"
        "    # stay away before its next request, i.e. how big the move window is.\n"
        "    last_turn_end: float = 0.0\n"
        "    gaps: List[float] = field(default_factory=list)\n",
    ),
    # record the gap when the program goes idle
    (
        "    def end_request(self, program_id: str) -> None:\n"
        "        with self._lock:\n"
        "            entry = self._programs.get(program_id)\n"
        "            if entry is not None:\n"
        "                entry.in_flight = max(0, entry.in_flight - 1)\n",
        "    def end_request(self, program_id: str) -> None:\n"
        "        with self._lock:\n"
        "            entry = self._programs.get(program_id)\n"
        "            if entry is not None:\n"
        "                entry.in_flight = max(0, entry.in_flight - 1)\n"
        "                if entry.in_flight == 0:\n"
        "                    now = time.time()\n"
        "                    gap = now - entry.last_turn_end if entry.last_turn_end else 0.0\n"
        "                    if 0.0 < gap <= 600.0:\n"
        "                        entry.gaps = (entry.gaps + [gap])[-8:]\n"
        "                    entry.last_turn_end = now\n",
    ),
    # the estimate itself
    (
        "    # -- migration ------------------------------------------------------\n",
        "    def idle_estimate(self, program_id: str) -> float:\n"
        "        \"\"\"Median inter-turn gap, or 0.0 while there is nothing to go on.\"\"\"\n"
        "        with self._lock:\n"
        "            entry = self._programs.get(program_id)\n"
        "            if entry is None or len(entry.gaps) < 2:\n"
        "                return 0.0\n"
        "            ordered = sorted(entry.gaps)\n"
        "            mid = len(ordered) // 2\n"
        "            if len(ordered) % 2:\n"
        "                return ordered[mid]\n"
        "            return 0.5 * (ordered[mid - 1] + ordered[mid])\n"
        "\n"
        "    # -- migration ------------------------------------------------------\n",
    ),
]

APP_EDITS = [
    (
        'BALANCE_MOVE_BUDGET = int(os.environ.get("EXECUTOR_BALANCE_MOVE_BUDGET", "0"))',
        'BALANCE_MOVE_BUDGET = int(os.environ.get("EXECUTOR_BALANCE_MOVE_BUDGET", "0"))\n'
        '# 0 disables the window gate; any positive value is the shortest window\n'
        '# (seconds) worth starting a move in.\n'
        'WINDOW_MIN = float(os.environ.get("EXECUTOR_WINDOW_MIN", "0"))\n'
        'MOVE_COST_INIT = float(os.environ.get("EXECUTOR_MOVE_COST_INIT", "0.6"))',
    ),
    (
        "        self._warming: set[str] = set()\n",
        "        self._warming: set[str] = set()\n"
        "        self.move_cost: float = MOVE_COST_INIT\n",
    ),
    # gate candidates on their own idle estimate
    (
        "        candidates = [c for c in self.table.migration_candidates(hot)\n"
        "                      if c not in self._warming]\n"
        "        if not candidates:\n"
        "            return 0\n",
        "        candidates = [c for c in self.table.migration_candidates(hot)\n"
        "                      if c not in self._warming]\n"
        "        if WINDOW_MIN > 0:\n"
        "            want = max(WINDOW_MIN, 1.2 * self.move_cost)\n"
        "            keep = [c for c in candidates if self.table.idle_estimate(c) >= want]\n"
        "            if not keep:\n"
        "                print(f\"[bal] window gate: {len(candidates)} candidates, none idles \"\n"
        "                      f\">={want:.1f}s (move_cost={self.move_cost:.2f}s)\", flush=True)\n"
        "            candidates = keep\n"
        "        if not candidates:\n"
        "            return 0\n",
    ),
    # learn how long a move actually takes
    (
        "                code, _ = await _do_migrate(program_id, target, BALANCE_MODE,\n"
        "                                            MIGRATE_TIMEOUT, allow_degraded=True)\n"
        "                if code == 200:\n"
        "                    self.moves += 1\n",
        "                started = time.time()\n"
        "                code, _ = await _do_migrate(program_id, target, BALANCE_MODE,\n"
        "                                            MIGRATE_TIMEOUT, allow_degraded=True)\n"
        "                spent = time.time() - started\n"
        "                self.move_cost = 0.7 * self.move_cost + 0.3 * spent\n"
        "                if code == 200:\n"
        "                    self.moves += 1\n",
    ),
    (
        '"move_budget": BALANCE_MOVE_BUDGET},',
        '"move_budget": BALANCE_MOVE_BUDGET, "window_min": WINDOW_MIN,'
        ' "move_cost_ema": round(STATE.move_cost, 3)},',
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
    if apply(PROGRAMS, PROGRAM_EDITS) < 0:
        return 3
    if apply(APP, APP_EDITS) < 0:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
