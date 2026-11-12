"""E10-4: how far is TA's bookkeeping from what the engine actually holds?

Drives N programs with long prefixes through TA, and after every turn records
TA's own estimate (/programs -> context_len, total_tokens) against the engine's
real KV usage (/metrics -> kv_cache_usage_perc x capacity).
"""
from __future__ import annotations
import json, os, random, time, urllib.request

TA = os.environ.get("TA_URL", "http://127.0.0.1:9001")
ENG = os.environ.get("ENG_URL", "http://127.0.0.1:8110")
MODEL = os.environ.get("E10_MODEL", "Qwen2.5-14B-Instruct")
PROGRAMS = int(os.environ.get("N", "6"))
WORDS = int(os.environ.get("WORDS", "3000"))
TURNS = int(os.environ.get("TURNS", "5"))
VOCAB = ("cache slate orchard lantern ripple meadow harbor velvet cipher nugget tundra "
         "bamboo cobalt ferry gable hollow islet jasper kestrel").split()

def get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())

def get_text(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode()

def post_json(url, payload, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json", "authorization": "Bearer x"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def engine_used():
    txt = get_text(ENG + "/metrics")
    cap = 0.0
    used = None
    running = 0.0
    for line in txt.splitlines():
        if line.startswith("vllm:cache_config_info"):
            lab = line.split("{", 1)[1].split("}", 1)[0]
            n = b = 0
            for kv in lab.split(","):
                if kv.startswith("num_gpu_blocks="):
                    n = int(float(kv.split("=", 1)[1].strip('"')))
                elif kv.startswith("block_size="):
                    b = int(float(kv.split("=", 1)[1].strip('"')))
            cap = n * b
        elif line.startswith("vllm:kv_cache_usage_perc"):
            used = float(line.rsplit(" ", 1)[1])
        elif line.startswith("vllm:num_requests_running"):
            running += float(line.rsplit(" ", 1)[1])
    return cap, (used or 0.0) * cap, running

def ta_view():
    try:
        d = get(TA + "/programs")
    except Exception:
        return {}
    progs = d.get("programs", d) if isinstance(d, dict) else {}
    out = {}
    if isinstance(progs, dict):
        for k, v in progs.items():
            if isinstance(v, dict):
                out[str(k)] = {"ctx": int(v.get("context_len") or 0),
                               "tot": int(v.get("total_tokens") or 0),
                               "backend": v.get("backend_url") or v.get("backend"),
                               "status": v.get("status")}
    return out

def main():
    rng = random.Random(5)
    prefixes = [" ".join(rng.choice(VOCAB) for _ in range(WORDS)) for _ in range(PROGRAMS)]
    rows = []
    for t in range(1, TURNS + 1):
        for i, pre in enumerate(prefixes):
            history = "" if t == 1 else " " + " ".join(f"<r{t-1}-{j}>" for j in range(80 * (t - 1)))
            body = {"model": MODEL, "messages": [{"role": "user", "content": pre + history}],
                    "max_tokens": 128, "temperature": 0.0, "ignore_eos": True,
                    "user": f"drift-p{i}", "program_id": f"drift-p{i}"}
            t0 = time.time()
            r = post_json(TA + "/v1/chat/completions", body)
            dt = time.time() - t0
            usage = r.get("usage") or {}
            time.sleep(1.0)
            cap, used, running = engine_used()
            view = ta_view()
            est_ctx = sum(v["ctx"] for v in view.values())
            est_tot = sum(v["tot"] for v in view.values())
            rows.append({"turn": t, "program": i, "dt": round(dt, 2),
                         "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                         "engine_cap": int(cap), "engine_used": int(used),
                         "engine_running": int(running),
                         "ta_programs": len(view), "ta_ctx_sum": est_ctx, "ta_tot_sum": est_tot,
                         "ta_ctx_sample": {k: v["ctx"] for k, v in list(view.items())[:4]}})
        print(json.dumps({"turn_done": t, "engine_used": rows[-1]["engine_used"],
                          "ta_ctx_sum": rows[-1]["ta_ctx_sum"]}, ensure_ascii=False), flush=True)
    path = os.environ.get("OUT", "/root/e10/ta_drift.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("WROTE", path, len(rows))

if __name__ == "__main__":
    main()