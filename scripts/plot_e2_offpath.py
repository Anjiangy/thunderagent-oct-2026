"""Blocking vs off-path migration: tail latency and bytes actually moved."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "e2_offpath.csv").open(encoding="utf-8-sig")))
arms = {"blocking": ("blocking (capture+pull inside the move)", "#c2410c", "s"),
        "offpath": ("off-path (pull in the background)", "#1f5fbf", "o")}

fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.5))

ax = axes[0]
for arm, (label, colour, marker) in arms.items():
    pts = [(int(r["turn"]), float(r["max_s"])) for r in rows if r["arm"] == arm]
    ax.plot([p[0] for p in pts], [p[1] for p in pts], marker=marker, lw=2.2, color=colour, label=label)
    for x, y in pts:
        if y > 2:
            ax.annotate(f"{y:.2f} s", (x, y), textcoords="offset points", xytext=(0, 8),
                        ha="center", fontsize=9, color=colour)
ax.set_yscale("log")
ax.set_xlabel("turn")
ax.set_ylabel("worst turn latency (s, log)")
ax.set_title("Worst turn latency: the 10.7 s tail is gone")
ax.set_xticks([1, 2, 3, 4])
ax.grid(axis="y", alpha=0.25, which="both")
ax.legend(frameon=False, fontsize=9)

ax = axes[1]
for arm, (label, colour, marker) in arms.items():
    pts = [(int(r["turn"]), float(r["b_external_hits"]) / 1000) for r in rows if r["arm"] == arm]
    ax.plot([p[0] for p in pts], [p[1] for p in pts], marker=marker, lw=2.2, color=colour, label=label)
ax.set_xlabel("turn")
ax.set_ylabel("KV pulled from the peer (thousand tokens)")
ax.set_title("Bytes actually pulled: fewer, because the window is 4 s")
ax.set_xticks([1, 2, 3, 4])
ax.grid(axis="y", alpha=0.25)
ax.legend(frameon=False, fontsize=9)

fig.tight_layout()
out = ROOT / "data" / "e2_offpath.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
