#!/usr/bin/env python3
"""
Where is the AI-vs-ground-truth gap larger or smaller, and what kind of place
is it larger in?

The per-CoC signed error is ai_estimate - ground_truth_r, so it can vary
across CoCs for two separate reasons, and they are tested separately:

  1. the ground truth varies. Each CoC's r comes from 6-18 annual points, so
     it carries sampling noise of roughly 1/sqrt(n-3) on the Fisher-z scale.
     Cochran's Q asks whether the per-CoC r's vary more than that noise alone
     would produce. If they don't, a covariate that "explains" the truth, or
     the error, is mostly explaining noise.
  2. the AI's estimate varies. Its per-CoC mean over 10 trials is measured
     well, which split-half reliability (odd vs. even trials,
     Spearman-Brown corrected) confirms, so what predicts it is answerable.

The truth is computed under four specifications, because two data problems
affect it: HUD's COVID waiver let most CA CoCs skip the 2021 unsheltered
count (statewide total falls from ~162k to ~57k), and the PIT count is taken
in January, before that calendar year's fire season, so lag1 (prior-year
fires) is the causally ordered comparison. The published ground truth
(compute_fire_influence.py) is lag0 with 2021 excluded, since the AI was
asked about the same-year relationship; errors are measured against it.

Each outcome is correlated (Spearman) with every column of
data/ca_coc_covariates.csv, with Benjamini-Hochberg FDR across the
covariates for that outcome. Two follow-ups: rank partial correlations of
each AI estimate with every covariate after removing structures destroyed
and population density (does anything about a place matter beyond how
destructive and how rural it is?), and a precision-weighted meta-regression
of the truth, so short-series CoCs don't count as much as 18-year ones.

Output: data/error_heterogeneity.json
"""

import csv
import json
import math
import pathlib
import statistics as st

import numpy as np

import compute_fire_influence as gt
from compare_ai_conditions import load_trials, pearson, ranks

DATA_DIR = pathlib.Path(__file__).parent / "data"
DEST = DATA_DIR / "error_heterogeneity.json"
SALIENCE_CONTROLS = ["structures_destroyed_total", "pop_density_sqmi"]

CONDITIONS = [("claude", "baseline"), ("claude", "pit_informed"), ("gemini", "baseline"), ("gemini", "pit_informed")]
TRUTH_SPECS = {
    "lag0_all_years": (0, False),
    "lag0_drop2021": (0, True),     # the published ground truth (same-year, as the AI was asked)
    "lag1_all_years": (1, False),
    "lag1_drop2021": (1, True),     # causally ordered, COVID-year artifact removed
}


def normal_p(z):
    return 2 * (1 - gt.normal_cdf(abs(z)))


