"""Render the manuscript's figures (PNG) and print the statistics they show.

Reads only files already produced by the pipeline (data/*.json, data/*.csv,
data/ca_coc_boundaries.min.geojson); no network. Writes manuscript_figures/fig*.png.

    .venv/bin/python make_manuscript_figures.py
"""
import csv
import json
import math
import os
import statistics as st

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PatchCollection  # noqa: E402
from matplotlib.colors import LogNorm, TwoSlopeNorm  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

DATA = "data"
OUT = "manuscript_figures"
os.makedirs(OUT, exist_ok=True)

# Same palette as index.html (validated pair + neutral gray).
BLUE, ORANGE, GRAY, INK, GRID = "#2a78d6", "#eb6834", "#8a8f98", "#1f2328", "#e3e5e8"
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 9,
    "axes.edgecolor": "#b9bec6",
    "axes.labelcolor": INK,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "xtick.color": "#4b5058",
    "ytick.color": "#4b5058",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
})


def load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


# ---------- data ----------
truth = {r["coc_number"]: r["ground_truth_r"] for r in load("ai_vs_ground_truth.json")["by_coc"]}
names = {r["coc_number"]: r["coc_name"] for r in load("ai_vs_ground_truth.json")["by_coc"]}
cocs = sorted(truth)

cov = {}
with open(os.path.join(DATA, "ca_coc_covariates.csv")) as f:
    for row in csv.DictReader(f):
        cov[row["coc_number"]] = row
structures = {c: float(cov[c]["structures_destroyed_total"]) for c in cocs}


def trial_values(path):
    """{coc: [estimate per trial]} from a trials-style file."""
    out = {}
    for trial in load(path)["trials"]:
        for e in trial:
            out.setdefault(e["coc_number"], []).append(float(e["estimated_correlation"]))
    return out


claude_orig = {e["coc_number"]: [float(v) for v in e["estimated_correlation_trials"]]
               for e in load("ai_fire_influence_estimates.json")["estimates"]}
CONDITIONS = [  # (key, label, per-CoC trial lists)
    ("claude_baseline", "Claude, original (Sept 23)", claude_orig),
    ("claude_pit", "Claude, + PIT description", trial_values("ai_estimates_claude_pit_informed.json")),
    ("claude_rerun", "Claude, original (Sept 30)", trial_values("ai_estimates_claude_baseline_rerun.json")),
    ("claude_neutral", "Claude, neutral (Sept 30)", trial_values("ai_estimates_claude_neutral.json")),
    ("gemini_baseline", "Gemini, original", trial_values("ai_estimates_gemini_baseline.json")),
    ("gemini_pit", "Gemini, + PIT description", trial_values("ai_estimates_gemini_pit_informed.json")),
    ("gemini_neutral", "Gemini, neutral", trial_values("ai_estimates_gemini_neutral.json")),
]
mean_est = {k: {c: st.mean(v[c]) for c in cocs} for k, _, v in CONDITIONS}
label = {k: lab for k, lab, _ in CONDITIONS}


def spearman(x, y):
    def ranks(a):
        order = sorted(range(len(a)), key=lambda i: a[i])
        r = [0.0] * len(a)
        i = 0
        while i < len(a):
            j = i
            while j + 1 < len(a) and a[order[j + 1]] == a[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return num / math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))


def short(c):
    n = names[c].replace(" CoC", "")
    return n if len(n) <= 34 else n[:33].rstrip(" ,/&") + "\u2026"


def group(c):
    s = structures[c]
    return "1,000+" if s >= 1000 else ("<100" if s < 100 else "100-999")


GROUPS = ["<100", "100-999", "1,000+"]

# ---------- statistics printed for the manuscript ----------
obs = [truth[c] for c in cocs]
print(f"Observed: {sum(r < 0 for r in obs)} of {len(obs)} CoC correlations negative; "
      f"mean {st.mean(obs):+.3f}; SD {st.stdev(obs):.3f}")
print(f"Observed vs structures rho = {spearman(obs, [structures[c] for c in cocs]):+.2f}")
print(f"Group sizes: " + ", ".join(f"{g}: {sum(group(c) == g for c in cocs)}" for g in GROUPS))
for k, lab, trials in CONDITIONS:
    vals = [v for c in trials for v in trials[c]]  # all 44 CoCs, as in the manuscript
    m = mean_est[k]
    gaps = {g: [m[c] - truth[c] for c in cocs if group(c) == g] for g in GROUPS}
    above = sum(m[c] > truth[c] for c in cocs)
    top = max(cocs, key=lambda c: m[c])
    print(f"{lab:30s} mean {st.mean(m.values()):.3f}  negatives {sum(v < 0 for v in vals)}/{len(vals)}  "
          f"SD(CoC means) {st.stdev(m.values()):.3f}  est>obs {above}/40  "
          f"rho(est,structures) {spearman([m[c] for c in cocs], [structures[c] for c in cocs]):+.2f}  "
          + "  ".join(f"gap[{g}] {st.mean(v):+.2f}" for g, v in gaps.items())
          + f"  top {top} {m[top]:.2f}")

