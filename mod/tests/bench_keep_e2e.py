"""Does the executor's keep loop actually save an idle program?

Three phases, all through the executor except the pressure:

0. settle  -- N programs, each its own long prompt, two turns (so the program
              table knows they come back).
1. flood   -- unrelated traffic sent straight to the engine, so it evicts the
              programs' blocks without the executor noticing a new program.
2. probe   -- each program's third turn, one at a time, diffing the engine's
              prefix-cache counters. Nothing else runs, so the delta belongs to
              that request.

Run it twice: once with EXECUTOR_KEEP=off, once with =on. That is the A/B.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import re
import statistics
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


def make_prefix(rng: random.Random, words: int, tag: str) -> str:
    body = " ".join(rng.choice(WORDS) for _ in range(words))
    return f"[{tag}] {body}"


def counters(client: httpx.Client, base: str) -> tuple[float, float]:
    text = client.get(base + "/metrics", timeout=20).text
    q = sum(float(m) for m in Q_RE.findall(text))
    h = sum(float(m) for m in H_RE.findall(text))
    return q, h


def ask(client: httpx.Client, prompt: str, program_id: str, max_tokens: int = 24) -> dict:
    body = {"model": MODEL, "prompt": prompt, "max_tokens": max_tokens, "temperature": 0.0}
    if program_id:
        body["program_id"] = program_id
    r = client.post(EXE + "/v1/completions", json=body, timeout=300)
    r.raise_for_status()
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="keep")
    ap.add_argument("--programs", type=int, default=10)
    ap.add_argument("--prefix-words", type=int, default=3000)
    ap.add_argument("--flood-tokens", type=int, default=250_000)
    ap.add_argument("--flood-words", type=int, default=3000)
    ap.add_argument("--flood-concurrency", type=int, default=4)
    ap.add_argument("--wait-s", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(f"{args.label}:{args.seed}")
    out = pathlib.Path("data")
    out.mkdir(exist_ok=True)

    with httpx.Client(headers={"content-type": "application/json"}) as client:
        health = client.get(EXE + "/healthz", timeout=20).json()
        keep = health.get("keep") or {}
        print(f"[keep-e2e] label={args.label} keep={keep}")

        # phase 0 -- settle: two turns each, so each program is a returning one
        prompts = {}
        for i in range(args.programs):
            pid = f"{args.label}-p{i}"
            prompts[pid] = make_prefix(rng, args.prefix_words, pid)
            for _ in range(2):
                ask(client, prompts[pid], pid)
        print(f"[keep-e2e] settled {len(prompts)} programs")

        # phase 1 -- flood straight at the engine (bypasses the executor)
        flood_started = time.time()
        sent = 0
        tokens = 0
        with httpx.Client(headers={"content-type": "application/json"}) as raw:
            while tokens < args.flood_tokens:
                batch = []
                for _ in range(args.flood_concurrency):
                    filler = make_prefix(rng, args.flood_words, f"filler{sent}")
                    batch.append(filler)
                    sent += 1
                    tokens += int(len(filler) / 3.6)
                for filler in batch:
                    raw.post(ENGINE + "/v1/completions",
                             json={"model": MODEL, "prompt": filler, "max_tokens": 2,
                                   "temperature": 0.0}, timeout=300)
        flood_seconds = time.time() - flood_started
        print(f"[keep-e2e] flooded {sent} filler requests (~{tokens} tokens) in {flood_seconds:.1f}s")

        if args.wait_s:
            time.sleep(args.wait_s)

        # phase 2 -- probe one at a time
        rows = []
        for pid, prompt in prompts.items():
            q0, h0 = counters(client, ENGINE)
            ask(client, prompt, pid, max_tokens=16)
            q1, h1 = counters(client, ENGINE)
            dq, dh = q1 - q0, h1 - h0
            rows.append({"program_id": pid, "queries": dq, "hits": dh,
                         "hit_rate": (dh / dq) if dq else 0.0})
        client.close  # noqa: B018 - keep the linter quiet about the scope

    rates = [r["hit_rate"] for r in rows]
    alive = sum(1 for r in rates if r > 0.5)
    health_after = httpx.get(EXE + "/healthz", timeout=20).json()
    summary = {
        "label": args.label,
        "keep_enabled": bool((health_after.get("keep") or {}).get("enabled")),
        "programs": args.programs,
        "prefix_words": args.prefix_words,
        "flood_tokens": args.flood_tokens,
        "flood_requests": sent,
        "flood_seconds": round(flood_seconds, 1),
        "hit_rate_median": round(statistics.median(rates), 4),
        "survivors": alive,
        "keep_refreshes": (health_after.get("keep") or {}).get("refreshes"),
        "keep_computed_tokens": (health_after.get("keep") or {}).get("computed_tokens"),
        "rows": rows,
    }
    with (out / "m11_keep_e2e.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
