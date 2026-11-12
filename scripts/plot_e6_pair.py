"""E6 clean pair: single card, cold engine before every run."""
import csv, pathlib, statistics
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "e6_pair_clean.csv").open(encoding="utf-8-sig")))
arms = {"ta": ("bare ThunderAgent", "#94a3b8", "o"), "ours": ("executor in front", "#1f5fbf", "s")}
fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2))
for ax, key, ylab, title, scale in (
    (axes[0], "hit", "prefix-cache hit rate (%)", "Hit rate: the two arms overlap", 100.0),
    (axes[1], "wall_s", "wall clock (s)", "Wall clock: ours has one slow run", 1.0),
):
    for i, (arm, (label, color, marker)) in enumerate(arms.items()):
        vals = [float(r[key]) * scale for r in rows if r["arm"] == arm]
        ax.scatter([i - 0.06 + 0.12 * j for j in range(len(vals))], vals, s=70, color=color, marker=marker, label=label)
        m = statistics.mean(vals)
        ax.plot([i - 0.22, i + 0.22], [m, m], color=color, lw=2.2)
        ax.text(i + 0.26, m, f"{m:.1f}", va="center", fontsize=9, color=color)
    ax.set_xticks([0, 1]); ax.set_xticklabels([v[0] for v in arms.values()], fontsize=9)
    ax.set_xlim(-0.5, 1.5); ax.set_ylabel(ylab); ax.set_title(title); ax.grid(axis="y", alpha=0.25)
axes[0].set_ylim(74, 79)
axes[1].set_ylim(220, 345)
axes[0].legend(frameon=False, fontsize=8)
fig.suptitle("E6 clean pair — 18 SWE instances, w8, slice 0:18, engine restarted before each run", fontsize=10.5)
fig.tight_layout()
out = ROOT / "data" / "e6_pair_clean.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
