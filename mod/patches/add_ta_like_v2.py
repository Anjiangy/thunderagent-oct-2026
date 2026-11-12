"""ta_like v2: over-admit instead of blind sleep, and wake on completion."""
from __future__ import annotations
import pathlib

P = pathlib.Path("mod/cli.py")
s = P.read_text(encoding="utf-8")
if "over_admit" in s:
    print("already patched")
    raise SystemExit(0)

s = s.replace("""        self.migrations = 0
        self._pending_hold = 0.0""", """        self.migrations = 0
        self.over_admit = 0
        self.waits = 0
        self._pending_hold = 0.0
        self._cond = None""")

s = s.replace("""    def take_hold(self) -> float:""", """    def condition(self):
        \"\"\"Lazily create the wake-up condition on the running loop.\"\"\"
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    def take_hold(self) -> float:""")

s = s.replace("""        if mode == "ta_like":
            card, hold = self.ta_like_decide(key, est)
            if hold > 0:
                self.holds += 1
                self.hold_s += hold
                self._pending_hold = hold
            return card""", """        if mode == "ta_like":
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
            return card""")

s = s.replace("""        hold = state.take_hold()
        if hold > 0:
            await asyncio.sleep(hold)""", """        hold = state.take_hold()
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
                state.hold_s += time.time() - started""")

s = s.replace("""            finally:
                state.in_flight[card] = max(0, state.in_flight.get(card, 1) - 1)""", """            finally:
                state.in_flight[card] = max(0, state.in_flight.get(card, 1) - 1)
                if state._cond is not None:
                    async with state._cond:
                        state._cond.notify_all()""")

s = s.replace("""            "holds": self.holds,""", """            "holds": self.holds,
            "waits": self.waits,
            "over_admit": self.over_admit,""")

P.write_text(s, encoding="utf-8")
print("patched mod/cli.py -> v2")
