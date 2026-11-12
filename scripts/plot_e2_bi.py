"""E2 bidirectional: latency per turn, and where the hits came from."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "e2_bi.csv").open(encoding="utf-8-sig")))

def series(arm, key):
    return [(int(r["turn"]), float(r[key])) for r in rows if r["arm"] == arm]

fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.5))

ax = axes[0]
for arm, colour, marker in (("off", "#c2410c", "s"), ("skew", "#1f5fbf", "o")):
    pts = series(arm, "p50_s")
    ax.plot([p[0] for p in pts], [p[1] for p in pts], marker=marker, lw=2.2, color=colour,
            label="balancer off" if arm == "off" else "balancer on (4 moved)")
    for x, y in pts:
        ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color=colour)
ax.set_xlabel("turn")
ax.set_ylabel("p50 turn latency (s)")
ax.set_title("Same 24 programs: moving 4 off the over-capacity card cuts p50 by 1.6x")
ax.set_xticks([1, 2, 3, 4])
ax.set_ylim(0.6, 1.45)
ax.grid(axis="y", alpha=0.25)
ax.legend(frameon=False, fontsize=9)

ax = axes[1]
labels = ["turn 1", "turn 2", "turn 3", "turn 4"]
a_hits = [float(r["a_hits"]) / 1000 for r in rows if r["arm"] == "skew"]
a_q = [float(r["a_queries"]) / 1000 for r in rows if r["arm"] == "skew"]
off_q = [float(r["a_queries"]) / 1000 for r in rows if r["arm"] == "off"]
x = range(4)
ax.bar([i - 0.2 for i in x], off_q, width=0.38, color="#c2410c", label="queries, balancer off")
ax.bar([i + 0.2 for i in x], a_q, width=0.38, color="#93c5fd", label="queries, balancer on")
ax.plot([i + 0.2 for i in x], a_hits, marker="o", lw=2.2, color="#1e3a8a", label="served from cache")
ax.set_xticks(list(x))
ax.set_xticklabels(labels)
ax.set_ylabel("prefix tokens per turn (thousands)")
ax.set_title("Where the work went: cache hits 0 -> 100k tokens per turn")
ax.legend(frameon=False, fontsize=7.5, loc="upper left", ncol=1, borderaxespad=0.2)
ax.grid(axis="y", alpha=0.25)

fig.tight_layout()
out = ROOT / "data" / "e2_bi.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
