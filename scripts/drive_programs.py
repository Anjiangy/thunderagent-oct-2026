"""Push N long-prefix programs through TA (for the overcommit watcher)."""
from __future__ import annotations
import json, os, random, time, urllib.request

TA = os.environ.get("TA_URL", "http://127.0.0.1:9001")
MODEL = os.environ.get("MODEL", "Qwen2.5-14B-Instruct")
N = int(os.environ.get("N", "10"))
WORDS = int(os.environ.get("WORDS", "6000"))
TURNS = int(os.environ.get("TURNS", "2"))
VOCAB = ("cache slate orchard lantern ripple meadow harbor velvet cipher nugget tundra "
         "bamboo cobalt ferry gable hollow islet jasper kestrel").split()

def post(payload):
    req = urllib.request.Request(TA + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json", "authorization": "Bearer x"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode()), time.time() - t0

def main():
    rng = random.Random(3)
    pre = [" ".join(rng.choice(VOCAB) for _ in range(WORDS)) for _ in range(N)]
    for t in range(1, TURNS + 1):
        for i, p in enumerate(pre):
            body = {"model": MODEL, "messages": [{"role": "user", "content": p}],
                    "max_tokens": 64, "temperature": 0.0, "ignore_eos": True,
                    "program_id": f"drv-{i}"}
            try:
                r, dt = post(body)
                u = r.get("usage") or {}
                print(json.dumps({"t": t, "i": i, "dt": round(dt, 1),
                                  "pt": u.get("prompt_tokens")}), flush=True)
            except Exception as e:
                print(json.dumps({"t": t, "i": i, "err": str(e)[:80]}), flush=True)

if __name__ == "__main__":
    main()