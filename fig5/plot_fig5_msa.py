import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rows = list(csv.DictReader(open(r"E:\studyfiles\dsh\Thunderagent\fig5_msa_results.csv", encoding="utf-8-sig")))
def grp(mode):
    d = {}
    for r in rows:
        if r["mode"] == mode:
            d[int(r["N"])] = r
    return d

vllm = grp("roundrobin")
ta = grp("single")
Ns = sorted(vllm.keys())

vllm_hit = [float(vllm[n]["hit_rate_pct"]) for n in Ns]
ta_hit   = [float(ta[n]["hit_rate_pct"]) for n in Ns]
vllm_spm = [float(vllm[n]["step_per_min"]) for n in Ns]
ta_spm   = [float(ta[n]["step_per_min"]) for n in Ns]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 5.2))

ax1.plot(Ns, vllm_hit, "o-", color="#c0392b", lw=2, ms=7, label="vLLM (round-robin baseline)")
ax1.plot(Ns, ta_hit,   "s-", color="#1f77b4", lw=2, ms=7, label="ThunderAgent (affinity + throttling)")
ax1.axhline(60, color="gray", ls="--", lw=1, alpha=0.6)
ax1.text(Ns[0], 61.5, "60% line", fontsize=8, color="gray")
ax1.set_xlabel("Concurrency (programs, N)")
ax1.set_ylabel("KV prefix-cache hit rate (%)")
ax1.set_title("KV cache hit rate  (vLLM collapses, TA holds)")
ax1.set_ylim(0, 100)
ax1.grid(alpha=0.3)
ax1.legend(fontsize=9, loc="center right")

ax2.plot(Ns, vllm_spm, "o-", color="#c0392b", lw=2, ms=7, label="vLLM (round-robin)")
ax2.plot(Ns, ta_spm,   "s-", color="#1f77b4", lw=2, ms=7, label="ThunderAgent")
ax2.set_xlabel("Concurrency (programs, N)")
ax2.set_ylabel("Throughput (step / min)")
ax2.set_title("Throughput  (TA stays ahead at high N)")
ax2.grid(alpha=0.3)
ax2.legend(fontsize=9, loc="upper left")

n93 = max(Ns)
sp = ta_spm[-1] / vllm_spm[-1]
hr = ta_hit[-1] / vllm_hit[-1]
ax1.annotate(f"N={n93}: TA {ta_hit[-1]:.0f}% vs vLLM {vllm_hit[-1]:.1f}%  ({hr:.0f}x)",
             xy=(n93, vllm_hit[-1]), xytext=(n93-24, 15),
             fontsize=9, color="#1f77b4",
             arrowprops=dict(arrowstyle="->", color="#1f77b4"))
ax2.annotate(f"N={n93}: TA {ta_spm[-1]:.0f} vs vLLM {vllm_spm[-1]:.0f} step/min  ({sp:.2f}x)",
             xy=(n93, ta_spm[-1]), xytext=(n93-26, ta_spm[-1]+2.5),
             fontsize=9, color="#1f77b4",
             arrowprops=dict(arrowstyle="->", color="#1f77b4"))

fig.suptitle("ThunderAgent Fig.5 reproduction  (mini-swe-agent load, Qwen2.5-14B, 2x Ascend 910B, step_limit=30)",
             fontsize=12, y=1.02)
fig.tight_layout()
out = r"E:\studyfiles\dsh\Thunderagent\fig5_msa_reproduction.png"
fig.savefig(out, dpi=130, bbox_inches="tight")
print("saved", out)
print("hit  vLLM:", vllm_hit)
print("hit  TA  :", ta_hit)
print("spm  vLLM:", vllm_spm)
print("spm  TA  :", ta_spm)
