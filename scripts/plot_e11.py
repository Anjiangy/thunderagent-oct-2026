"""Real SWE-agent sweep: three routers, same six instances."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = {r["arm"]: r for r in csv.DictReader((ROOT / "data" / "e11_sweep.csv").open(encoding="utf-8-sig"))}
arms = ["ta", "aff", "stk"]
label = {"ta": "bare TA", "aff": "ours: affinity", "stk": "ours: sticky(bytes)"}
color = {"ta": "#94a3b8", "aff": "#1f5fbf", "stk": "#0f766e"}

fig, axes = plt.subplots(1, 3, figsize=(13.6, 4.3))
ax = axes[0]
w = 0.26
for i, a in enumerate(arms):
    r = rows[a]
    ax.bar(i - w, float(r["hit_a"]) * 100, w, color=color[a], alpha=0.95)
    ax.bar(i, float(r["hit_b"]) * 100, w, color=color[a], alpha=0.6)
    ax.bar(i + w, float(r["hit_cluster"]) * 100, w, color=color[a], alpha=1.0, edgecolor="k", lw=0.6)
    ax.text(i + w, float(r["hit_cluster"]) * 100 + 0.15, f'{float(r["hit_cluster"])*100:.1f}%', ha="center", fontsize=9)
ax.set_xticks(range(3)); ax.set_xticklabels([label[a] for a in arms], fontsize=8)
ax.set_ylim(94, 98.2); ax.set_ylabel("prefix-cache hit rate (%)")
ax.set_title("Hit rate: all three arms are ~96-97%")
ax.grid(axis="y", alpha=0.25)

ax = axes[1]
walls = [float(rows[a]["wall_s"]) for a in arms]
ax.bar(range(3), walls, color=[color[a] for a in arms])
for i, v in enumerate(walls):
    ax.text(i, v + 25, f"{v:.0f} s", ha="center", fontsize=9)
ax.set_xticks(range(3)); ax.set_xticklabels([label[a] for a in arms], fontsize=8)
ax.set_ylim(0, 1900); ax.set_ylabel("wall clock (s)")
ax.set_title("Wall clock: sticky is 4.2x slower")
ax.grid(axis="y", alpha=0.25)

ax = axes[2]
dq = [float(rows[a]["dq_a"]) + float(rows[a]["dq_b"]) for a in arms]
dh = [float(rows[a]["dh_a"]) + float(rows[a]["dh_b"]) for a in arms]
re = [d - h for d, h in zip(dq, dh)]
ax.bar([i - 0.18 for i in range(3)], [x / 1000 for x in dq], 0.36, color="#cbd5e1", label="queried")
ax.bar([i + 0.18 for i in range(3)], [x / 1000 for x in re], 0.36, color="#b91c1c", label="recomputed")
for i, x in enumerate(re):
    ax.text(i + 0.18, x / 1000 + 25, f"{x/1000:.0f}k", ha="center", fontsize=8.5)
ax.set_xticks(range(3)); ax.set_xticklabels([label[a] for a in arms], fontsize=8)
ax.set_ylabel("tokens (thousands)"); ax.set_title("Work volume and what had to be recomputed")
ax.legend(fontsize=8, frameon=False); ax.grid(axis="y", alpha=0.25)

fig.suptitle("Real SWE-agent traffic (6 instances, step_limit 30, w8, same engines) — engines were NOT restarted between arms", fontsize=11)
fig.tight_layout()
out = ROOT / "data" / "e11_sweep.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
