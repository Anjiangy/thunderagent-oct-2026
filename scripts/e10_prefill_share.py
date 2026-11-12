"""E10-1: how much of one agent step is prefill?

For each (context, output, concurrency) cell: fire `conc` streaming chat requests,
measure time-to-first-token (prefill proxy) and total wall time (one step), and
also diff the engine's own prefill/decode counters.
"""
from __future__ import annotations
import asyncio, json, statistics, sys, urllib.request
import httpx

BASE = "http://127.0.0.1:8110"
MODEL = "Qwen2.5-14B-Instruct"
FILLER = ("import os import sys def main build task context file buffer line "
          "return value result handler dataset token prefix cache block engine ")
KEYS = ("vllm:time_to_first_token_seconds", "vllm:request_prefill_time_seconds",
        "vllm:request_decode_time_seconds", "vllm:e2e_request_latency_seconds",
        "vllm:num_requests_running")


def metrics() -> dict:
    out = {}
    try:
        body = urllib.request.urlopen(BASE + "/metrics", timeout=10).read().decode()
    except Exception:
        return out
    for line in body.splitlines():
        if not line.startswith("vllm:") or " " not in line:
            continue
        name = line.split("{")[0].split(" ")[0]
        for k in KEYS:
            if name.startswith(k):
                try:
                    out[name] = out.get(name, 0.0) + float(line.rsplit(" ", 1)[1])
                except ValueError:
                    pass
    return out


def ctx(n_tokens: int, salt: str) -> str:
    per = 1.3                      # ~1.3 tokens per filler word for this vocabulary
    words = int(n_tokens / per)
    return (f"[{salt}] " + (FILLER * (words // len(FILLER.split()) + 2)))[: words * 8]


async def one(client: httpx.AsyncClient, n_in: int, n_out: int, tag: str) -> dict:
    payload = {"model": MODEL, "max_tokens": n_out, "temperature": 0.0,
               "ignore_eos": True, "stream": True,
               "stream_options": {"include_usage": True},
               "messages": [{"role": "user", "content": ctx(n_in, tag)}]}
    t0 = asyncio.get_running_loop().time()
    t_first = None
    usage = {}
    async with client.stream("POST", BASE + "/v1/chat/completions", json=payload) as r:
        async for line in r.aiter_lines():
            if not line.startswith("data: "):
                continue
            body = line[6:]
            if body == "[DONE]":
                break
            d = json.loads(body)
            if d.get("usage"):
                usage = d["usage"]
            if t_first is None and d.get("choices") and d["choices"][0].get("delta"):
                if d["choices"][0]["delta"].get("content"):
                    t_first = asyncio.get_running_loop().time() - t0
    t_end = asyncio.get_running_loop().time() - t0
    return {"t_first": t_first if t_first is not None else t_end, "t_end": t_end,
            "n_in": usage.get("prompt_tokens", 0), "n_out": usage.get("completion_tokens", 0)}


async def cell(n_in: int, n_out: int, conc: int, timeout: float = 900.0) -> dict:
    before = metrics()
    async with httpx.AsyncClient(timeout=timeout) as client:
        t0 = asyncio.get_running_loop().time()
        runs = await asyncio.gather(*[one(client, n_in, n_out, f"c{conc}") for _ in range(conc)])
        wall = asyncio.get_running_loop().time() - t0
    after = metrics()
    true_prefill = None
    for k in ("vllm:request_prefill_time_seconds_sum",):
        if k in after:
            true_prefill = (after[k] - before.get(k, 0.0)) / conc
    tf = statistics.median(r["t_first"] for r in runs)
    te = statistics.median(r["t_end"] for r in runs)
    return {"ctx_req": n_in, "out_req": n_out, "conc": conc,
            "prompt_tokens": int(statistics.median(r["n_in"] for r in runs)),
            "completion_tokens": int(statistics.median(r["n_out"] for r in runs)),
            "ttft_s": round(tf, 3), "step_s": round(te, 3),
            "prefill_share": round(tf / te, 4) if te else None,
            "decode_tps": round((te - tf) and (statistics.median(r["n_out"] for r in runs) / (te - tf)), 1),
            "wall_s": round(wall, 2),
            "server_prefill_s": round(true_prefill, 3) if true_prefill is not None else None}


async def main() -> None:
    rows = []
    for n_in in (2000, 4000, 8000):
        for n_out in (128, 512):
            for conc in (1, 8, 32):
                if conc > 1 and n_in * conc > 3 * 114176:
                    rows.append({"ctx_req": n_in, "out_req": n_out, "conc": conc,
                                 "prompt_tokens": None, "ttft_s": None, "step_s": None,
                                 "prefill_share": None, "note": "skipped: over cluster KV"})
                    continue
                row = await cell(n_in, n_out, conc)
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    with open("/root/e10/prefill_share.json", "w") as fh:
        json.dump(rows, fh, indent=2)
    print("DONE", len(rows))


asyncio.run(main())
