"""Keep loop A/B: survival is the point, the refresh cost is the bill."""
from __future__ import annotations

import csv
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "m11_keep_e2e.csv").open(encoding="utf-8-sig")))

labels = [r["label"] for r in rows]
surv = [int(r["survivors"]) for r in rows]
hit = [float(r["hit_rate_median"]) * 100 for r in rows]
secs = [float(r["flood_seconds"]) for r in rows]
comp = [int(r["computed_tokens"]) for r in rows]
colors = ["#c2410c", "#1f5fbf", "#0f766e"]

fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.4))

ax = axes[0]
ax.bar(labels, surv, color=colors)
for i, v in enumerate(surv):
    ax.text(i, v + 0.2, f"{v}/10", ha="center", fontsize=10)
ax.set_ylim(0, 12)
ax.set_title("Programs still cached after 250k tokens of noise")
ax.set_ylabel("survivors")
ax.grid(axis="y", alpha=0.25)

ax = axes[1]
ax.bar(labels, secs, color=colors)
for i, v in enumerate(secs):
    ax.text(i, v + 0.25, f"{v:.1f}s", ha="center", fontsize=10)
ax.set_ylim(0, max(secs) * 1.25)
ax.set_title("What the flood cost (44 unrelated requests)")
ax.set_ylabel("seconds")
ax.grid(axis="y", alpha=0.25)

ax = axes[2]
ax.bar(labels, comp, color=colors)
for i, v in enumerate(comp):
    ax.text(i, v + max(comp) * 0.02, f"{v/1000:.0f}k", ha="center", fontsize=10)
ax.set_ylim(0, max(comp) * 1.25)
ax.set_title("Tokens the refreshes had to compute")
ax.set_ylabel("tokens")
ax.grid(axis="y", alpha=0.25)

fig.suptitle("Keep loop through the executor: 10 idle programs x 5.4k tokens, one card of 121k", fontsize=11)
fig.tight_layout()
out = ROOT / "data" / "m11_keep_e2e.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
