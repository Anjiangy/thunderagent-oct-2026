"""E10-2: is a *gated* keep loop cheaper than no keep at all?

One card, synthetic long sessions + background churn (prefill-only noise).
Three arms: off / naive keep every 2 s / gated keep (size + churn-based interval).
"""
from __future__ import annotations
import json, math, os, random, threading, time, urllib.request

BASE = os.environ.get("E10_BASE", "http://127.0.0.1:8110")
MODEL = os.environ.get("E10_MODEL", "Qwen2.5-14B-Instruct")
PROGRAMS = int(os.environ.get("E10_PROGRAMS", "6"))
PREFIX_WORDS = int(os.environ.get("E10_WORDS", "3500"))
TURNS = int(os.environ.get("E10_TURNS", "6"))
GAP = float(os.environ.get("E10_GAP", "25"))
ARM = os.environ.get("E10_ARM", "off")          # off | naive | gated
WORDS = ("cache slate orchard lantern ripple meadow harbor velvet cipher nugget "
         "tundra bamboo cobalt ferry gable hollow islet jasper kestrel").split()

def post(path, payload, timeout=180):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json", "authorization": "Bearer x"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def metrics():
    with urllib.request.urlopen(BASE + "/metrics", timeout=20) as r:
        txt = r.read().decode()
    out = {}
    for line in txt.splitlines():
        if line.startswith("vllm:prefix_cache_queries_total"):
            out["q"] = out.get("q", 0.0) + float(line.rsplit(" ", 1)[1])
        elif line.startswith("vllm:prefix_cache_hits_total"):
            out["h"] = out.get("h", 0.0) + float(line.rsplit(" ", 1)[1])
    return out

def make_prefix(rng, words):
    return " ".join(rng.choice(WORDS) for _ in range(words))

def chat(prompt, maxtok, ignore_eos=False):
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": maxtok, "temperature": 0.0}
    if ignore_eos:
        body["ignore_eos"] = True
    t0 = time.time()
    r = post("/v1/chat/completions", body)
    dt = time.time() - t0
    u = r.get("usage") or {}
    return dt, int(u.get("prompt_tokens") or 0), r

def churn(stop, tokens_target, state):
    """prefill-only noise: 1500-token prompts, max_tokens=1, 3 threads."""
    rng = random.Random(7)
    sent = 0
    while not stop.is_set() and sent < tokens_target:
        prompt = "noise " + make_prefix(rng, 1200)
        try:
            _, pt, _ = chat(prompt, 1)
            sent += pt
        except Exception:
            pass
        state["noise_tokens"] = sent

def main():
    rng = random.Random(11)
    prefixes = [make_prefix(rng, PREFIX_WORDS) for _ in range(PROGRAMS)]
    m0 = metrics()
    t_start = time.time()
    prog_q = prog_h = 0
    turns = []
    state = {}
    stop = threading.Event()
    churn_total = int(1.4 * 892 * 128)      # ~1.4x card capacity
    threads = []
    if ARM != "off":
        for _ in range(3):
            th = threading.Thread(target=churn, args=(stop, churn_total // 3, state), daemon=True)
            th.start(); threads.append(th)

    # per-program context growth: turn k sends prefix + k*reply-so-far
    keep_count = 0
    keep_time = 0.0
    for t in range(TURNS):
        for i, pre in enumerate(prefixes):
            prompt = pre + ("" if t == 0 else " " + " ".join([f"<prev{t}x{j}>" for j in range(60 * t)]))
            dt, pt, _ = chat(prompt, 128, ignore_eos=True)
            prog_q += pt
            turns.append({"turn": t, "prog": i, "pt": pt, "dt": dt})
        if t == TURNS - 1:
            break
        # gap with churn; keep loop runs inside it
        gap_end = time.time() + GAP
        if ARM == "naive":
            interval = 2.0
        elif ARM == "gated":
            # interval = resident tokens / churn rate (tokens per second), floored at 2 s
            resident = sum(x["pt"] for x in turns[-PROGRAMS:])
            rate = max(1.0, (state.get("noise_tokens", 0) or 1) / max(1.0, time.time() - t_start))
            interval = max(2.0, resident / (0.5 * rate))
        else:
            interval = None
        next_keep = time.time() + (interval or 1e9)
        while time.time() < gap_end:
            if interval and time.time() >= next_keep:
                for pre in prefixes:
                    try:
                        kt, kpt, _ = chat(pre + " keep", 1)
                        keep_count += 1; keep_time += kt
                    except Exception:
                        pass
                next_keep = time.time() + interval
            time.sleep(0.2)

    stop.set()
    m1 = metrics()
    dq = int(m1["q"] - m0["q"]); dh = int(m1["h"] - m0["h"])
    prog_hits = None
    wall = time.time() - t_start
    dts = sorted(x["dt"] for x in turns)
    p50 = dts[len(dts) // 2]
    row = {"arm": ARM, "programs": PROGRAMS, "words": PREFIX_WORDS, "turns": TURNS, "gap": GAP,
           "wall_s": round(wall, 1), "dq": dq, "dh": dh, "hit": round(dh / dq, 4) if dq else 0.0,
           "prog_tokens": prog_q, "keep_requests": keep_count, "keep_s": round(keep_time, 1),
           "p50_step_s": round(p50, 3), "noise_tokens": state.get("noise_tokens", 0)}
    print(json.dumps(row, ensure_ascii=False))

if __name__ == "__main__":
    main()
