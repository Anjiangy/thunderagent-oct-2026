"""E3: what a ping costs, what forgetting costs, and where migrating crosses over."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "e3_cost_model.csv").open(encoding="utf-8-sig")))
tok = [int(r["prompt_tokens"]) for r in rows]
ping = [float(r["t_ping_s"]) for r in rows]
rec = [float(r["t_recompute_s"]) for r in rows]
TRANSFER_RATIO = 0.61          # E-env, same-family measurement

fig, (ax, bx) = plt.subplots(1, 2, figsize=(12.8, 4.9))

ax.plot(tok, rec, marker="s", ms=9, lw=2.4, color="#b45309", label="forgot it: full prefill")
ax.plot(tok, ping, marker="o", ms=9, lw=2.4, color="#1f5fbf", label="kept it: one 1-token ping")
for x, y, r in zip(tok, rec, rows):
    ax.annotate(f"{y:.2f}s ({float(r['ratio']):.1f}x)", (x, y), textcoords="offset points",
                xytext=(0, 9), ha="center", fontsize=8.5, color="#b45309")
ax.set_xlabel("prefix length (prompt tokens)")
ax.set_ylabel("wall clock per turn (s)")
ax.set_title("A ping is flat at ~0.12 s; forgetting scales with prefix")
ax.set_ylim(0, 0.92)
ax.grid(alpha=0.25)
ax.legend(frameon=False, fontsize=9, loc="upper left")

mid = 1
S = tok[mid]
p = ping[mid]
r = rec[mid]
labels = ["1 ping", "3 pings", "6 pings", f"migrate ({TRANSFER_RATIO}x prefill)"]
vals = [p, 3 * p, 6 * p, TRANSFER_RATIO * r]
colors = ["#1f5fbf", "#1f5fbf", "#1f5fbf", "#15803d"]
bars = bx.bar(range(len(vals)), vals, color=colors, width=0.6)
for i, v in enumerate(vals):
    bx.annotate(f"{v:.2f}s", (i, v), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=9.5)
bx.axhline(TRANSFER_RATIO * r, ls=":", color="#15803d", lw=1.4)
bx.set_xticks(range(len(vals)))
bx.set_xticklabels(labels, fontsize=9)
bx.set_ylabel("cost (s)")
bx.set_title(f"For a {S}-token program, moving beats keeping past ~2.4 pings")
bx.set_ylim(0, max(vals) * 1.3)
bx.grid(axis="y", alpha=0.25)

fig.suptitle("E3: keeping is cheap per ping, but a long sleep is cheaper to migrate than to babysit", fontsize=11)
fig.tight_layout()
out = ROOT / "data" / "e3_cost_model.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
