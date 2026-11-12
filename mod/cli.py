"""E9 Mod: placement over two cards, program affinity, usage metering, kill switch.

Modes
-----
passthrough : round-robin, no memory (what the plain LB does)
affinity    : pin a program to the card it first landed on
sticky      : re-evaluate on every request, but only move when the program is
              not itself the reason its card is full (hysteresis by subtraction)

Load is measured in tokens.  Two sources:
  * estimate  -- len(text) / 3.6, available before the call
  * actual    -- usage.total_tokens, read out of the streamed response
`load()` uses max(estimate, actual) per program so a program is never counted
twice and never counted as smaller than it really is.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import time
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

CHARS_PER_TOKEN = 3.6
_USAGE_RE = re.compile(rb'"total_tokens"\s*:\s*(\d+)')

BUFFER_PER_PROGRAM = 100      # same constant ThunderAgent uses
TA_LIKE_PAUSE_MAX_S = 2.0     # below this, waiting beats moving
TA_LIKE_HOLD_MAX_S = 30.0     # never hold a request longer than this
TA_LIKE_DRAIN_TOK_PER_S = 800.0  # rough drain rate of one card, tokens/s


def estimate_tokens(payload: dict) -> int:
    text = payload.get("prompt")
    if not isinstance(text, str):
        msgs = payload.get("messages") or []
        parts = []
        for m in msgs:
            if isinstance(m, dict):
                c = m.get("content")
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, list):
                    parts.extend(str(p) for p in c)
        text = "".join(parts)
    return int(len(text) / CHARS_PER_TOKEN) if text else 0


class ModState:
    def __init__(self, mode: str, cards: Dict[str, str], kill_switch: str) -> None:
        self.mode = mode
        self.cards = cards
        self.kill_switch = kill_switch
        self.started = time.time()
        self.moves = 0
        self._rr = 0
        self.estimate: Dict[str, int] = {}
        self.actual: Dict[str, int] = {}
        self.pinned: Dict[str, str] = {}
        self.capacity: Dict[str, int] = {}
        self.in_flight: Dict[str, int] = {}
        self.holds = 0
        self.hold_s = 0.0
        self.migrations = 0
        self.over_admit = 0
        self.waits = 0
        self._pending_hold = 0.0
        self._cond = None

    # ---- modes -------------------------------------------------------
    def effective_mode(self) -> str:
        if self.kill_switch and pathlib.Path(self.kill_switch).exists():
            return "passthrough"
        return self.mode

    def program_tokens(self, pid: str) -> int:
        return max(self.estimate.get(pid, 0), self.actual.get(pid, 0))

    def load(self) -> Dict[str, int]:
        out = {name: 0 for name in self.cards}
        for pid, card in self.pinned.items():
            if card in out:
                out[card] += self.program_tokens(pid)
        return out

    def record(self, pid: Optional[str], est: int) -> None:
        if not pid or est <= 0:
            return
        self.estimate[pid] = max(self.estimate.get(pid, 0), est)

    def add_usage(self, pid: Optional[str], tokens: int) -> None:
        if not pid or tokens <= 0:
            return
        self.actual[pid] = max(self.actual.get(pid, 0), int(tokens))

    def pick(self, pid: Optional[str], est: int = 0) -> str:
        names = sorted(self.cards)
        if not names:
            raise RuntimeError("no cards configured")
        mode = self.effective_mode()
        key = pid or "default"
        if mode == "ta_like":
            card, hold = self.ta_like_decide(key, est)
            if hold > 0:
                load = self.load()
                stuck = all(load[n] >= self.capacity.get(n, 0) for n in self.cards)
                if stuck:
                    # waiting cannot create room: admit and record the over-commit
                    self.over_admit += 1
                else:
                    self.holds += 1
                    self.hold_s += hold
                    self._pending_hold = hold
            return card
        if mode == "passthrough":
            self._rr = (self._rr + 1) % len(names)
            card = names[self._rr]
            self.pinned[key] = card
            return card

        if mode == "affinity" and key in self.pinned:
            return self.pinned[key]

        load = self.load()
        current = self.pinned.get(key)
        # what the card would hold if this program were not on it
        def effective(name: str) -> int:
            own = self.program_tokens(key) if current == name else 0
            return load[name] - own

        best = min(names, key=lambda n: (effective(n), n))
        if mode == "sticky" and current is not None and best != current:
            # move only when the gain exceeds what the move itself costs
            if effective(best) + est >= effective(current):
                best = current
            else:
                self.moves += 1
        self.pinned[key] = best
        return best

    # ---- ta_like: capacity ledger, pause first, migrate second --------
    def _count(self, card: str) -> int:
        return sum(1 for c in self.pinned.values() if c == card)

    def _held(self, card: str) -> int:
        return self.load()[card] + BUFFER_PER_PROGRAM * self._count(card)

    def ta_like_decide(self, key: str, est: int) -> tuple:
        names = sorted(self.cards)
        load = self.load()
        cur = self.pinned.get(key)
        if cur is None:
            cur = min(names, key=lambda n: self._held(n))
        own = self.program_tokens(key)
        over = (
            load[cur] - (own if self.pinned.get(key) == cur else 0)
            + est + BUFFER_PER_PROGRAM * (self._count(cur) + 1)
            - self.capacity.get(cur, 0)
        )
        if over <= 0:
            self.pinned[key] = cur
            return cur, 0.0
        wait = over / TA_LIKE_DRAIN_TOK_PER_S
        # rule 1: a short wait beats a move
        if wait <= TA_LIKE_PAUSE_MAX_S and self.in_flight.get(cur, 0) > 0:
            self.pinned[key] = cur
            return cur, wait
        # rule 2: move only when the destination can hold this program's prefix
        for name in names:
            if name == cur:
                continue
            room = self.capacity.get(name, 0) - load[name] - BUFFER_PER_PROGRAM * self._count(name)
            if room >= max(own, est):
                self.pinned[key] = name
                self.migrations += 1
                return name, 0.0
        self.pinned[key] = cur
        return cur, min(TA_LIKE_HOLD_MAX_S, wait)

    def condition(self):
        """Lazily create the wake-up condition on the running loop."""
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    def take_hold(self) -> float:
        hold = self._pending_hold
        self._pending_hold = 0.0
        return hold

    def snapshot(self) -> dict:
        present = bool(self.kill_switch) and pathlib.Path(self.kill_switch).exists()
        return {
            "mode": self.effective_mode(),
            "configured_mode": self.mode,
            "kill_switch_present": present,
            "cards": self.cards,
            "programs_pinned": len(self.pinned),
            "load_tokens": self.load(),
            "moves": self.moves,
            "capacity_tokens": self.capacity,
            "in_flight": self.in_flight,
            "holds": self.holds,
            "waits": self.waits,
            "over_admit": self.over_admit,
            "hold_seconds_total": round(self.hold_s, 2),
            "migrations": self.migrations,
            "uptime_s": round(time.time() - self.started, 1),
        }


def build(args: argparse.Namespace) -> FastAPI:
    cards: Dict[str, str] = {}
    for spec in args.card:
        name, _, url = spec.partition("=")
        if not url:
            raise SystemExit(f"--card expects name=url, got {spec!r}")
        cards[name] = url.rstrip("/")
    state = ModState(args.mode, cards, args.kill_switch)
    for spec in args.capacity:
        name, _, value = spec.partition("=")
        if not name or name not in cards or not value.isdigit():
            raise SystemExit(f"--capacity expects NAME=TOKENS for a configured card, got {spec!r}")
        state.capacity[name] = int(value)
    if args.mode == "ta_like" and len(state.capacity) != len(cards):
        raise SystemExit("--mode ta_like requires one --capacity NAME=TOKENS per card")
    app = FastAPI()
    client = httpx.AsyncClient(timeout=None)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse(state.snapshot())

    @app.api_route("/{path:path}", methods=["GET", "POST", "DELETE"])
    async def proxy(path: str, request: Request):
        if path == "healthz":
            return JSONResponse(state.snapshot())
        body = await request.body()
        payload: dict = {}
        if body:
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}
        pid = (
            request.headers.get("x-program-id")
            or request.headers.get("x-session-id")
            or payload.get("program_id")
            or (payload.get("extra_body") or {}).get("program_id")
        )
        est = estimate_tokens(payload) if payload else 0
        state.record(pid, est)
        card = state.pick(pid, est)
        hold = state.take_hold()
        if hold > 0:
            started = time.time()
            cond = state.condition()
            state.waits += 1
            try:
                async with cond:
                    try:
                        await asyncio.wait_for(cond.wait(), timeout=hold)
                    except asyncio.TimeoutError:
                        pass
            finally:
                state.hold_s += time.time() - started
        upstream = state.cards[card]
        url = upstream + request.url.path
        if request.url.query:
            url += "?" + request.url.query
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() in {"content-type", "authorization", "accept", "x-request-id"}
        }
        if pid and "x-program-id" not in {k.lower() for k in headers}:
            headers["x-program-id"] = str(pid)
        state.in_flight[card] = state.in_flight.get(card, 0) + 1
        try:
            resp = await client.send(
                client.build_request(request.method, url, content=body, headers=headers), stream=True
            )
        except Exception:
            state.in_flight[card] = max(0, state.in_flight.get(card, 1) - 1)
            raise

        async def metered():
            best = 0
            buf = b""
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
                    buf = (buf + chunk)[-8192:]
                    if b"usage" in buf:
                        m = _USAGE_RE.search(buf)
                        if m:
                            best = max(best, int(m.group(1)))
            finally:
                state.in_flight[card] = max(0, state.in_flight.get(card, 1) - 1)
                if state._cond is not None:
                    async with state._cond:
                        state._cond.notify_all()
            state.add_usage(pid, best)

        return StreamingResponse(
            metered(),
            status_code=resp.status_code,
            headers={
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in {"content-length", "content-encoding"}
            },
        )

    return app


def main(argv: List[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="mod.cli")
    ap.add_argument("--listen", type=int, default=9002)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--mode",
        choices=["passthrough", "affinity", "sticky", "ta_like"],
        default="passthrough",
    )
    ap.add_argument("--capacity", action="append", default=[], metavar="NAME=TOKENS")
    ap.add_argument("--kill-switch", default="")
    ap.add_argument("--card", action="append", default=[], metavar="NAME=URL")
    args = ap.parse_args(argv)
    if not args.card:
        raise SystemExit("at least one --card NAME=URL is required")
    app = build(args)
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.listen, log_level="warning")


if __name__ == "__main__":
    main()
