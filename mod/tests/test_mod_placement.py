"""Unit tests for the Mod placement logic (no server, no fastapi)."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _stub(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def load_mod():
    if "mod_cli" in sys.modules:
        return sys.modules["mod_cli"]
    # fastapi / httpx are server-side deps; stub them so the logic is importable.
    _stub("fastapi", FastAPI=object, Request=object)
    _stub("fastapi.responses", JSONResponse=object, StreamingResponse=object)
    _stub("httpx", AsyncClient=object)
    spec = importlib.util.spec_from_file_location("mod_cli", ROOT / "mod" / "cli.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mod_cli"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def state(mode: str = "sticky"):
    m = load_mod()
    return m.ModState(mode, {"a": "http://a:8110", "b": "http://b:8110"}, "")


def test_estimate_prefers_prompt_then_messages():
    m = load_mod()
    assert m.estimate_tokens({"prompt": "x" * 360}) == 100
    assert m.estimate_tokens({"messages": [{"role": "user", "content": "y" * 72}]}) == 20
    assert m.estimate_tokens({}) == 0


def test_load_is_max_of_estimate_and_usage():
    st = state()
    st.record("p1", 100)
    st.add_usage("p1", 400)
    st.pinned["p1"] = "a"
    assert st.load() == {"a": 400, "b": 0}


def test_affinity_pins_for_ever():
    st = state("affinity")
    first = st.pick("p1", 100)
    for _ in range(5):
        assert st.pick("p1", 100) == first
    assert st.moves == 0


def test_sticky_spreads_when_first_program_is_large():
    st = state("sticky")
    st.record("big", 10_000)
    st.pinned["big"] = "a"
    st.record("small", 100)
    # "small" should go to the empty card, not onto the already full one
    assert st.pick("small", 100) == "b"


def test_sticky_keeps_a_program_that_is_its_own_load():
    st = state("sticky")
    st.record("p1", 5_000)
    st.pinned["p1"] = "a"
    # p1 is 100% of a's load, so re-evaluating with its own load removed says "stay"
    assert st.pick("p1", 0) == "a"
    assert st.moves == 0


def test_sticky_moves_when_the_other_card_is_clearly_lighter():
    st = state("sticky")
    st.record("heavy", 9_000)
    st.pinned["heavy"] = "a"
    st.record("light", 100)
    st.pinned["light"] = "a"
    st.record("mover", 1_000)
    st.pinned["mover"] = "a"
    assert st.pick("mover", 1_000) == "b"
    assert st.moves == 1


def test_passthrough_round_robins():
    st = state("passthrough")
    seen = {st.pick("p1", 10) for _ in range(4)}
    assert seen == {"a", "b"}


def test_kill_switch_forces_passthrough(tmp_path):
    m = load_mod()
    kill = tmp_path / "kill"
    st = m.ModState("sticky", {"a": "http://a", "b": "http://b"}, str(kill))
    st.record("big", 10_000)
    st.pinned["big"] = "a"
    st.record("p2", 100)
    assert st.pick("p2", 100) == "b"          # sticky: lighter card
    kill.write_text("1")
    assert st.effective_mode() == "passthrough"
    st.pinned.clear()
    seq = [st.pick("p3", 0) for _ in range(2)]
    assert set(seq) == {"a", "b"}


def test_usage_regex_reads_total_tokens():
    m = load_mod()
    m_ = m._USAGE_RE.search(b'{"usage":{"prompt_tokens":3,"total_tokens":4242}}')
    assert m_ is not None and int(m_.group(1)) == 4242
