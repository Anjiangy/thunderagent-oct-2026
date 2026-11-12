"""Add mode=ta_like: TA's capacity ledger + pause-first, migrate-second."""
from __future__ import annotations
import pathlib

P = pathlib.Path("mod/cli.py")
s = P.read_text(encoding="utf-8")

if "ta_like_decide" in s:
    print("already patched")
    raise SystemExit(0)

# 1. constants
anchor = "_USAGE_RE = re.compile(rb'\"total_tokens\"\\s*:\\s*(\\d+)')"
assert anchor in s, "usage regex anchor missing"
s = s.replace(anchor, anchor + '''

BUFFER_PER_PROGRAM = 100      # same constant ThunderAgent uses
TA_LIKE_PAUSE_MAX_S = 2.0     # below this, waiting beats moving
TA_LIKE_HOLD_MAX_S = 30.0     # never hold a request longer than this
TA_LIKE_DRAIN_TOK_PER_S = 800.0  # rough drain rate of one card, tokens/s''')

# 2. state fields
anchor = "        self.pinned: Dict[str, str] = {}"
assert anchor in s
s = s.replace(anchor, anchor + '''
        self.capacity: Dict[str, int] = {}
        self.in_flight: Dict[str, int] = {}
        self.holds = 0
        self.hold_s = 0.0
        self.migrations = 0
        self._pending_hold = 0.0''')

# 3. helpers + ta_like policy
anchor = "    def snapshot(self) -> dict:"
assert anchor in s
s = s.replace(anchor, '''    # ---- ta_like: capacity ledger, pause first, migrate second --------
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

    def take_hold(self) -> float:
        hold = self._pending_hold
        self._pending_hold = 0.0
        return hold

    def snapshot(self) -> dict:''')

# 4. pick: ta_like branch
anchor = '''        mode = self.effective_mode()
        key = pid or "default"'''
assert anchor in s
s = s.replace(anchor, '''        mode = self.effective_mode()
        key = pid or "default"
        if mode == "ta_like":
            card, hold = self.ta_like_decide(key, est)
            if hold > 0:
                self.holds += 1
                self.hold_s += hold
                self._pending_hold = hold
            return card''')

# 5. snapshot fields
anchor = '''            "moves": self.moves,'''
assert anchor in s
s = s.replace(anchor, '''            "moves": self.moves,
            "capacity_tokens": self.capacity,
            "in_flight": self.in_flight,
            "holds": self.holds,
            "hold_seconds_total": round(self.hold_s, 2),
            "migrations": self.migrations,''')

# 6. handler: hold + in-flight accounting
anchor = '''        card = state.pick(pid, est)
        upstream = state.cards[card]'''
assert anchor in s
s = s.replace(anchor, '''        card = state.pick(pid, est)
        hold = state.take_hold()
        if hold > 0:
            await asyncio.sleep(hold)
        upstream = state.cards[card]''')

anchor = '''        resp = await client.send(
            client.build_request(request.method, url, content=body, headers=headers), stream=True
        )'''
assert anchor in s
s = s.replace(anchor, '''        state.in_flight[card] = state.in_flight.get(card, 0) + 1
        try:
            resp = await client.send(
                client.build_request(request.method, url, content=body, headers=headers), stream=True
            )
        except Exception:
            state.in_flight[card] = max(0, state.in_flight.get(card, 1) - 1)
            raise''')

anchor = '''            state.add_usage(pid, best)'''
assert anchor in s
s = s.replace(anchor, '''            state.add_usage(pid, best)''')

anchor = '''        async def metered():
            best = 0
            buf = b""
            async for chunk in resp.aiter_bytes():
                yield chunk
                buf = (buf + chunk)[-8192:]
                if b"usage" in buf:
                    m = _USAGE_RE.search(buf)
                    if m:
                        best = max(best, int(m.group(1)))
            state.add_usage(pid, best)'''
assert anchor in s
s = s.replace(anchor, '''        async def metered():
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
            state.add_usage(pid, best)''')

# 7. CLI: capacity parsing + mode choice
anchor = '''    ap.add_argument("--mode", choices=["passthrough", "affinity", "sticky"], default="passthrough")'''
assert anchor in s
s = s.replace(anchor, '''    ap.add_argument(
        "--mode",
        choices=["passthrough", "affinity", "sticky", "ta_like"],
        default="passthrough",
    )
    ap.add_argument("--capacity", action="append", default=[], metavar="NAME=TOKENS")''')

anchor = '''    state = ModState(args.mode, cards, args.kill_switch)'''
assert anchor in s
s = s.replace(anchor, '''    state = ModState(args.mode, cards, args.kill_switch)
    for spec in args.capacity:
        name, _, value = spec.partition("=")
        if not name or name not in cards or not value.isdigit():
            raise SystemExit(f"--capacity expects NAME=TOKENS for a configured card, got {spec!r}")
        state.capacity[name] = int(value)
    if args.mode == "ta_like" and len(state.capacity) != len(cards):
        raise SystemExit("--mode ta_like requires one --capacity NAME=TOKENS per card")''')

# 8. asyncio import
if "import asyncio" not in s:
    s = s.replace("import argparse", "import argparse\nimport asyncio", 1)

P.write_text(s, encoding="utf-8")
print("patched mod/cli.py")
