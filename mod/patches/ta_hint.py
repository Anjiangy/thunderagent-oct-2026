"""Second TA patch: program -> shard hint (env-gated) + strip the hint field before forwarding."""
from __future__ import annotations
import pathlib, sys

ROOT = pathlib.Path(r"E:\studyfiles\dsh\Thunderagent\ThunderAgent")
ROUTER = ROOT / "ThunderAgent" / "scheduler" / "router.py"
PROC = ROOT / "ThunderAgent" / "scheduler" / "vllm_request_processor.py"
MARK = "# [ta-patch:hint]"

HELPERS = '''


# [ta-patch:hint] ---- begin ----
def _ta_hint_enabled() -> bool:
    import os
    return os.environ.get("TA_HINT", "0").strip().lower() in {"1", "true", "yes", "on"}


def _ta_hint_map() -> dict:
    """TA_HINT_BACKENDS='a=http://127.0.0.1:8110,b=http://<POD-N-POD>:8110'"""
    import os
    out = {}
    for item in os.environ.get("TA_HINT_BACKENDS", "").split(","):
        if "=" in item:
            key, val = item.split("=", 1)
            out[key.strip()] = val.strip().rstrip("/")
    return out


def _ta_hint_target(payload) -> "Optional[str]":
    if not isinstance(payload, dict):
        return None
    cand = payload.get("program_id_hint")
    if cand is None and isinstance(payload.get("extra_body"), dict):
        cand = payload["extra_body"].get("program_id_hint")
    if cand is None:
        return None
    cand = str(cand).strip().rstrip("/")
    if not cand:
        return None
    table = _ta_hint_map()
    return table.get(cand, cand if cand.startswith("http") else None)


# [ta-patch:hint] ---- end ----
'''

OLD_ANCHOR = """        state.step_count += 1
        is_new_program = state.step_count == 1"""
NEW_ANCHOR = """        state.step_count += 1
        is_new_program = state.step_count == 1

        # [ta-patch:hint] steer this program to the shard the caller asks for
        if _ta_hint_enabled():
            _want = _ta_hint_target(payload)
            _cur = state.backend_url
            _tgt = self.backends.get(_want) if _want else None
            if _tgt is not None and _tgt.healthy and _cur and _tgt.url != _cur:
                _old = self.backends.get(_cur)
                if _old is not None:
                    _old.unregister_program(program_id)
                _tgt.register_program(program_id, state)
                state.backend_url = _tgt.url
                self.hint_moves = getattr(self, "hint_moves", 0) + 1
                logger.info(f"[hint] {program_id} -> {_tgt.url} (moves={self.hint_moves})")"""

OLD_STRIP = """    payload.pop("program_id", None)"""
NEW_STRIP = """    payload.pop("program_id", None)
    payload.pop("program_id_hint", None)  # [ta-patch:hint]
    if isinstance(payload.get("extra_body"), dict):
        payload["extra_body"].pop("program_id_hint", None)  # [ta-patch:hint]"""


def main() -> int:
    src = ROUTER.read_text(encoding="utf-8")
    if MARK not in src:
        if MARK in src or OLD_ANCHOR not in src:
            raise SystemExit("anchor missing: step_count block")
        src = src.replace(OLD_ANCHOR, NEW_ANCHOR, 1)
        anchor = "logger = logging.getLogger(__name__)"
        if anchor not in src:
            raise SystemExit("anchor missing: logger")
        src = src.replace(anchor, anchor + HELPERS, 1)
        ROUTER.write_text(src, encoding="utf-8")
        print("router.py: hint added")
    else:
        print("router.py: already patched")

    psrc = PROC.read_text(encoding="utf-8")
    if MARK not in psrc:
        if OLD_STRIP not in psrc:
            raise SystemExit("anchor missing: remove_program_id body")
        psrc = psrc.replace(OLD_STRIP, NEW_STRIP, 1)
        PROC.write_text(psrc, encoding="utf-8")
        print("processor: hint stripped")
    else:
        print("processor: already patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
