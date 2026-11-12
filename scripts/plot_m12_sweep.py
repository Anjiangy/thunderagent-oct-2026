"""Where does the marginal move stop paying?

16 programs pinned to one card (144k of demand on a 121k card), four turns.
Only the balancer's move budget changes between runs.
"""
from __future__ import annotations

import csv
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "m12_move_sweep.csv").open(encoding="utf-8-sig")))

budget = [int(r["budget"]) for r in rows]
total = [int(r["total_recompute"]) for r in rows]
walls = [float(r["wall_s"]) for r in rows]

# marginal saving per extra move (against the previous budget)
marg = []
for i in range(1, len(rows)):
    dm = max(1, budget[i] - budget[i - 1])
    marg.append(((total[i - 1] - total[i]) / 1000.0 / dm, budget[i]))

fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.5))

ax = axes[0]
bars = ax.bar([str(b) for b in budget], [t / 1000 for t in total], color="#1f5fbf")
for b, t, w in zip(budget, total, walls):
    ax.text(str(b), t / 1000 + 12, f"{t/1000:.0f}k", ha="center", fontsize=9)
ax.set_xlabel("move budget (programs allowed to migrate)")
ax.set_ylabel("total recomputed (thousand tokens)")
ax.set_title("Recompute collapses by move 4, then stops improving")
ax.set_ylim(0, max(total) / 1000 * 1.2)
ax.grid(axis="y", alpha=0.25)

ax = axes[1]
xs = [m[1] for m in marg]
ys = [m[0] for m in marg]
ax.bar([str(x) for x in xs], ys, color="#0f766e")
for x, y in zip(xs, ys):
    ax.text(str(x), y + (max(ys) * 0.03 if y >= 0 else -max(ys) * 0.08),
            f"{y:.0f}k", ha="center", fontsize=9)
ax.axhline(0, color="#333", lw=0.8)
ax.set_xlabel("budget reached (marginal move range)")
ax.set_ylabel("tokens saved per move (thousand)")
ax.set_title("Marginal value of an extra move")
ax.grid(axis="y", alpha=0.25)

fig.suptitle("16 programs x 11.7k tokens pinned to one card of 121k, 4 turns, only the move budget varies", fontsize=10.5)
fig.tight_layout()
out = ROOT / "data" / "m12_move_sweep.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
