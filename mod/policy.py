"""Pure ta_like policy: capacity ledger, pause first, migrate second.

Kept free of web-framework imports so it can be unit tested anywhere.
"""
from __future__ import annotations
from typing import Dict, Iterable, List, Tuple

BUFFER_PER_PROGRAM = 100
TA_LIKE_PAUSE_MAX_S = 2.0
TA_LIKE_HOLD_MAX_S = 30.0
TA_LIKE_DRAIN_TOK_PER_S = 800.0


def held(load: Dict[str, int], counts: Dict[str, int], card: str) -> int:
    return load[card] + BUFFER_PER_PROGRAM * counts.get(card, 0)


def decide(
    cards: Iterable[str],
    load: Dict[str, int],
    counts: Dict[str, int],
    capacity: Dict[str, int],
    in_flight: Dict[str, int],
    own: int,
    est: int,
    current: str | None,
) -> Tuple[str, float, bool]:
    """Return (card, hold_seconds, migrated)."""
    names: List[str] = sorted(cards)
    card = current
    if card is None:
        card = min(names, key=lambda n: held(load, counts, n))
    over = (
        load[card]
        - (own if current == card else 0)
        + est
        + BUFFER_PER_PROGRAM * (counts.get(card, 0) + 1)
        - capacity.get(card, 0)
    )
    if over <= 0:
        return card, 0.0, False
    wait = over / TA_LIKE_DRAIN_TOK_PER_S
    if wait <= TA_LIKE_PAUSE_MAX_S and in_flight.get(card, 0) > 0:
        return card, wait, False
    for name in names:
        if name == card:
            continue
        room = capacity.get(name, 0) - load[name] - BUFFER_PER_PROGRAM * counts.get(name, 0)
        if room >= max(own, est):
            return name, 0.0, True
    return card, min(TA_LIKE_HOLD_MAX_S, wait), False
