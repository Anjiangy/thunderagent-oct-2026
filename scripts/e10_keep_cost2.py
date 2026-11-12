"""E10-2b: keep loop cost/benefit under identical churn (all arms same pressure).

Arms: off | naive (every 2 s) | gated (interval = resident / observed churn rate).
Churn runs in background for every arm: prefill-only noise, target 1.4x card capacity.
"""
from __future__ import annotations
import json, os, random, threading, time, urllib.request

BASE = os.environ.get("E10_BASE", "http://127.0.0.1:8110")
MODEL = os.environ.get("E10_MODEL", "Qwen2.5-14B-Instruct")
PROGRAMS = int(os.environ.get("E10_PROGRAMS", "4"))
PREFIX_WORDS = int(os.environ.get("E10_WORDS", "3500"))
TURNS = int(os.environ.get("E10_TURNS", "4"))
GAP = float(os.environ.get("E10_GAP", "20"))
ARM = os.environ.get("E10_ARM", "off")
CHURN_MULT = float(os.environ.get("E10_CHURN_MULT", "1.4"))
CAP = 892 * 128
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
    q = h = 0.0
    for line in txt.splitlines():
        if line.startswith("vllm:prefix_cache_queries_total"):
            q += float(line.rsplit(" ", 1)[1])
        elif line.startswith("vllm:prefix_cache_hits_total"):
            h += float(line.rsplit(" ", 1)[1])
    return q, h

def make_prefix(rng, n):
    return " ".join(rng.choice(WORDS) for _ in range(n))

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

class Churn:
    def __init__(self, target):
        self.target = target
        self.sent = 0
        self.samples = []          # (t, sent)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.threads = []

    def _worker(self):
        rng = random.Random(hash(os.getpid()) + threading.get_ident())
        while not self.stop.is_set():
            with self.lock:
                if self.sent >= self.target:
                    return
            try:
                _, pt, _ = chat("noise " + make_prefix(rng, 1200), 1)
            except Exception:
                continue
            with self.lock:
                self.sent += pt
                self.samples.append((time.time(), self.sent))

    def start(self, n=3):
        for _ in range(n):
            th = threading.Thread(target=self._worker, daemon=True)
            th.start(); self.threads.append(th)

    def rate(self, window=15.0):
        """Recent rate, falling back to the run-wide average until a window exists."""
        t = time.time()
        with self.lock:
            pts = [s for s in self.samples if s[0] >= t - window]
            first, last = (self.samples[0] if self.samples else None), (self.samples[-1] if self.samples else None)
            total = self.sent
        if len(pts) >= 2:
            return (pts[-1][1] - pts[0][1]) / max(1e-6, pts[-1][0] - pts[0][0])
        if first and last and last[0] - first[0] > 1.0:
            return total / max(1e-6, last[0] - first[0])
        return 0.0

def main():
    rng = random.Random(11)
    prefixes = [make_prefix(rng, PREFIX_WORDS) for _ in range(PROGRAMS)]
    q0, h0 = metrics()
    t_start = time.time()
    churn = Churn(int(CHURN_MULT * CAP))
    churn.start(3)
    turns, keeps, keep_s = [], 0, 0.0
    resident = 0
    for t in range(TURNS):
        for pre in prefixes:
            prompt = pre + ("" if t == 0 else " " + " ".join([f"<p{t}x{j}>" for j in range(60 * t)]))
            dt, pt, _ = chat(prompt, 128, ignore_eos=True)
            turns.append(dt); resident = resident * 0.5 + pt * 0.5 if resident else pt
        if t == TURNS - 1:
            break
        gap_end = time.time() + GAP
        if ARM == "naive":
            interval = 2.0
        elif ARM == "gated":
            r = churn.rate()
            interval = max(2.0, resident / (0.5 * r)) if r > 100 else 20.0
        else:
            interval = None
        nxt = time.time() + (interval or 1e9)
        while time.time() < gap_end:
            if interval and time.time() >= nxt:
                for pre in prefixes:
                    try:
                        kt, _, _ = chat(pre + " keep", 1)
                        keeps += 1; keep_s += kt
                    except Exception:
                        pass
                nxt = time.time() + interval
            time.sleep(0.2)
    churn.stop.set()
    q1, h1 = metrics()
    dq, dh = int(q1 - q0), int(h1 - h0)
    turns_sorted = sorted(turns)
    row = {"arm": ARM, "programs": PROGRAMS, "words": PREFIX_WORDS, "turns": TURNS, "gap": GAP,
           "wall_s": round(time.time() - t_start, 1), "churn_tokens": churn.sent,
           "churn_mult": round(churn.sent / CAP, 3), "dq": dq, "dh": dh,
           "hit_all": round(dh / dq, 4) if dq else 0.0,
           "keep_requests": keeps, "keep_s": round(keep_s, 1),
           "resident_tokens": int(resident),
           "p50_step_s": round(turns_sorted[len(turns_sorted) // 2], 3),
           "max_step_s": round(turns_sorted[-1], 3),
           "sum_step_s": round(sum(turns), 1)}
    print(json.dumps(row, ensure_ascii=False))

if __name__ == "__main__":
    main()