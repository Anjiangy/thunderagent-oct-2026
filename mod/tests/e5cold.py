"""Cold-start mismatch: prime KV on the card that is NOT where TA will send it.

Two arms:
  free : prime half the programs on each card, then let TA place them by its own accounting.
  pin  : same priming, then pin every program to the card that already holds its KV.

The gap between the two arms is the value of "knowing where the KV is" -- which is
exactly what a migration decision can buy, and what TA cannot see.
"""
from __future__ import annotations

import json
import os
import random
import statistics
import time
import urllib.request

ARM = os.environ["ARM"]                 # free | pin
N = int(os.environ.get("N", 16))
WORDS = int(os.environ.get("WORDS", 5000))
TURNS = int(os.environ.get("TURNS", 8))
GAP = float(os.environ.get("GAP", 6))

A_EXE, B_EXE = "http://127.0.0.1:8101", "http://127.0.0.1:8102"
TA = os.environ.get("TA_URL", "http://127.0.0.1:9000")
MODEL = "Qwen2.5-14B-Instruct"
VOCAB = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
         "golf", "hotel", "india", "juliet", "kilo", "lima"]


def make_prefix(tag: str, words: int) -> str:
    rng = random.Random(zlib_crc(tag))
    return tag + " " + " ".join(rng.choice(VOCAB) for _ in range(words))


def zlib_crc(text: str) -> int:
    import zlib
    return zlib.crc32(text.encode())


def post(url: str, payload: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.loads(fh.read())


def main() -> None:
    pids = [f"{ARM}-p{i}" for i in range(N)]
    home = {p: (A_EXE if i % 2 == 0 else B_EXE) for i, p in enumerate(pids)}
    prompts = {p: make_prefix(p, WORDS) for p in pids}

    for p in pids:                                   # 1) put the KV on a chosen card
        post(f"{home[p]}/v1/completions",
             {"model": MODEL, "prompt": prompts[p], "max_tokens": 1,
              "temperature": 0.0, "program_id": p})

    if ARM == "pin":                                 # 2) tell the executor where it belongs
        for p in pids:
            post(f"{home[p]}/v1/programs/{p}/seed", {"instance": "a"})

    per_turn = []
    for t in range(1, TURNS + 1):
        row = []
        for p in pids:
            started = time.time()
            try:
                post(f"{TA}/v1/completions",
                     {"model": MODEL, "prompt": prompts[p] + f" turn{t}", "max_tokens": 1,
                      "temperature": 0.0, "program_id": p}, timeout=120)
                row.append(time.time() - started)
            except Exception as exc:                 # keep going, but say so
                print(f"  {p} failed: {exc!r}", flush=True)
        if not row:
            raise SystemExit(f"turn {t}: every request failed")
        per_turn.append(statistics.median(row))
        print(f"turn{t}: n={len(row)}/{N} p50={statistics.median(row):.2f}s", flush=True)
        time.sleep(GAP)

    print(json.dumps({"arm": ARM, "programs": N, "words": WORDS, "turns": TURNS,
                      "per_turn_p50": [round(x, 3) for x in per_turn],
                      "sum_p50": round(sum(per_turn), 3)}), flush=True)


if __name__ == "__main__":
    main()
