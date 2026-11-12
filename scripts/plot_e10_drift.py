"""E10-4/5: what TA believes vs what the engine reports."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = [r for r in csv.DictReader((ROOT / "data" / "e10_ta_drift.csv").open(encoding="utf-8-sig"))]
turn = [int(r["turn"]) for r in rows]
actual = [int(r["actual_prompt"]) for r in rows]
ctx = [int(r["ta_context_len"]) for r in rows]
ratio = [float(r["ratio"]) for r in rows]

fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.5))

ax = axes[0]
ax.plot(turn, ctx, "-o", color="#b91c1c", label="TA context_len (char-based)")
ax.plot(turn, actual, "-s", color="#1f6feb", label="real prompt tokens")
for t, r in zip(turn, ratio):
    ax.annotate(f"{r:.1f}x", (t, ctx[t - 1]), textcoords="offset points", xytext=(0, 8),
                ha="center", fontsize=8, color="#b91c1c")
ax.set_xlabel("turn"); ax.set_ylabel("tokens")
ax.set_title("TA's context length estimate runs 3.4-5.2x high")
ax.legend(fontsize=8, frameon=False); ax.grid(alpha=0.25)

ax = axes[1]
vals = [0.944, 0.000]
lbl = ["what TA believes it holds\n(Σ total_tokens / capacity)", "what the engine reports\n(kv_cache_usage x capacity)"]
bars = ax.bar(range(2), vals, color=["#b91c1c", "#94a3b8"])
for i, v in enumerate(vals):
    ax.text(i, v + 0.03, f"{v:.3f}", ha="center", fontsize=11)
ax.set_xticks(range(2)); ax.set_xticklabels(lbl, fontsize=8.5)
ax.set_ylim(0, 1.12); ax.set_ylabel("fraction of one card's KV")
ax.set_title("8 programs: 94% admitted, 0% visible to the engine")
ax.grid(axis="y", alpha=0.25)

fig.suptitle("E10-4/5  one card (114,176 tokens), TA in front, 90 watcher ticks", fontsize=11)
fig.tight_layout()
out = ROOT / "data" / "e10_ta_drift.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)