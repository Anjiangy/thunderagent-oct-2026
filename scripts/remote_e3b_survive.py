"""E3b: same program, same churn, two destinations with different residual room."""
import json, random, time, urllib.request
BASE="http://127.0.0.1:8110"; CAP=114176; MODEL="Qwen2.5-14B-Instruct"
WORDS=("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron "
       "pi rho sigma tau upsilon phi chi psi omega").split()
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
        k=min(3000,n-done); post(f"[{tag}] "+text(k,rng)); done+=k
def probe(prefix):
    q0,h0=metrics(); post(prefix); q1,h1=metrics()
    dq,dh=q1-q0,h1-h0
    return dq,dh,(dh/dq if dq else 0)
rng=random.Random(7)
prefix="[program-p] "+text(5000,rng)
out=[]
for name, fill, churn in (("roomy",0.00,0.35),("tight",0.45,0.35)):
    if fill: flood(int(fill*CAP), f"fill-{name}")
    post(prefix)                       # the move lands here
    flood(int(churn*CAP), f"churn-{name}")
    dq,dh,hit=probe(prefix)
    out.append({"dest":name,"fill":fill,"churn":churn,"dq":dq,"dh":dh,"hit":round(hit,4)})
    print(name,"dq=%d dh=%d hit=%.4f"%(dq,dh,hit),flush=True)
print(json.dumps(out))
