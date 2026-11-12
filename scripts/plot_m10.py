"""Two questions in one picture: does an idle program survive pressure, and what
does keeping it alive cost in throughput?
"""
from __future__ import annotations

import csv
import pathlib
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT / "data" / "m10_residency.csv").open(encoding="utf-8-sig")))


def get(label_start):
    hit = [r for r in rows if r["label"].startswith(label_start)]
    return hit[0] if hit else None


fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.6))

# --- left: survival under pressure ---------------------------------------
ax = axes[0]
groups = [
    ("no pressure", ["c1-"], "0 filler"),
    ("200k filler", ["c3-", "c4-"], "1.6x card"),
    ("400k filler", ["c5-", "c6-"], "3.3x card"),
]
x = range(len(groups))
nokeep = []
keep = []
for _name, prefixes, _note in groups:
    base = next((get(p) for p in prefixes if get(p) and float(get(p)["keep_every_s"]) == 0), None)
    withkeep = next((get(p) for p in prefixes if get(p) and float(get(p)["keep_every_s"]) > 0), None)
    nokeep.append(int(base["survivors"]) if base else 0)
    keep.append(int(withkeep["survivors"]) if withkeep else 0)

w = 0.36
ax.bar([i - w / 2 for i in x], nokeep, w, label="no keep (LRU only)", color="#c2410c")
ax.bar([i + w / 2 for i in x], keep, w, label="keep: 1-token refresh", color="#1f5fbf")
ax.set_xticks(list(x))
ax.set_xticklabels([g[0] + "\n" + g[2] for g in groups], fontsize=9)
ax.set_ylabel("programs still cached (of 10)")
ax.set_ylim(0, 12.6)
ax.set_title("An idle program survives idleness, not competition")
ax.grid(axis="y", alpha=0.25)
for i, (bv, kv) in enumerate(zip(nokeep, keep)):
    ax.text(i - w / 2, bv + 0.15, f"{bv}/10", ha="center", fontsize=9, color="#c2410c")
    ax.text(i + w / 2, kv + 0.15, f"{kv}/10", ha="center", fontsize=9, color="#1f5fbf")
ax.legend(frameon=False, fontsize=9, loc="lower left")

# --- right: what keep costs in throughput --------------------------------
ax = axes[1]
cells = [
    ("0 filler", "c1-", "c11-"),
    ("200k filler", "c3-", "c8-"),
    ("400k filler", "c5-", "c6-"),
]
per_req = []
labels = []
for name, base_px, keep_px in cells:
    base = get(base_px)
    kp = get(keep_px)
    if base and float(base["filler_requests"]) > 0:
        per_req.append((float(base["pressure_s"]) / float(base["filler_requests"]), "no keep"))
    if kp and float(kp["filler_requests"]) > 0:
        per_req.append((float(kp["pressure_s"]) / float(kp["filler_requests"]), "keep 2 s"))
    if base or kp:
        labels.append(name)

# simple grouped bars, skipping the zero-filler cell
plot = [(lbl, b, k, bv, kv) for lbl, k, b, bv, kv in [
    ("200k filler", 0, 0, *[v for v, n in per_req if n == "no keep"][:1],
     *[v for v, n in per_req if n == "keep 2 s"][:1]),
    ("400k filler", 0, 0, *[v for v, n in per_req if n == "no keep"][1:2],
     *[v for v, n in per_req if n == "keep 2 s"][1:2]),
]]
xs = range(len(plot))
ax.bar([i - w / 2 for i in xs], [p[3] for p in plot], w, color="#c2410c", label="no keep")
ax.bar([i + w / 2 for i in xs], [p[4] for p in plot], w, color="#1f5fbf", label="keep every 2 s")
for i, p in enumerate(plot):
    ax.text(i - w / 2, p[3] + 0.02, f"{p[3]:.2f}", ha="center", fontsize=9, color="#c2410c")
    ax.text(i + w / 2, p[4] + 0.02, f"{p[4]:.2f}", ha="center", fontsize=9, color="#1f5fbf")
ax.set_xticks(list(xs))
ax.set_xticklabels([p[0] for p in plot], fontsize=9)
ax.set_ylabel("seconds per filler request")
ax.set_title("Keeping 10 programs alive slows the others 15-25%")
ax.grid(axis="y", alpha=0.25)
ax.legend(frameon=False, fontsize=9, loc="lower right")

fig.suptitle("Single card, 10 idle programs (54k tokens), 946 blocks x 128 = 121k tokens of KV", fontsize=11)
fig.tight_layout()
out = ROOT / "data" / "m10_residency.png"
fig.savefig(out, dpi=150)
print("wrote", out, out.stat().st_size)
