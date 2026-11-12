"""Does the engine evict blocks that belong to an idle program, and can a cheap
refresh keep them alive?

Single card. Three phases:
  A  settle   -- R residents each take two turns, so their prefixes are cached
  B  pressure -- unrelated filler requests, sized to overflow the card
  C  probe    -- each resident takes its third turn *alone*; we diff the cache
                 counters around that single request, so the hit rate is not
                 contaminated by anything else

Two knobs: how much filler (--pressure-tokens) and how long the residents stay
idle before the probe (--gap). One remedy: --keep-every N seconds, which sends a
one-token refresh of each resident's prefix while the pressure is on.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

WORDS = (
    "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike "
    "november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu "
    "amber basalt cobalt dune ember fjord gneiss harbor isthmus juniper kestrel lagoon mesa "
    "nimbus obsidian prairie quill ridge summit tundra umbra vertex willow xenon yarrow zephyr"
).split()


def make_prefix(rng: random.Random, words: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(words))


def turn_prompt(prefix: str, turn: int) -> str:
    """Deterministic conversation so a refresh can reproduce the exact prefix."""
    lines = [prefix, "", "=== session log ==="]
    for i in range(1, turn):
        lines.append(f"step {i}: read the file, run the tests, they passed")
    return "\n".join(lines)


def read_counters(base: str) -> tuple[float, float]:
    text = httpx.get(f"{base}/metrics", timeout=30).text
    q = h = 0.0
    for line in text.splitlines():
        if line.startswith("vllm:prefix_cache_queries_total"):
            q = float(line.rsplit(" ", 1)[1])
        elif line.startswith("vllm:prefix_cache_hits_total"):
            h = float(line.rsplit(" ", 1)[1])
    return q, h


def read_capacity(base: str) -> tuple[int, int]:
    text = httpx.get(f"{base}/metrics", timeout=30).text
    for line in text.splitlines():
        if line.startswith("vllm:cache_config_info"):
            bs = int(re.search(r'block_size="(\d+)"', line).group(1))
            nb = int(re.search(r'num_gpu_blocks="(\d+)"', line).group(1))
            return bs, nb
    raise SystemExit("no cache_config_info in /metrics")


def complete(base: str, model: str, prompt: str, max_tokens: int) -> dict:
    payload = {"model": model, "prompt": prompt, "max_tokens": max_tokens, "temperature": 0.0}
    r = httpx.post(f"{base}/v1/completions", json=payload, timeout=600)
    r.raise_for_status()
    return r.json()


def complete_measured(base: str, model: str, prompt: str, max_tokens: int):
    q0, h0 = read_counters(base)
    body = complete(base, model, prompt, max_tokens)
    q1, h1 = read_counters(base)
    return q1 - q0, h1 - h0, body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8110")
    ap.add_argument("--model", default="Qwen2.5-14B-Instruct")
    ap.add_argument("--residents", type=int, default=10)
    ap.add_argument("--prefix-words", type=int, default=3000)
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--gap", type=float, default=30.0)
    ap.add_argument("--pressure-tokens", type=int, default=0,
                    help="tokens of unrelated filler to push through the card; 0 = no pressure")
    ap.add_argument("--filler-words", type=int, default=3000)
    ap.add_argument("--filler-concurrency", type=int, default=4)
    ap.add_argument("--keep-every", type=float, default=0.0,
                    help="seconds between refreshes of every resident; 0 = no keep")
    ap.add_argument("--keep-max-tokens", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", default="data/m10_residency.jsonl")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    bs, nb = read_capacity(args.base)
    capacity = bs * nb
    print(f"[setup] block_size={bs} blocks={nb} capacity={capacity} tokens", flush=True)
    print(f"[setup] residents={args.residents} prefix_words={args.prefix_words} "
          f"turn_words~{args.prefix_words}", flush=True)

    prefixes = {}
    for i in range(args.residents):
        prefixes[f"p{i:02d}"] = make_prefix(rng, args.prefix_words)

    # ---- phase A: settle -------------------------------------------------
    t0 = time.time()
    for pid, prefix in prefixes.items():
        for turn in (1, 2):
            complete(args.base, args.model, turn_prompt(prefix, turn), 8)
    settle_s = time.time() - t0
    print(f"[A] settled {args.residents} residents in {settle_s:.1f}s", flush=True)

    stop = threading.Event()
    keep_calls = 0
    keep_tokens = 0

    # ---- keep thread (starts before pressure so it competes with filler) --
    def keep_loop():
        nonlocal keep_calls, keep_tokens
        while not stop.is_set():
            for prefix in list(prefixes.values()):
                if stop.is_set():
                    return
                try:
                    q, h, _ = complete_measured(args.base, args.model, turn_prompt(prefix, 2),
                                                args.keep_max_tokens)
                    keep_calls += 1
                    keep_tokens += int(q)
                except Exception as exc:  # noqa: BLE001
                    print(f"[keep] failed: {exc}", flush=True)
            stop.wait(args.keep_every)

    keep_thread = None
    if args.keep_every > 0:
        keep_thread = threading.Thread(target=keep_loop, daemon=True)
        keep_thread.start()
        print(f"[keep] refreshing every {args.keep_every}s", flush=True)

    # ---- phase B: pressure ----------------------------------------------
    t1 = time.time()
    filler_sent = 0
    if args.pressure_tokens > 0:
        per_filler = args.filler_words  # words ~= tokens for this filler
        batches = max(1, args.pressure_tokens // max(1, per_filler))

        def one(_):
            fprefix = make_prefix(rng, args.filler_words)
            try:
                complete(args.base, args.model, fprefix, 4)
                return True
            except Exception as exc:  # noqa: BLE001
                print(f"[filler] failed: {exc}", flush=True)
                return False

        with ThreadPoolExecutor(max_workers=args.filler_concurrency) as pool:
            for ok in pool.map(one, range(batches)):
                filler_sent += 1 if ok else 0
    pressure_s = time.time() - t1
    print(f"[B] filler requests={filler_sent} pressure={pressure_s:.1f}s "
          f"(~{filler_sent * args.filler_words} tokens)", flush=True)

    # ---- idle gap --------------------------------------------------------
    if args.gap > 0:
        time.sleep(args.gap)
        print(f"[gap] idled {args.gap}s", flush=True)

    stop.set()
    if keep_thread:
        keep_thread.join(timeout=5)

    # ---- phase C: probe --------------------------------------------------
    rows = []
    for pid, prefix in prefixes.items():
        q, h, _ = complete_measured(args.base, args.model, turn_prompt(prefix, args.turns), 8)
        hit = (h / q) if q else 0.0
        rows.append({"program": pid, "queries": q, "hits": h, "hit_rate": round(hit, 4)})
        print(f"[C] {pid}: queries={q:.0f} hits={h:.0f} hit_rate={hit:.3f}", flush=True)

    hits = [r["hit_rate"] for r in rows]
    summary = {
        "label": args.label,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "capacity_tokens": capacity,
        "residents": args.residents,
        "prefix_words": args.prefix_words,
        "turns": args.turns,
        "gap_s": args.gap,
        "pressure_tokens_target": args.pressure_tokens,
        "filler_requests": filler_sent,
        "keep_every_s": args.keep_every,
        "keep_calls": keep_calls,
        "keep_tokens": keep_tokens,
        "settle_s": round(settle_s, 1),
        "pressure_s": round(pressure_s, 1),
        "hit_median": round(statistics.median(hits), 4),
        "hit_mean": round(statistics.mean(hits), 4),
        "hit_min": round(min(hits), 4),
        "survivors": sum(1 for x in hits if x > 0.5),
        "per_program": rows,
    }
    with open(args.out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print("[summary] " + json.dumps({k: v for k, v in summary.items() if k != "per_program"},
                                   ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
