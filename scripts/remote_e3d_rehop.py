"""E3d: cost of the second hop. Components on one card: cold prefill vs warm hit."""
import json, random, time, urllib.request
BASE="http://127.0.0.1:8110"; CAP=114176; MODEL="Qwen2.5-14B-Instruct"
WORDS=("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho "
       "sigma tau upsilon phi chi psi omega").split()
def post(p,mt=1):
    b=json.dumps({"model":MODEL,"prompt":p,"max_tokens":mt,"temperature":0.0}).encode()
    req=urllib.request.Request(BASE+"/v1/completions",b,{"content-type":"application/json"})
    t=time.time()
    with urllib.request.urlopen(req,timeout=900) as r: d=json.loads(r.read())
    return time.time()-t, d.get("usage",{})
def text(n,rng): return " ".join(rng.choice(WORDS) for _ in range(int(n/1.3)))
def metrics():
    with urllib.request.urlopen(BASE+"/metrics",timeout=30) as r: t=r.read().decode()
    q=h=0
    for l in t.splitlines():
        if l.startswith("vllm:prefix_cache_queries_total"): q+=int(float(l.rsplit(" ",1)[1]))
        elif l.startswith("vllm:prefix_cache_hits_total"): h+=int(float(l.rsplit(" ",1)[1]))
    return q,h
def flood(n,tag):
    rng=random.Random(tag); done=0
    while done<n:
        k=min(4000,n-done); post(f"[{tag}] "+text(k,rng)); done+=k
rng=random.Random(21)
prefix="[program-r] "+text(5000,rng)
out={}
t1,u1=post(prefix); out["cold_prefill_s"]=round(t1,3); out["tokens"]=u1.get("prompt_tokens")
t2,_=post(prefix); out["warm_hit_s"]=round(t2,3)
flood(int(1.25*CAP),"kill-r")            # evict it (E3c: 1.20x kills)
q0,h0=metrics(); t3,_=post(prefix); q1,h1=metrics()
out["after_evict_prefill_s"]=round(t3,3); out["after_evict_dq"]=q1-q0; out["after_evict_dh"]=h1-h0
out["pull_cost_est_s"]=round(0.61*out["cold_prefill_s"],3)   # measured cross-container ratio
out["one_hop_s"]=round(0.23+out["pull_cost_est_s"],3)        # capture + pull
out["two_hop_intact_s"]=round(2*(0.23+out["pull_cost_est_s"]),3)
out["two_hop_broken_s"]=round(0.23+out["pull_cost_est_s"]+out["cold_prefill_s"],3)
print(json.dumps(out))
