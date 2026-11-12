"""Wire the keep loop into the executor (idempotent)."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def patch(path: pathlib.Path, pairs: list[tuple[str, str]]) -> None:
    src = path.read_text(encoding="utf-8")
    out = src
    for old, new in pairs:
        if new in out:
            continue
        if old not in out:
            sys.exit(f"anchor not found in {path.name}: {old[:60]!r}")
        out = out.replace(old, new, 1)
    if out != src:
        path.write_text(out, encoding="utf-8")
        print(f"patched {path.name}")


patch(
    ROOT / "executor" / "programs.py",
    [
        (
            "    prompt_tokens: int = 0\n    warmed_tokens: int = 0\n",
            "    prompt_tokens: int = 0\n    warmed_tokens: int = 0\n"
            "    # Refreshes sent to keep this program's blocks in the cache, and when\n"
            "    # the last one went out. Only the keep loop touches these.\n"
            "    keeps: int = 0\n"
            "    last_refresh: float = 0.0\n",
        ),
        (
            '            "prompt_tokens": self.prompt_tokens,',
            '            "prompt_tokens": self.prompt_tokens,\n'
            '            "keeps": self.keeps,\n'
            '            "last_refresh": self.last_refresh,',
        ),
        (
            "    def migration_candidates(self, instance: str) -> List[str]:",
            "    def record_refresh(self, program_id: str, tokens: int) -> None:\n"
            "        \"\"\"Note that a keep refresh went out and what it cost.\"\"\"\n"
            "        with self._lock:\n"
            "            entry = self._programs.get(program_id)\n"
            "            if entry is not None:\n"
            "                entry.keeps += 1\n"
            "                entry.last_refresh = time.time()\n"
            "                entry.warmed_tokens = int(tokens or 0)\n"
            "\n"
            "    def migration_candidates(self, instance: str) -> List[str]:",
        ),
    ],
)

patch(
    ROOT / "executor" / "app.py",
    [
        (
            "from .programs import ProgramTable",
            "from .keep import KeepConfig, keep_candidates\nfrom .programs import ProgramTable",
        ),
        (
            "        self.moves: int = 0\n",
            "        self.moves: int = 0\n"
            "        self.keep = KeepConfig.from_env()\n"
            "        self.keeps: int = 0\n"
            "        self.keep_tokens: int = 0\n",
        ),
        (
            "@asynccontextmanager\nasync def lifespan(app: FastAPI):",
            "    async def keep_loop(self) -> None:\n"
            "        \"\"\"Refresh idle programs so other traffic cannot evict them.\"\"\"\n"
            "        while not self._stop.is_set():\n"
            "            try:\n"
            "                await self._keep_once()\n"
            "            except Exception:  # noqa: BLE001 - keeping must never take the server down\n"
            "                pass\n"
            "            try:\n"
            "                await asyncio.wait_for(self._stop.wait(), timeout=self.keep.interval_s)\n"
            "            except asyncio.TimeoutError:\n"
            "                continue\n"
            "\n"
            "    async def _keep_once(self) -> int:\n"
            "        if not self.keep.enabled:\n"
            "            return 0\n"
            "        assert self.client is not None\n"
            "        now = time.time()\n"
            "        targets = keep_candidates(self.table.entries(), self.live, now, self.keep)\n"
            "        if not targets:\n"
            "            return 0\n"
            "        sent = 0\n"
            "        for program_id in targets:\n"
            "            entry = self.table.get(program_id)\n"
            "            if entry is None or entry.prompt_body is None:\n"
            "                continue\n"
            "            base = self.backends.get(entry.instance or \"\")\n"
            "            if not base:\n"
            "                continue\n"
            "            payload = dict(entry.prompt_body)\n"
            "            payload[\"max_tokens\"] = 1\n"
            "            payload[\"temperature\"] = 0.0\n"
            "            payload[\"stream\"] = False\n"
            "            try:\n"
            "                r = await self.client.post(base + entry.prompt_path, json=payload,\n"
            "                                           timeout=httpx.Timeout(120.0, connect=5.0))\n"
            "                if r.status_code != 200:\n"
            "                    continue\n"
            "                usage = (r.json() or {}).get(\"usage\") or {}\n"
            "                computed = int(usage.get(\"prompt_tokens\") or 0)\n"
            "                self.table.record_refresh(program_id, computed)\n"
            "                self.keeps += 1\n"
            "                self.keep_tokens += computed\n"
            "                sent += 1\n"
            "            except Exception:  # noqa: BLE001 - one failed refresh is not fatal\n"
            "                continue\n"
            "        if sent:\n"
            "            print(f\"[keep] refreshed={sent} total={self.keeps} computed={self.keep_tokens}\",\n"
            "                  flush=True)\n"
            "        return sent\n"
            "\n"
            "\n"
            "@asynccontextmanager\nasync def lifespan(app: FastAPI):",
        ),
        (
            "        tasks.append(asyncio.create_task(STATE.balance_loop())),",
            "        tasks.append(asyncio.create_task(STATE.balance_loop()))",
        ),
        (
            "    if STATE.balance in (\"skew\", \"on\", \"1\", \"true\"):\n"
            "        tasks.append(asyncio.create_task(STATE.balance_loop()))",
            "    if STATE.balance in (\"skew\", \"on\", \"1\", \"true\"):\n"
            "        tasks.append(asyncio.create_task(STATE.balance_loop()))\n"
            "    if STATE.keep.enabled:\n"
            "        tasks.append(asyncio.create_task(STATE.keep_loop()))",
        ),
        (
            '        "balance_thresholds": {"hot": BALANCE_HOT, "cold": BALANCE_COLD, "mode": BALANCE_MODE},',
            '        "balance_thresholds": {"hot": BALANCE_HOT, "cold": BALANCE_COLD, "mode": BALANCE_MODE},\n'
            '        "keep": {**STATE.keep.to_dict(), "refreshes": STATE.keeps, "computed_tokens": STATE.keep_tokens},',
        ),
    ],
)
print("done")
