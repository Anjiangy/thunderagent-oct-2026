"""E1d: does churn evict an idle program's prefix cache?  Two orders, same cliff."""
from __future__ import annotations
import csv, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "e1_q_surface.csv").open(encoding="utf-8-sig")))
cap = int(rows[0]["capacity"])
styles = {"ascending": ("#1f5fbf", "o", "ascending pressure (0 -> 0.75)"),
          "descending": ("#b45309", "s", "descending pressure (0.75 -> 0)")}

fig, ax = plt.subplots(figsize=(8.6, 4.9))
for order, (color, marker, label) in styles.items():
    pts = sorted((float(r["pressure_ratio"]), float(r["q_mean"])) for r in rows if r["order"] == order)
    xs = [p for p, _ in pts]
    ys = [q for _, q in pts]
    ax.plot(xs[:2], ys[:2], marker=marker, ms=9, lw=2.2, color=color, label=label, ls="-")
    ax.plot(xs[1:3], ys[1:3], marker=marker, ms=9, lw=2.0, color=color, ls=":")
    ax.plot(xs[2:], ys[2:], marker=marker, ms=9, lw=2.2, color=color, ls="-")
    for p, q in pts:
        ax.annotate(f"{q:.2f}", (p, q), textcoords="offset points",
                    xytext=(0, 11) if q > 0.5 else (0, -17), ha="center", fontsize=8.5, color=color)

ax.axvspan(0.25, 0.5, color="#f3f4f6", zorder=0)
ax.text(0.375, 0.30, "no measurement in here\n(dotted = interpolated)", ha="center", fontsize=9, color="#6b7280")
ax.set_xlim(-0.04, 0.82)
ax.set_ylim(-0.06, 1.12)
ax.set_xlabel("unrelated traffic sent, as a fraction of one card's KV capacity")
ax.set_ylabel("hit rate when the idle program comes back")
ax.set_title("A sleeping program's cache dies once churn passes ~1/3 of the card")
ax.grid(alpha=0.25)
ax.legend(frameon=False, fontsize=9, loc="center left")
out = ROOT / "data" / "e1_q_surface.png"
fig.tight_layout()
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
