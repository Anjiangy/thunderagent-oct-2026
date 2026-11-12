"""ta_like policy: capacity ledger, pause first, migrate second."""
from __future__ import annotations
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from mod.policy import (  # noqa: E402
    BUFFER_PER_PROGRAM,
    TA_LIKE_HOLD_MAX_S,
    TA_LIKE_PAUSE_MAX_S,
    decide,
    held,
)


def test_buffer_is_charged_per_program():
    assert BUFFER_PER_PROGRAM == 100
    assert held({"a": 500}, {"a": 2}, "a") == 700


def test_fits_picks_the_empty_card():
    card, hold, moved = decide(
        ["a", "b"], {"a": 5_000, "b": 0}, {"a": 1}, {"a": 10_000, "b": 10_000}, {}, 1_000, 1_000, None
    )
    assert (card, hold, moved) == ("b", 0.0, False)


def test_short_overflow_waits_instead_of_moving():
    card, hold, moved = decide(
        ["a", "b"],
        {"a": 900, "b": 0},
        {"a": 1},
        {"a": 1_000, "b": 10_000},
        {"a": 1},
        own=900,
        est=900,
        current="a",
    )
    assert card == "a"
    assert 0 < hold <= TA_LIKE_PAUSE_MAX_S
    assert moved is False


def test_big_overflow_moves_when_destination_has_room():
    card, hold, moved = decide(
        ["a", "b"],
        {"a": 2_000, "b": 0},
        {"a": 1},
        {"a": 1_000, "b": 10_000},
        {},
        own=2_000,
        est=2_000,
        current="a",
    )
    assert (card, hold, moved) == ("b", 0.0, True)


def test_no_room_anywhere_holds_but_is_capped():
    card, hold, moved = decide(
        ["a", "b"],
        {"a": 5_000, "b": 5_000},
        {"a": 1, "b": 1},
        {"a": 1_000, "b": 1_000},
        {},
        own=5_000,
        est=5_000,
        current="a",
    )
    assert card == "a"
    assert hold <= TA_LIKE_HOLD_MAX_S
    assert moved is False


def test_never_moves_into_a_card_too_small_for_the_prefix():
    card, hold, moved = decide(
        ["a", "b"],
        {"a": 9_000, "b": 0},
        {"a": 1},
        {"a": 10_000, "b": 3_000},
        {},
        own=4_000,
        est=4_000,
        current="a",
    )
    assert card == "a"
    assert moved is False
