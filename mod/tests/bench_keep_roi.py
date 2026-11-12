"""ROI test: does keeping a program alive pay for itself over a multi-turn session?

The M11 test answered "does it survive" (0/10 -> 10/10). This one answers the
only question that matters for adoption: over a session that comes back several
times while other traffic is hitting the card, does the recompute we avoid
exceed the tokens the refreshes themselves burn?

Design:
  - N programs, each its own long prompt, T turns, `--gap` seconds between turns
  - a background flooder keeps unrelated traffic flowing the whole time, so the
    blocks are under constant eviction pressure (this is the regime where keep
    is supposed to matter)
  - every turn's cost is measured as (dq - dh) for that request alone

Reported: recompute per turn per program (summed), total, and wall clock.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import re
import threading
import time

import httpx

MODEL = os.environ.get("BENCH_MODEL", "Qwen2.5-14B-Instruct")
EXE = os.environ.get("BENCH_EXE", "http://127.0.0.1:8100")
ENGINE = os.environ.get("BENCH_ENGINE", "http://127.0.0.1:8110")

WORDS = (
    "server handler cache prefix block decoder token tensor kernel stream batch layer "
    "matrix gradient buffer shard pipeline socket packet vector index segment fragment "
    "commit branch patch review thread issue report metric latency throughput capacity "
    "schedule queue worker actor lease epoch window bucket shard replica leader follower"
).split()

Q_RE = re.compile(r"^vllm:prefix_cache_queries_total\{[^}]*\}\s+([0-9.eE+-]+)", re.M)
H_RE = re.compile(r"^vllm:prefix_cache_hits_total\{[^}]*\}\s+([0-9.eE+-]+)", re.M)


def counters(client: httpx.Client) -> tuple[float, float]:
    text = client.get(ENGINE + "/metrics", timeout=30).text
    return (sum(float(m) for m in Q_RE.findall(text)),
            sum(float(m) for m in H_RE.findall(text)))


def make_prefix(rng: random.Random, words: int, tag: str) -> str:
    return f"[{tag}] " + " ".join(rng.choice(WORDS) for _ in range(words))


def ask(client: httpx.Client, prompt: str, program_id: str, max_tokens: int = 24) -> None:
    body = {"model": MODEL, "prompt": prompt, "max_tokens": max_tokens,
            "temperature": 0.0, "program_id": program_id}
    r = client.post(EXE + "/v1/completions", json=body, timeout=600)
    r.raise_for_status()


class Flooder(threading.Thread):
    """Unrelated traffic straight at the engine: it never becomes a program."""

    def __init__(self, words: int, workers: int = 2) -> None:
        super().__init__(daemon=True)
        self.words = words
        self.workers = workers
        self.stop = threading.Event()
        self.sent = 0
        self.tokens = 0
        self._lock = threading.Lock()

    def run(self) -> None:
        rng = random.Random("flood")
        with httpx.Client(headers={"content-type": "application/json"}) as raw:
            while not self.stop.is_set():
                filler = make_prefix(rng, self.words, f"f{self.sent}")
                try:
                    raw.post(ENGINE + "/v1/completions",
                             json={"model": MODEL, "prompt": filler, "max_tokens": 2,
                                   "temperature": 0.0}, timeout=120)
                    with self._lock:
                        self.sent += 1
                        self.tokens += int(len(filler) / 3.6)
                except Exception:  # noqa: BLE001 - pressure is best effort
                    time.sleep(0.05)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="roi")
    ap.add_argument("--programs", type=int, default=10)
    ap.add_argument("--prefix-words", type=int, default=3000)
    ap.add_argument("--turns", type=int, default=4)
    ap.add_argument("--gap", type=float, default=12.0)
    ap.add_argument("--flood-words", type=int, default=3000)
    ap.add_argument("--no-flood", action="store_true")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    rng = random.Random(f"{args.label}:{args.seed}")
    out = pathlib.Path("data")
    out.mkdir(exist_ok=True)

    with httpx.Client(headers={"content-type": "application/json"}) as client:
        health = client.get(EXE + "/healthz", timeout=30).json()
        keep = health.get("keep") or {}
        print(f"[roi] label={args.label} keep={keep}")

        flooder = None
        if not args.no_flood:
            flooder = Flooder(args.flood_words)
            flooder.start()

        prompts = {f"{args.label}-p{i}": make_prefix(rng, args.prefix_words, f"{args.label}-p{i}")
                   for i in range(args.programs)}
        per_turn: list[dict] = []
        started = time.time()
        for turn in range(args.turns):
            if turn and args.gap:
                time.sleep(args.gap)
            for pid, prompt in prompts.items():
                q0, h0 = counters(client)
                ask(client, prompt, pid)
                q1, h1 = counters(client)
                dq, dh = q1 - q0, h1 - h0
                per_turn.append({"turn": turn, "program_id": pid, "queries": dq, "hits": dh,
                                 "recompute": max(0.0, dq - dh),
                                 "hit_rate": (dh / dq) if dq else 0.0})
            done = [r for r in per_turn if r["turn"] == turn]
            print(f"[roi] turn {turn}: recompute={sum(r['recompute'] for r in done):.0f} "
                  f"hit={sum(r['hits'] for r in done) / max(1.0, sum(r['queries'] for r in done)):.3f}")
        wall = time.time() - started

        if flooder:
            flooder.stop.set()
            flooder.join(timeout=10)
        health_after = client.get(EXE + "/healthz", timeout=30).json()

    total_recompute = sum(r["recompute"] for r in per_turn)
    summary = {
        "label": args.label,
        "keep_enabled": bool((health_after.get("keep") or {}).get("enabled")),
        "programs": args.programs,
        "turns": args.turns,
        "prefix_words": args.prefix_words,
        "gap_s": args.gap,
        "wall_s": round(wall, 1),
        "total_recompute": round(total_recompute),
        "per_turn_recompute": [round(sum(r["recompute"] for r in per_turn if r["turn"] == t))
                               for t in range(args.turns)],
        "hit_rate_overall": round(sum(r["hits"] for r in per_turn)
                                  / max(1.0, sum(r["queries"] for r in per_turn)), 4),
        "flood_requests": flooder.sent if flooder else 0,
        "flood_tokens": flooder.tokens if flooder else 0,
        "keep_refreshes": (health_after.get("keep") or {}).get("refreshes"),
        "keep_computed_tokens": (health_after.get("keep") or {}).get("computed_tokens"),
        "keep_looked_up_tokens": (health_after.get("keep") or {}).get("looked_up_tokens"),
    }
    with (out / "m11_keep_roi.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
