"""E3c: the newest program survives any churn below capacity; churn above capacity kills it."""
import json, random, urllib.request
BASE="http://127.0.0.1:8110"; CAP=114176; MODEL="Qwen2.5-14B-Instruct"
WORDS=("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho "
       "sigma tau upsilon phi chi psi omega").split()
def metrics():
    with urllib.request.urlopen(BASE+"/metrics",timeout=30) as r: t=r.read().decode()
    q=h=0
    for l in t.splitlines():
        if l.startswith("vllm:prefix_cache_queries_total"): q+=int(float(l.rsplit(" ",1)[1]))
        elif l.startswith("vllm:prefix_cache_hits_total"): h+=int(float(l.rsplit(" ",1)[1]))
    return q,h
def post(p,mt=1):
    b=json.dumps({"model":MODEL,"prompt":p,"max_tokens":mt,"temperature":0.0}).encode()
    req=urllib.request.Request(BASE+"/v1/completions",b,{"content-type":"application/json"})
    with urllib.request.urlopen(req,timeout=900) as r: r.read()
def text(n,rng): return " ".join(rng.choice(WORDS) for _ in range(int(n/1.3)))
def flood(n,tag):
    rng=random.Random(tag); done=0
    while done<n:
        k=min(4000,n-done); post(f"[{tag}] "+text(k,rng)); done+=k
rng=random.Random(11)
prefix="[program-q] "+text(5000,rng)
out=[]
for frac in (0.55, 0.95, 1.20):
    post(prefix)                       # land on this card (newest block group)
    flood(int(frac*CAP), f"c-{frac}")
    q0,h0=metrics(); post(prefix); q1,h1=metrics()
    dq,dh=q1-q0,h1-h0
    hit=dh/dq if dq else 0.0
    out.append({"churn_frac":frac,"dq":dq,"dh":dh,"hit":round(hit,4)})
    print("churn=%.2f dq=%d dh=%d hit=%.4f"%(frac,dq,dh,hit),flush=True)
print(json.dumps(out))
