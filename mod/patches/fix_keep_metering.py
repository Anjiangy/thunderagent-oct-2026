"""Measure what a keep refresh actually computes, not what it looks up.

`usage.prompt_tokens` is the whole prompt even on a full cache hit, so it cannot
answer "how much did this refresh cost". The engine's prefix-cache counters can:
computed = (queries - hits) for the window around the refresh.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("executor/app.py")
s = p.read_text(encoding="utf-8")

helper = '''    async def _instance_counters(self, base: str) -> Tuple[float, float]:
        """Prefix-cache (queries, hits) for one engine, or (0, 0) if unreachable."""
        assert self.client is not None
        try:
            r = await self.client.get(base + "/metrics", timeout=SCRAPE_TIMEOUT)
            r.raise_for_status()
            info = parse_metrics(r.text)
        except Exception:  # noqa: BLE001 - a failed scrape must not break the loop
            return 0.0, 0.0
        return (float(info.get("prefix_cache_queries_total") or 0.0),
                float(info.get("prefix_cache_hits_total") or 0.0))

'''
anchor = "    async def _keep_once(self) -> int:\n"
if "_instance_counters" not in s:
    s = s.replace(anchor, helper + anchor, 1)

old_block = '''                r = await self.client.post(base + entry.prompt_path, json=payload,
                                           timeout=httpx.Timeout(120.0, connect=5.0))
                if r.status_code != 200:
                    continue
                usage = (r.json() or {}).get("usage") or {}
                computed = int(usage.get("prompt_tokens") or 0)
                self.table.record_refresh(program_id, computed)
                self.keeps += 1
                self.keep_tokens += computed
                sent += 1'''
new_block = '''                q0, h0 = await self._instance_counters(base)
                r = await self.client.post(base + entry.prompt_path, json=payload,
                                           timeout=httpx.Timeout(120.0, connect=5.0))
                if r.status_code != 200:
                    continue
                q1, h1 = await self._instance_counters(base)
                looked = int(max(0.0, q1 - q0))
                computed = int(max(0.0, (q1 - q0) - (h1 - h0)))
                self.table.record_refresh(program_id, computed)
                self.keeps += 1
                self.keep_tokens += computed
                self.keep_looked_up += looked
                sent += 1'''
if old_block in s:
    s = s.replace(old_block, new_block, 1)
elif new_block not in s:
    sys.exit("refresh body anchor not found")

if "self.keep_looked_up: int = 0" not in s:
    s = s.replace("        self.keep_tokens: int = 0\n",
                  "        self.keep_tokens: int = 0\n        self.keep_looked_up: int = 0\n", 1)
s = s.replace('"computed_tokens": STATE.keep_tokens}',
              '"computed_tokens": STATE.keep_tokens, "looked_up_tokens": STATE.keep_looked_up}', 1)
s = s.replace('print(f"[keep] refreshed={sent} total={self.keeps} computed={self.keep_tokens}",',
              'print(f"[keep] refreshed={sent} total={self.keeps} computed={self.keep_tokens} looked_up={self.keep_looked_up}",', 1)
p.write_text(s, encoding="utf-8")
print("patched keep metering")
