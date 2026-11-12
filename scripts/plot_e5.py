"""E5 corrected: three wirings, TA's capacity view decides everything."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "e5_corrected.csv").open(encoding="utf-8-sig")))
labels = {"ta_direct": "bare TA\n(card capacity 114k)",
          "ta_aggregate": "ours behind TA\n(cluster 228k)",
          "ta_percard": "ours, one per card\n(card capacity 114k)"}
xs = list(labels)
tpm = [float(r["turns_per_min"]) for r in rows]
p50 = [float(r["p50_s"]) for r in rows]
colors = ["#94a3b8", "#dc2626", "#1f5fbf"]

fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.3))
ax = axes[0]
bars = ax.bar(range(3), tpm, color=colors)
for i, v in enumerate(tpm):
    ax.text(i, v + 0.8, f"{v}", ha="center", fontsize=10)
ax.set_xticks(range(3)); ax.set_xticklabels([labels[x] for x in xs], fontsize=8)
ax.set_ylim(0, 56); ax.set_ylabel("turns per minute")
ax.set_title("Telling TA the truth about each card is worth 1.4x")
ax.grid(axis="y", alpha=0.25)
ax.axhline(tpm[0], ls=":", color="#64748b", lw=1.2)
ax.text(2.45, tpm[0] + 1.2, "bare TA", fontsize=8, color="#64748b", ha="right")

ax = axes[1]
ax.bar(range(3), p50, color=colors)
for i, v in enumerate(p50):
    ax.text(i, v + 0.02, f"{v:.2f} s", ha="center", fontsize=10)
ax.set_xticks(range(3)); ax.set_xticklabels([labels[x] for x in xs], fontsize=8)
ax.set_ylim(0, 1.05); ax.set_ylabel("median turn latency (s)")
ax.set_title("And it removes the 0.9 s tail")
ax.grid(axis="y", alpha=0.25)

fig.suptitle("E5: same load, same engines - only the wiring changed", fontsize=11.5)
fig.tight_layout()
out = ROOT / "data" / "e5_corrected.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