def chi2_sf(x, df):
    # Wilson-Hilferty normal approximation; fine for df ~ 40.
    z = ((x / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return 1 - gt.normal_cdf(z)


def spearman_test(x, y):
    rho = pearson(ranks(x), ranks(y))
    n = len(x)
    t = rho * math.sqrt((n - 2) / (1 - rho * rho)) if abs(rho) < 1 else math.inf
    return rho, normal_p(t)


def bh(pvals):
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, pvals[i] * m / rank)
        q[i] = prev
    return q


def residualize(y, controls):
    X = np.column_stack([np.ones(len(y))] + controls)
    return y - X @ np.linalg.lstsq(X, y, rcond=None)[0]


def truth_r(pit, acres, cocs, lag, drop2021):
    out = {}
    for c in cocs:
        pts = [(acres.get((c, y - lag), 0.0), v) for y, v in pit[c] if not (drop2021 and y == 2021)]
        r = gt.pearson(pts)
        if r is not None and len(pts) > 3:
            out[c] = (r, len(pts))
    return out


def heterogeneity(rs):
    z = [(math.atanh(max(min(r, 0.999), -0.999)), n - 3) for r, n in rs.values()]
    w_sum = sum(w for _, w in z)
    zbar = sum(a * w for a, w in z) / w_sum
    q = sum(w * (a - zbar) ** 2 for a, w in z)
    df = len(z) - 1
    return {
        "n_cocs": len(z),
        "pooled_r": round(math.tanh(zbar), 4),
        "mean_r": round(st.mean(r for r, _ in rs.values()), 4),
        "sd_r": round(st.pstdev(r for r, _ in rs.values()), 4),
        "cochran_q": round(q, 2),
        "df": df,
        "p_value": round(chi2_sf(q, df), 4),
        "i_squared": round(max(0.0, (q - df) / q), 3) if q else 0.0,
    }


def split_half(trials, cocs):
    odd = [st.mean(t[c][0] for t in trials[0::2]) for c in cocs]
    even = [st.mean(t[c][0] for t in trials[1::2]) for c in cocs]
    r = pearson(odd, even)
    return round(2 * r / (1 + r), 3) if r is not None else None


def main():
    pit, _ = gt.load_pit(exclude_years=set())  # the specs below decide about 2021 themselves
    acres = gt.load_fires()
    published = json.loads((DATA_DIR / "ai_vs_ground_truth.json").read_text())["by_coc"]
    cocs = sorted(r["coc_number"] for r in published)
    names = {r["coc_number"]: r["coc_name"] for r in published}

    with open(DATA_DIR / "ca_coc_covariates.csv", newline="") as f:
        cov_rows = {r["coc_number"]: r for r in csv.DictReader(f)}
    cov_names = [k for k in next(iter(cov_rows.values())) if k not in ("coc_number", "coc_name")]

    truths = {k: truth_r(pit, acres, cocs, lag, drop) for k, (lag, drop) in TRUTH_SPECS.items()}
    ai, reliability = {}, {}
    for model, cond in CONDITIONS:
        trials = load_trials(model, cond)
        if trials:
            key = f"{model}_{cond}"
            ai[key] = {c: st.mean(t[c][0] for t in trials) for c in cocs}
            reliability[key] = split_half(trials, cocs)

    outcomes = {}
    for k, rs in truths.items():
        outcomes[f"truth_{k}"] = {c: r for c, (r, _) in rs.items()}
    for k, est in ai.items():
        outcomes[f"ai_{k}"] = est
    base = truths["lag0_drop2021"]  # the published ground truth, and what the AI was asked to estimate
    for k, est in ai.items():
        outcomes[f"error_{k}"] = {c: est[c] - base[c][0] for c in cocs if c in base}
        outcomes[f"abs_error_{k}"] = {c: abs(est[c] - base[c][0]) for c in cocs if c in base}

    correlates = {}
    for name, vals in outcomes.items():
        cs = [c for c in cocs if c in vals]
        tests = []
        for cov in cov_names:
            x = [float(cov_rows[c][cov]) for c in cs]
            rho, p = spearman_test(x, [vals[c] for c in cs])
            tests.append({"covariate": cov, "spearman_rho": round(rho, 3), "p_value": round(p, 4)})
        for t, q in zip(tests, bh([t["p_value"] for t in tests])):
            t["q_value"] = round(q, 4)
        tests.sort(key=lambda t: t["p_value"])
        correlates[name] = {"n_cocs": len(cs), "n_fdr_significant": sum(t["q_value"] < 0.05 for t in tests), "tests": tests}

    # How much of the error's spread comes from each side: var(ai - truth) = var(ai) + var(truth) - 2cov.
    decomposition = {}
    for k, est in ai.items():
        a = [est[c] for c in cocs if c in base]
        g = [base[c][0] for c in cocs if c in base]
        va, vg = st.pvariance(a), st.pvariance(g)
        cov = sum((x - st.mean(a)) * (y - st.mean(g)) for x, y in zip(a, g)) / len(a)
        ve = va + vg - 2 * cov
        decomposition[k] = {"var_error": round(ve, 4), "share_from_ai": round(va / ve, 3),
                            "share_from_truth": round(vg / ve, 3), "share_from_covariance": round(-2 * cov / ve, 3)}

    # Does any place characteristic predict the AI's estimate beyond how destructive
    # and how rural the CoC is? Rank partial correlations after removing both.
    partial = {}
    for k, est in ai.items():
        y = np.array(ranks([est[c] for c in cocs]))
        ctrl = [np.array(ranks([float(cov_rows[c][v]) for c in cocs])) for v in SALIENCE_CONTROLS]
        tests = []
        for cov in cov_names:
            if cov in SALIENCE_CONTROLS:
                continue
            x = np.array(ranks([float(cov_rows[c][cov]) for c in cocs]))
            pr = float(np.corrcoef(residualize(y, ctrl), residualize(x, ctrl))[0, 1])
            df = len(cocs) - 2 - len(ctrl)
            tests.append({"covariate": cov, "partial_rho": round(pr, 3),
                          "p_value": round(normal_p(pr * math.sqrt(df / (1 - pr * pr))), 4)})
        for t, q in zip(tests, bh([t["p_value"] for t in tests])):
            t["q_value"] = round(q, 4)
        tests.sort(key=lambda t: t["p_value"])
        partial[k] = {"controls": SALIENCE_CONTROLS, "r2_from_controls": round(1 - residualize(y, ctrl).var() / y.var(), 3),
                      "n_fdr_significant": sum(t["q_value"] < 0.05 for t in tests), "tests": tests}

    # Spearman treats a 5-year r and an 18-year r as equally informative. A
    # fixed-effect meta-regression on Fisher z, weighted by n - 3, doesn't.
    metareg = {}
    for k, rs in truths.items():
        cs = sorted(rs)
        z = np.array([math.atanh(max(min(rs[c][0], 0.999), -0.999)) for c in cs])
        w = np.array([rs[c][1] - 3 for c in cs], float)
        tests = []
        for cov in cov_names:
            x = np.array([float(cov_rows[c][cov]) for c in cs])
            X = np.column_stack([np.ones(len(cs)), (x - x.mean()) / x.std()])
            xtwx = X.T @ (X * w[:, None])
            beta = np.linalg.solve(xtwx, X.T @ (w * z))
            se = math.sqrt(np.linalg.inv(xtwx)[1, 1])
            tests.append({"covariate": cov, "coef_per_sd": round(float(beta[1]), 4), "z": round(float(beta[1]) / se, 2),
                          "p_value": round(normal_p(float(beta[1]) / se), 4)})
        for t, q in zip(tests, bh([t["p_value"] for t in tests])):
            t["q_value"] = round(q, 4)
        tests.sort(key=lambda t: t["p_value"])
        metareg[k] = {"n_cocs": len(cs), "n_fdr_significant": sum(t["q_value"] < 0.05 for t in tests), "tests": tests}

    by_coc = []
    for c in cocs:
        row = {"coc_number": c, "coc_name": names[c]}
        for k, rs in truths.items():
            row[f"truth_{k}"] = round(rs[c][0], 4) if c in rs else None
            row[f"truth_{k}_n"] = rs[c][1] if c in rs else None
        for k, est in ai.items():
            row[f"ai_{k}"] = round(est[c], 4)
        by_coc.append(row)

    DEST.write_text(json.dumps({
        "methodology": __doc__.strip(),
        "truth_heterogeneity": {k: heterogeneity(rs) for k, rs in truths.items()},
        "ai_split_half_reliability": reliability,
        "error_variance_decomposition": decomposition,
        "correlates": correlates,
        "ai_partial_after_salience": partial,
        "truth_weighted_metaregression": metareg,
        "by_coc": by_coc,
    }, indent=2))

    print("ground-truth heterogeneity (does the per-CoC r vary beyond sampling noise?)")
    for k, rs in truths.items():
        h = heterogeneity(rs)
        print(f"  {k:16s} n={h['n_cocs']} mean r {h['mean_r']:+.3f}  Q={h['cochran_q']:.1f}/{h['df']}  p={h['p_value']:.3f}  I2={h['i_squared']:.2f}")
    print("AI split-half reliability:", reliability)
    print("error variance decomposition:", decomposition)
    for name, v in correlates.items():
        top = v["tests"][:3]
        print(f"  {name:32s} FDR-sig {v['n_fdr_significant']}  top: " +
              ", ".join(f"{t['covariate']} {t['spearman_rho']:+.2f} (q={t['q_value']:.3f})" for t in top))
    for k, v in partial.items():
        top = v["tests"][0]
        print(f"  partial {k:22s} R2 controls {v['r2_from_controls']:.2f}  FDR-sig {v['n_fdr_significant']}  top {top['covariate']} {top['partial_rho']:+.2f} (q={top['q_value']:.3f})")
    for k, v in metareg.items():
        top = v["tests"][0]
        print(f"  metareg {k:16s} FDR-sig {v['n_fdr_significant']}  top {top['covariate']} z={top['z']:+.2f} (q={top['q_value']:.3f})")
    print(f"-> {DEST}")


if __name__ == "__main__":
    main()