# Sign test for "estimate above observed" (binomial, two-sided).
def binom_two_sided(k, n):
    p = sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n
    return min(1.0, 2 * p)


for k in ("claude_neutral", "gemini_neutral"):
    above = sum(mean_est[k][c] > truth[c] for c in cocs)
    print(f"sign test {k}: {above}/40 above observed, p = {binom_two_sided(max(above, 40 - above), 40):.3f}")
    hi = [mean_est[k][c] - truth[c] for c in cocs if group(c) == "1,000+"]
    print(f"  1,000+ group: {sum(g > 0 for g in hi)}/{len(hi)} above observed, "
          f"mean gap {st.mean(hi):+.3f} (SE {st.stdev(hi) / math.sqrt(len(hi)):.3f})")


# ---------- Figure 1: distributions, AI vs observed ----------
def fig_distributions():
    rows = [("Observed (HUD PIT data)", obs, GRAY)] + [
        (label[k], [mean_est[k][c] for c in cocs], BLUE if k.startswith("claude") else ORANGE)
        for k in ("claude_baseline", "claude_pit", "claude_rerun", "claude_neutral",
                  "gemini_baseline", "gemini_pit", "gemini_neutral")
    ]
    neg = {"Observed (HUD PIT data)": f"{sum(r < 0 for r in obs)} of 40 CoCs below 0"}
    for k, lab, trials in CONDITIONS:
        vals = [v for c in trials for v in trials[c]]
        neg[lab] = f"{sum(v < 0 for v in vals)} of {len(vals)} estimates below 0"
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    for i, (lab, vals, col) in enumerate(rows):
        y = len(rows) - 1 - i
        # deterministic jitter so the figure is reproducible
        jit = [((j * 37) % 11 - 5) / 22 for j in range(len(vals))]
        ax.scatter(vals, [y + j * 0.5 for j in jit], s=14, color=col, alpha=0.75, linewidths=0)
        ax.plot([st.mean(vals)] * 2, [y - 0.33, y + 0.33], color=INK, lw=1.6)
        ax.text(1.0, y, neg[lab], va="center", ha="left", fontsize=8, color="#4b5058",
                transform=ax.get_yaxis_transform())
    ax.axvline(0, color=INK, lw=0.8)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows][::-1])
    ax.set_xlim(-0.85, 0.85)
    ax.set_xlabel("Correlation between acres burned and same-year PIT count (one dot per CoC)")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.savefig(os.path.join(OUT, "fig1_distributions.png"))
    plt.close(fig)


# ---------- Figure 2: original vs neutral, per CoC (dumbbell) ----------
def fig_dumbbell():
    order = sorted(cocs, key=lambda c: structures[c])
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 7.6), sharey=True)
    for ax, (k0, k1, title, col) in zip(axes, [
        ("claude_rerun", "claude_neutral", "Claude (same Sept 30 batch)", BLUE),
        ("gemini_baseline", "gemini_neutral", "Gemini 3.5 Flash-Lite", ORANGE),
    ]):
        for y, c in enumerate(order):
            a, b = mean_est[k0][c], mean_est[k1][c]
            ax.plot([a, b], [y, y], color=col, lw=1.2, alpha=0.45)
            ax.scatter([a], [y], s=16, facecolors="white", edgecolors=col, linewidths=1.0, zorder=3)
            ax.scatter([b], [y], s=16, color=col, zorder=3)
            ax.scatter([truth[c]], [y], s=18, marker="D", color=GRAY, zorder=2)
        ax.axvline(0, color=INK, lw=0.8)
        ax.set_xlim(-0.75, 0.85)
        ax.set_title(title)
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", length=0)
        # mark the destruction groups
        for g_lo in (sum(structures[c] < 100 for c in cocs), sum(structures[c] < 1000 for c in cocs)):
            ax.axhline(g_lo - 0.5, color="#b9bec6", lw=0.6)
    axes[0].set_yticks(range(len(order)))
    axes[0].set_yticklabels([short(c) for c in order], fontsize=6.5)
    axes[0].spines["left"].set_visible(False)
    axes[1].spines["left"].set_visible(False)
    n_lo = sum(structures[c] < 100 for c in cocs)
    n_mid = sum(structures[c] < 1000 for c in cocs)
    for y, txt in ((n_lo / 2, "<100 structures\ndestroyed"), ((n_lo + n_mid) / 2, "100-999"),
                   ((n_mid + len(cocs)) / 2, "1,000+")):
        axes[1].text(0.86, y, txt, fontsize=7, color="#4b5058", va="center", ha="left",
                     transform=axes[1].get_yaxis_transform())
    handles = [
        plt.Line2D([], [], marker="o", ls="", mfc="white", mec=INK, label="Original prompt"),
        plt.Line2D([], [], marker="o", ls="", color=INK, label="Neutral prompt"),
        plt.Line2D([], [], marker="D", ls="", color=GRAY, label="Observed r"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.01))
    fig.supxlabel("Correlation (acres burned vs. same-year PIT count)", y=0.025, fontsize=9)
    fig.subplots_adjust(bottom=0.09, wspace=0.08)
    fig.savefig(os.path.join(OUT, "fig2_neutral_dumbbell.png"))
    plt.close(fig)


