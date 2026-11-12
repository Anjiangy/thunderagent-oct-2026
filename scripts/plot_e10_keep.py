"""E10-2: same churn for every arm; does keeping the cache change what a user feels?"""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "e10_keep_cost.csv").open(encoding="utf-8-sig")))
for r in rows:
    for k in ("dq", "dh", "keep_requests", "churn_tokens"):
        r[k] = int(r[k])
    for k in ("churn_mult", "hit_all", "keep_s", "p50_step_s", "max_step_s", "sum_step_s"):
        r[k] = float(r[k])

name = {"off": "no keep\n(today's default)", "naive": "keep every 2 s", "gated": "keep by churn rate\n(floor 2 s)"}
xs = [r["arm"] for r in rows]
colors = {"off": "#94a3b8", "naive": "#1f6feb", "gated": "#0f766e"}

fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.5))

ax = axes[0]
vals = [r["hit_all"] * 100 for r in rows]
ax.bar(range(3), vals, color=[colors[x] for x in xs])
for i, v in enumerate(vals):
    ax.text(i, v + 1.5, f"{v:.1f}%", ha="center", fontsize=10)
ax.set_xticks(range(3)); ax.set_xticklabels([name[x] for x in xs], fontsize=8)
ax.set_ylim(0, 90); ax.set_ylabel("counted prefix-cache hit rate (%)")
ax.set_title("Keeping buys hit-rate points")
ax.grid(axis="y", alpha=0.25)

ax = axes[1]
tot = [r["sum_step_s"] for r in rows]
mx = [r["max_step_s"] for r in rows]
ax.bar([i - 0.2 for i in range(3)], tot, width=0.4, color="#cbd5e1", label="sum of 16 turns (s)")
ax.bar([i + 0.2 for i in range(3)], mx, width=0.4, color=[colors[x] for x in xs], label="worst single turn (s)")
for i in range(3):
    ax.text(i - 0.2, tot[i] + 4, f"{tot[i]:.1f}", ha="center", fontsize=9)
    ax.text(i + 0.2, mx[i] + 4, f"{mx[i]:.1f}", ha="center", fontsize=9)
ax.set_xticks(range(3)); ax.set_xticklabels([name[x] for x in xs], fontsize=8)
ax.set_ylim(0, 260); ax.set_ylabel("seconds")
ax.set_title("...and buys zero user-visible latency")
ax.legend(fontsize=8, frameon=False); ax.grid(axis="y", alpha=0.25)

ax = axes[2]
extra = [(r["dq"] - rows[0]["dq"]) / 1000 for r in rows]
ax.bar(range(3), extra, color=[colors[x] for x in xs])
for i, v in enumerate(extra):
    ax.text(i, v + 10, f"+{v:.0f}k", ha="center", fontsize=10)
ax.set_xticks(range(3)); ax.set_xticklabels([name[x] for x in xs], fontsize=8)
ax.set_ylabel("extra prefill tokens counted (thousands)")
ax.set_title("The bill: 3x prefill tokens for the same step time")
ax.grid(axis="y", alpha=0.25)

fig.suptitle("E10-2  one card, 4 programs x 3500-word prefixes x 4 turns, churn 1.43x capacity in every arm", fontsize=10.5)
fig.tight_layout()
out = ROOT / "data" / "e10_keep_cost.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)