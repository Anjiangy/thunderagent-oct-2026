"""E10-1: prefill is a small slice of an agent step on this stack."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = [r for r in csv.DictReader((ROOT / "data" / "e10_prefill_share.csv").open(encoding="utf-8-sig"))]
for r in rows:
    for k in ("conc", "prompt_tokens", "out_req", "ctx_req"):
        r[k] = int(r[k])
    for k in ("ttft_s", "step_s", "prefill_share", "decode_tps", "server_prefill_s"):
        r[k] = float(r[k])

fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.6))

ax = axes[0]
style = {128: ("-", "o"), 512: ("--", "s")}
colors = {2000: "#94a3b8", 4000: "#1f6feb", 8000: "#b91c1c"}
for out in (128, 512):
    for ctx in (2000, 4000, 8000):
        pts = sorted([r for r in rows if r["out_req"] == out and r["ctx_req"] == ctx],
                     key=lambda r: r["conc"])
        ax.plot([p["conc"] for p in pts], [p["prefill_share"] * 100 for p in pts],
                style[out][0], marker=style[out][1], color=colors[ctx], ms=6,
                label=f"{ctx//1000}k ctx / {out} out")
ax.axhline(10, color="#111", ls=":", lw=1.3)
ax.text(1.05, 11.5, "10% decision line", fontsize=8.5)
ax.set_xscale("log"); ax.set_xticks([1, 8, 32]); ax.set_xticklabels(["1", "8", "32"])
ax.set_xlabel("concurrent requests"); ax.set_ylabel("prefill share of one step (%)")
ax.set_title("Prefill is 0.5-6% of a step, except when the queue dominates")
ax.grid(alpha=0.25); ax.legend(fontsize=7, ncol=2, loc="upper left")

ax = axes[1]
sub = [r for r in rows if r["out_req"] == 512 and r["conc"] == 1]
lbl = [f"{r['ctx_req']//1000}k" for r in sub]
pref = [r["server_prefill_s"] for r in sub]
dec = [r["step_s"] - r["ttft_s"] for r in sub]
x = range(len(sub))
ax.bar(x, pref, color="#1f6feb", label="prefill compute (server)")
ax.bar(x, dec, bottom=pref, color="#cbd5e1", label="decode (512 tokens)")
for i, (p, d) in enumerate(zip(pref, dec)):
    ax.text(i + 0.28, p + 0.4, f"{p:.2f}s", ha="left", va="bottom", fontsize=8.5, color="#1f6feb")
    ax.text(i, p + d / 2, f"{d:.1f}s", ha="center", va="center", fontsize=9, color="#334155")
ax.set_xticks(list(x)); ax.set_xticklabels(lbl)
ax.set_xlabel("prompt length"); ax.set_ylabel("seconds per step")
ax.set_title("The step is decode-bound: ~10 tok/s, 0.2-0.5 s of prefill")
ax.grid(axis="y", alpha=0.25); ax.legend(fontsize=8, loc="upper left")

fig.suptitle("E10-1  single NPU, Qwen2.5-14B, greedy, 128/512 output tokens", fontsize=11)
fig.tight_layout()
out = ROOT / "data" / "e10_prefill_share.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
