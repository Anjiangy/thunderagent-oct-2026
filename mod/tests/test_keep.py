"""Gates around the keep loop: each one exists because M10 showed it matters."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from executor.keep import KeepConfig, cluster_capacity, eligible, keep_candidates, needs_refresh

LIVE = {"a": {"healthy": True, "kv_capacity_tokens": 100_000.0}}
CFG = KeepConfig(enabled=True, min_tokens=2000, min_turns=2, interval_s=2.0,
                 ttl_s=900.0, cap_fraction=0.65)


@dataclass
class FakeEntry:
    program_id: str = "p"
    instance: Optional[str] = "a"
    prompt_body: Optional[Dict[str, Any]] = field(default_factory=lambda: {"prompt": "x"})
    prompt_path: Optional[str] = "/v1/completions"
    prompt_tokens: int = 5000
    requests: int = 2
    in_flight: int = 0
    migrating: bool = False
    last_seen: float = field(default_factory=time.time)
    last_refresh: float = 0.0


def test_capacity_sums_healthy_cards_only():
    live = {"a": {"healthy": True, "kv_capacity_tokens": 100.0},
            "b": {"healthy": False, "kv_capacity_tokens": 900.0},
            "c": {"healthy": True, "block_size": 128, "num_gpu_blocks": 10}}
    assert cluster_capacity(live) == 100.0 + 1280.0


def test_disabled_keeps_nothing():
    cfg = KeepConfig(enabled=False)
    assert keep_candidates([FakeEntry()], LIVE, time.time(), cfg) == []


def test_small_program_is_not_worth_a_slot():
    entry = FakeEntry(prompt_tokens=1500)
    assert not eligible(entry, LIVE, time.time(), CFG)


def test_single_turn_program_is_not_yet_known_to_return():
    entry = FakeEntry(requests=1)
    assert not eligible(entry, LIVE, time.time(), CFG)


def test_busy_or_migrating_programs_are_skipped():
    assert not eligible(FakeEntry(in_flight=1), LIVE, time.time(), CFG)
    assert not eligible(FakeEntry(migrating=True), LIVE, time.time(), CFG)


def test_program_quiet_longer_than_ttl_is_considered_gone():
    stale = FakeEntry(last_seen=time.time() - 1000)
    assert not eligible(stale, LIVE, time.time(), CFG)


def test_unknown_or_unhealthy_instance_is_skipped():
    assert not eligible(FakeEntry(instance="zz"), LIVE, time.time(), CFG)
    assert not eligible(FakeEntry(), {"a": {"healthy": False}}, time.time(), CFG)


def test_refresh_interval_gate():
    now = time.time()
    entry = FakeEntry(last_refresh=now - 0.5)
    assert not needs_refresh(entry, now, CFG)
    entry.last_refresh = now - 3.0
    assert needs_refresh(entry, now, CFG)


def test_candidates_are_biggest_first():
    now = time.time()
    entries = [FakeEntry(program_id="small", prompt_tokens=2500),
               FakeEntry(program_id="big", prompt_tokens=9000),
               FakeEntry(program_id="mid", prompt_tokens=5000)]
    assert keep_candidates(entries, LIVE, now, CFG) == ["big", "mid", "small"]


def test_budget_stops_at_the_cap_instead_of_hoarding():
    now = time.time()
    # 65% of 100k = 65k: the 40k one fits, the next 40k would exceed it.
    entries = [FakeEntry(program_id="a1", prompt_tokens=40000),
               FakeEntry(program_id="a2", prompt_tokens=40000)]
    assert keep_candidates(entries, LIVE, now, CFG) == ["a1"]


def test_already_refreshed_this_interval_is_skipped():
    now = time.time()
    entries = [FakeEntry(program_id="fresh", last_refresh=now - 0.1),
               FakeEntry(program_id="due", last_refresh=now - 10.0)]
    assert keep_candidates(entries, LIVE, now, CFG) == ["due"]
