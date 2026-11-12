"""Move the transfer off the request path.

Before: the balancer awaited `_do_migrate`, which drained the program, captured on
the source, pulled into the target and only then flipped the pin.  Two costs landed
on live traffic: `_route` answered 503 while `migrating` was set, and the capture
prefill competed with everyone else on the source card (multi-second tail).

After: the move runs as a background task.  The pin keeps pointing at the source
until the transfer completes, so requests are served normally the whole time; the
target is warmed before the flip, so the first turn after the move is a cache hit.

Idempotent.
"""
from __future__ import annotations

import pathlib
import sys

APP = pathlib.Path(__file__).resolve().parents[1] / "executor" / "app.py"

EDITS = [
    (
        "        self.moves: int = 0\n",
        "        self.moves: int = 0\n        self._warming: set[str] = set()\n",
    ),
    (
        "        candidates = self.table.migration_candidates(hot)\n"
        "        if not candidates:\n"
        "            return 0\n"
        "        code, _ = await _do_migrate(candidates[0], cold, BALANCE_MODE,\n"
        "                                    MIGRATE_TIMEOUT, allow_degraded=True)\n"
        "        return 1 if code == 200 else 0\n",
        "        candidates = [c for c in self.table.migration_candidates(hot)\n"
        "                      if c not in self._warming]\n"
        "        if not candidates:\n"
        "            return 0\n"
        "        self._spawn_migration(candidates[0], cold)\n"
        "        return 0\n"
        "\n"
        "    def _spawn_migration(self, program_id: str, target: str) -> None:\n"
        "        \"\"\"Hand one move to a background task.\n"
        "\n"
        "        The pin flips only when the transfer finishes, so the source card\n"
        "        keeps serving this program's turns in the meantime.  Nothing on the\n"
        "        request path ever waits for the peer.\n"
        "        \"\"\"\n"
        "        self._warming.add(program_id)\n"
        "\n"
        "        async def _run() -> None:\n"
        "            try:\n"
        "                code, _ = await _do_migrate(program_id, target, BALANCE_MODE,\n"
        "                                            MIGRATE_TIMEOUT, allow_degraded=True)\n"
        "                if code == 200:\n"
        "                    self.moves += 1\n"
        "            except Exception:  # noqa: BLE001 - a failed move must not kill the loop\n"
        "                pass\n"
        "            finally:\n"
        "                self._warming.discard(program_id)\n"
        "\n"
        "        asyncio.create_task(_run())\n",
    ),
    (
        "    entry = STATE.table.touch(program_id)\n"
        "    if entry.migrating:\n"
        "        return JSONResponse(\n"
        "            {\"error\": \"program is migrating\", \"program_id\": program_id,\n"
        "             \"target\": entry.migrate_target, \"mode\": entry.migrate_mode},\n"
        "            status_code=503, headers={\"Retry-After\": \"1\"})\n",
        "    # A move no longer blocks traffic: `entry.instance` still names the source\n"
        "    # card until the transfer finishes, so assign() below routes there.\n"
        "    entry = STATE.table.touch(program_id)\n",
    ),
    (
        '"move_budget": BALANCE_MOVE_BUDGET},',
        '"move_budget": BALANCE_MOVE_BUDGET, "warming": len(self._warming)},',
    ),
]


def main() -> int:
    if not APP.exists():
        print(f"missing {APP}")
        return 2
    text = APP.read_text(encoding="utf-8")
    applied = skipped = 0
    for old, new in EDITS:
        if new in text:
            skipped += 1
            continue
        if old not in text:
            print(f"anchor not found:\n{old[:100]}...")
            return 3
        text = text.replace(old, new, 1)
        applied += 1
    if applied:
        APP.write_text(text, encoding="utf-8")
    print(f"applied={applied} skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