# ---------- Figure 3: estimate vs structures destroyed + gap by group ----------
def fig_salience():
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.4, 3.3), gridspec_kw={"width_ratios": [1.25, 1]})
    xs = {c: structures[c] + 1 for c in cocs}
    ax.scatter([xs[c] for c in cocs], [truth[c] for c in cocs], s=16, marker="D", color=GRAY,
               label="Observed r", zorder=2)
    ax.scatter([xs[c] for c in cocs], [mean_est["claude_neutral"][c] for c in cocs], s=18, color=BLUE,
               label="Claude, neutral", zorder=3)
    ax.scatter([xs[c] for c in cocs], [mean_est["gemini_neutral"][c] for c in cocs], s=18, color=ORANGE,
               label="Gemini, neutral", zorder=3)
    butte = "CA-519"
    ax.annotate("Butte (Camp Fire)", (xs[butte], mean_est["claude_neutral"][butte]),
                xytext=(-95, 22), textcoords="offset points", fontsize=7.5, color=INK,
                arrowprops={"arrowstyle": "-", "color": "#4b5058", "lw": 0.6})
    ax.set_xscale("log")
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_xlabel("Structures destroyed, 2013-2024 (+1, log scale)")
    ax.set_ylabel("Correlation")
    ax.set_title("A. Estimate vs. destruction")
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=7.5, loc="lower left")

    keys = [("claude_rerun", "Claude, original", BLUE, 0.45), ("claude_neutral", "Claude, neutral", BLUE, 1.0),
            ("gemini_baseline", "Gemini, original", ORANGE, 0.45), ("gemini_neutral", "Gemini, neutral", ORANGE, 1.0)]
    w = 0.2
    for i, (k, lab, col, alpha) in enumerate(keys):
        vals = [st.mean([mean_est[k][c] - truth[c] for c in cocs if group(c) == g]) for g in GROUPS]
        xpos = [j + (i - 1.5) * w for j in range(len(GROUPS))]
        bx.bar(xpos, vals, width=w, color=col, alpha=alpha, label=lab)
    bx.axhline(0, color=INK, lw=0.8)
    bx.set_xticks(range(len(GROUPS)))
    bx.set_xticklabels([f"{g}\n(n={sum(group(c) == g for c in cocs)})" for g in GROUPS])
    bx.set_xlabel("Structures destroyed")
    bx.set_ylabel("Mean gap (estimate - observed)")
    bx.set_title("B. Mean gap by group")
    bx.grid(axis="y", color=GRID, lw=0.6)
    bx.set_axisbelow(True)
    bx.legend(frameon=False, fontsize=7, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig3_salience.png"))
    plt.close(fig)


# ---------- Figure 4: maps ----------
def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    return [p[0] for p in geom["coordinates"]]


def fig_maps():
    gj = load("ca_coc_boundaries.min.geojson")
    feats = [f for f in gj["features"]]
    panels = [
        ("A. Structures destroyed, 2013-2024", {c: structures[c] + 1 for c in structures}, "log"),
        ("B. Observed r (HUD PIT data)", truth, "div"),
        ("C. Claude, neutral prompt", mean_est["claude_neutral"], "div"),
        ("D. Gemini, neutral prompt", mean_est["gemini_neutral"], "div"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 8.2))
    axes = axes.ravel()
    div_norm = TwoSlopeNorm(vmin=-0.7, vcenter=0, vmax=0.7)
    log_norm = LogNorm(vmin=1, vmax=max(structures.values()) + 1)
    for ax, (title, vals, kind) in zip(axes, panels):
        patches, colors = [], []
        cmap = plt.get_cmap("Purples" if kind == "log" else "RdBu_r")
        norm = log_norm if kind == "log" else div_norm
        for f in feats:
            c = f["properties"].get("COCNUM")
            v = vals.get(c)
            for ring in polygons(f["geometry"]):
                patches.append(Polygon(ring, closed=True))
                colors.append("#b9bec6" if v is None else cmap(norm(v)))
        ax.add_collection(PatchCollection(patches, facecolor=colors, edgecolor="white", linewidths=0.3))
        ax.set_xlim(-124.6, -114.0)
        ax.set_ylim(32.4, 42.1)
        ax.set_aspect(1 / math.cos(math.radians(37)))
        ax.axis("off")
        ax.set_title(title, fontsize=9.5)
        sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
        cb = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.045, pad=0.02, aspect=22)
        cb.ax.tick_params(labelsize=7)
        cb.outline.set_visible(False)
        if kind == "log":
            cb.set_ticks([1, 10, 100, 1000, 10000])
            cb.set_ticklabels(["0", "10", "100", "1k", "10k"])
    fig.text(0.02, 0.0, "Gray: no observed correlation (San Francisco, Long Beach and Imperial have no "
             "major fires; Nevada County's only post-2019 fire was in 2021).", fontsize=7, color="#4b5058")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig4_maps.png"))
    plt.close(fig)


fig_distributions()
fig_dumbbell()
fig_salience()
fig_maps()
print("wrote", sorted(os.listdir(OUT)))
