"""E11 pressure: same harness, same prefixes, only the number of concurrent programs differs."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "e11_pressure.csv").open(encoding="utf-8-sig")))
for r in rows:
    r["instances"] = int(r["instances"])
    r["hit"] = float(r["hit_cluster"]) * 100
    r["tps"] = float(r["tok_per_s"])
    r["wall"] = float(r["wall_s"])

label = {"sticky32": "ours (sticky router)", "ta32": "bare ThunderAgent"}
color = {"sticky32": "#1f5fbf", "ta32": "#64748b"}
order = [m for m in ("ta32", "sticky32") if any(r["mode"] == m for r in rows)]

fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.4))

ax = axes[0]
st = [r for r in rows if r["mode"] == "sticky32"]
xs = [6] + [r["instances"] for r in st]
ys = [95.82] + [r["hit"] for r in st]
ax.plot(xs, ys, "o-", color="#1f5fbf", lw=2, ms=7, label="ours (sticky router)")
mk = {"sticky32": ("s", 31.4), "ta32": ("^", 32.6)}
for r in order:
    row = next(x for x in rows if x["mode"] == r)
    m, dx = mk[r]
    ax.plot([dx], [row["hit"]], m, color=color[r], ms=11, label=label[r])
    off = (12, 4) if r == "sticky32" else (12, -12)
    ax.annotate(f"{row['hit']:.2f}%", (dx, row["hit"]), textcoords="offset points",
                xytext=off, ha="left", fontsize=8.5, color=color[r])
ax.annotate("95.82%", (6, 95.82), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8.5, color="#1f5fbf")
ax.set_xlabel("concurrent programs"); ax.set_ylabel("cluster prefix-cache hit rate (%)")
ax.set_title("32 concurrent programs finally push one card past capacity")
ax.set_ylim(75, 100); ax.set_xlim(3, 37); ax.grid(alpha=0.25); ax.legend(fontsize=8.5, loc="lower left")

ax = axes[1]
modes = [r["mode"] for r in rows]
vals = [r["tps"] for r in rows]
xs2 = range(len(modes))
ax.bar(xs2, vals, color=[color.get(m, "#94a3b8") for m in modes])
for i, v in enumerate(vals):
    ax.text(i, v + 80, f"{v}", ha="center", fontsize=9)
ax.set_xticks(list(xs2))
ax.set_xticklabels([f"{label.get(m, m)}\n{next(r['instances'] for r in rows if r['mode']==m)} programs" for m in modes], fontsize=8)
ax.set_ylabel("query tokens per second"); ax.set_title("Throughput goes up even as the hit rate falls")
ax.grid(axis="y", alpha=0.25)

fig.suptitle("E11  real mini-swe-agent, 5000-word prefixes, 6 steps, same two cards", fontsize=11)
fig.tight_layout()
out = ROOT / "data" / "e11_pressure.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size, "rows", len(rows))
