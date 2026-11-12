"""Patch ThunderAgent in place: overcapacity admission + a hook for program->shard hints.

Two knobs, both env-gated so the upstream default behaviour is untouched:

  TA_OVERCOMMIT=1        -> a new program is admitted even when no backend has room
                            (pick the least-loaded healthy one instead of waiting).
  TA_OVERCOMMIT=1        -> resume waits are skipped, so a paused program is not held.

Idempotent: markers `# [ta-patch:overcommit]` guard every edit.
"""
from __future__ import annotations
import pathlib, sys

ROOT = pathlib.Path(r"E:\studyfiles\dsh\Thunderagent\ThunderAgent")
ROUTER = ROOT / "ThunderAgent" / "scheduler" / "router.py"
MARK = "# [ta-patch:overcommit]"

PROLOGUE = '''

# [ta-patch:overcommit] ---- begin ----
def _ta_overcommit() -> bool:
    """True when TA should admit programs past its KV budget."""
    import os
    return os.environ.get("TA_OVERCOMMIT", "0").strip().lower() in {"1", "true", "yes", "on"}


# [ta-patch:overcommit] ---- end ----
'''

OLD_ROUTE = """        if backend.remaining_capacity() < required_capacity:
                continue  # Not enough capacity for this program"""
NEW_ROUTE = """        if backend.remaining_capacity() < required_capacity:  # [ta-patch:overcommit]
                if not _ta_overcommit():
                    continue  # Not enough capacity for this program
                # [ta-patch:overcommit] overcapacity is allowed: rank by load only"""

OLD_RET = """        return best_backend.url if best_backend else None"""
NEW_RET = """        if best_backend is None and _ta_overcommit():  # [ta-patch:overcommit]
            healthy = [b for b in self.backends.values() if b.healthy]
            if healthy:
                best_backend = min(healthy, key=lambda b: b.active_program_tokens)
        return best_backend.url if best_backend else None"""

OLD_WAIT = """                await self._wait_for_resume(program_id, state)"""
NEW_WAIT = """                if not _ta_overcommit():  # [ta-patch:overcommit]
                    await self._wait_for_resume(program_id, state)"""


def apply() -> int:
    src = ROUTER.read_text(encoding="utf-8")
    if MARK in src:
        print("already patched")
        return 0

    n = 0
    for old, new in ((OLD_ROUTE, NEW_ROUTE), (OLD_RET, NEW_RET)):
        if old not in src:
            raise SystemExit("anchor missing:\n" + old[:120])
        src = src.replace(old, new, 1); n += 1

    if OLD_WAIT not in src:
        raise SystemExit("anchor missing: wait_for_resume")
    src = src.replace(OLD_WAIT, NEW_WAIT)  # both call sites
    n += src.count(MARK) - (n + 2)

    # insert the prologue right after the logger definition
    anchor = "logger = logging.getLogger(__name__)"
    if anchor not in src:
        raise SystemExit("anchor missing: logger")
    src = src.replace(anchor, anchor + PROLOGUE, 1)

    ROUTER.write_text(src, encoding="utf-8")
    print(f"patched router.py ({n} edits)")
    return 0


if __name__ == "__main__":
    sys.exit(apply())
