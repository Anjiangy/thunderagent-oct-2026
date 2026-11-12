"""E1e (dense cliff) + E2 (price of a keep-alive ping)."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
dense = list(csv.DictReader((ROOT / "data" / "e1_dense.csv").open(encoding="utf-8-sig")))
old = list(csv.DictReader((ROOT / "data" / "e1_q_surface.csv").open(encoding="utf-8-sig")))
e2 = list(csv.DictReader((ROOT / "data" / "e2_ping.csv").open(encoding="utf-8-sig")))[0]

fig, (ax, bx) = plt.subplots(1, 2, figsize=(12.6, 4.8))

xs = [float(r["pressure_ratio"]) for r in dense]
ys = [float(r["q_mean"]) for r in dense]
o = [float(r["pressure_ratio"]) for r in old if r["order"] == "ascending"]
oy = [float(r["q_mean"]) for r in old if r["order"] == "ascending"]
ax.scatter(o, oy, marker="o", s=70, facecolors="none", edgecolors="#1f5fbf", lw=1.8,
           label="earlier, coarse (no points between)")
ax.plot(xs, ys, marker="s", ms=9, lw=2.4, color="#b45309", label="dense sweep (step 0.05)")
ax.axvspan(0.40, 0.50, color="#f3f4f6", zorder=0)
ax.text(0.452, 0.45, "cliff in here", ha="center", fontsize=9, color="#6b7280", rotation=90)
for x, y in zip(xs, ys):
    ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=8.5)
ax.set_xlim(0.18, 0.58)
ax.set_ylim(-0.06, 1.12)
ax.set_xlabel("unrelated traffic / one card's KV capacity")
ax.set_ylabel("hit rate when the idle program returns")
ax.set_title("The cache does not decay, it falls off a cliff at ~0.45")
ax.grid(alpha=0.25)
ax.legend(frameon=False, fontsize=8.5, loc="center left")

th, tm = float(e2["t_hit_s"]), float(e2["t_miss_s"])
bx.bar([0, 1], [th, tm], color=["#1f5fbf", "#b45309"], width=0.55)
for i, v in enumerate([th, tm]):
    bx.annotate(f"{v:.3f} s", (i, v), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=10)
bx.set_xticks([0, 1])
bx.set_xticklabels(["cached: 1-token ping\n(what keeping costs)", "evicted: full prefill\n(what forgetting costs)"],
                   fontsize=9)
bx.set_ylim(0, tm * 1.28)
bx.set_ylabel("wall clock per turn (s)")
bx.set_title(f"One miss buys {tm/th:.1f} pings (E2)")
bx.grid(axis="y", alpha=0.25)

fig.suptitle("E1 + E2: the cliff is real, and keeping a program alive is cheap per ping but you must ping often", fontsize=11)
fig.tight_layout()
out = ROOT / "data" / "e1e_e2.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
