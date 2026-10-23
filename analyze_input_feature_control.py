#!/usr/bin/env python3
"""
Do the AI's estimates follow structures destroyed, or just the fire-history
numbers the prompt actually contained?

The models saw only each CoC's (year, acres burned) list. Structures destroyed
(DINS) was never shown, so a high correlation with it could simply reflect
bigger or more variable acreage. This script rebuilds the features computable
from the prompt input (total acres, peak-year acres, number of fire years,
SD of annual acres, total fire count) and asks, on ranks across the 40 CoCs:

  1. How much of each condition's estimate do the input features alone explain?
  2. Does structures destroyed add to them (nested R2 change, exact
     permutation p from shuffling the structures residual)?
  3. Same for the signed error (estimate - observed).
  4. Leave-one-out out-of-sample R2 with and without structures (stability of the increment).
  5. Partial Spearman of estimate with structures after removing the inputs,
     plus a leave-Butte-out refit.

Output: data/input_feature_control.json
"""

import csv
import json
import pathlib
import random
import statistics as st
from collections import defaultdict

import numpy as np

from compare_ai_conditions import ranks

DATA_DIR = pathlib.Path(__file__).parent / "data"
DEST = DATA_DIR / "input_feature_control.json"
CONDITIONS = ["claude_baseline", "claude_pit_informed", "claude_baseline_rerun", "claude_neutral",
              "gemini_baseline", "gemini_pit_informed", "gemini_neutral"]
FEATURES = ["total_acres", "peak_acres", "n_fire_years", "sd_acres", "total_fire_count"]
N_PERM = 20000
random.seed(0)
np.random.seed(0)


def prompt_features():
    hist = defaultdict(list)
    for r in csv.DictReader(open(DATA_DIR / "ca_fires_by_coc_year.csv")):
        hist[r["coc_number"]].append((float(r["acres_burned"]), float(r["fire_count"])))
    out = {}
    for c, rows in hist.items():
        a = [x for x, _ in rows]
        out[c] = {"total_acres": sum(a), "peak_acres": max(a), "n_fire_years": len(a),
                  "sd_acres": st.pstdev(a) if len(a) > 1 else 0.0, "total_fire_count": sum(f for _, f in rows)}
    return out


def r2(y, cols):
    X = np.column_stack([np.ones(len(y))] + cols)
    res = y - X @ np.linalg.lstsq(X, y, rcond=None)[0]
    return 1 - res.var() / y.var(), res


def rk(v):
    return np.array(ranks(list(v)), float)


def loo_r2(y, cols):
    """Out-of-sample R2 from leave-one-out prediction of the rank outcome."""
    X = np.column_stack([np.ones(len(y))] + cols)
    pred = np.empty(len(y))
    for i in range(len(y)):
        m = np.arange(len(y)) != i
        pred[i] = X[i] @ np.linalg.lstsq(X[m], y[m], rcond=None)[0]
    return 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()


def analyze(y, x, F):
    """y outcome, x structures, F list of input-feature rank columns (all ranked)."""
    y, x = rk(y), rk(x)
    r2_in, res_y = r2(y, F)
    r2_both, _ = r2(y, F + [x])
    r2_x, _ = r2(y, [x])
    _, res_x = r2(x, F)
    partial = float(np.corrcoef(res_y, res_x)[0, 1])
    # exact-ish permutation of the structures residual (Freedman-Lane style)
    obs = abs(partial)
    hits = sum(abs(np.corrcoef(res_y, np.random.permutation(res_x))[0, 1]) >= obs for _ in range(N_PERM))
    loo_in, loo_both = loo_r2(y, F), loo_r2(y, F + [x])
    return {"loo_r2_inputs_only": round(loo_in, 3), "loo_r2_inputs_plus_structures": round(loo_both, 3),
            "loo_delta_r2_structures": round(loo_both - loo_in, 3), "r2_inputs_only": round(r2_in, 3), "r2_structures_only": round(r2_x, 3),
            "r2_inputs_plus_structures": round(r2_both, 3), "delta_r2_structures": round(r2_both - r2_in, 3),
            "partial_rho_structures": round(partial, 3), "perm_p_two_sided": round((hits + 1) / (N_PERM + 1), 4)}


def main():
    het = json.loads((DATA_DIR / "error_heterogeneity.json").read_text())["by_coc"]
    cov = {r["coc_number"]: float(r["structures_destroyed_total"]) for r in csv.DictReader(open(DATA_DIR / "ca_coc_covariates.csv"))}
    feats = prompt_features()
    out = {"features": FEATURES, "n_cocs": len(het), "conditions": {}}

    def run(rows):
        cocs = [r["coc_number"] for r in rows]
        F = [rk([feats[c][f] for c in cocs]) for f in FEATURES]
        x = [cov[c] for c in cocs]
        res = {}
        for k in CONDITIONS:
            est = [r["ai_" + k] for r in rows]
            err = [r["ai_" + k] - r["truth_lag0_drop2021"] for r in rows]
            res[k] = {"estimate": analyze(est, x, F), "error": analyze(err, x, F)}
        return res, F, x

    res, F, x = run(het)
    cocs = [r["coc_number"] for r in het]
    out["conditions"] = res
    out["spearman_structures_vs_each_input"] = {
        f: round(float(np.corrcoef(rk(x), F[i])[0, 1]), 3) for i, f in enumerate(FEATURES)}
    res_nb, _, _ = run([r for r in het if r["coc_number"] != "CA-519"])
    out["leave_out_butte_CA-519"] = res_nb
    DEST.write_text(json.dumps(out, indent=1))
    for k in CONDITIONS:
        e, g = res[k]["estimate"], res[k]["error"]
        print(f"{k:22s} est: inputs R2 {e['r2_inputs_only']:.2f} +struct {e['r2_inputs_plus_structures']:.2f} "
              f"partial rho {e['partial_rho_structures']:+.2f} p={e['perm_p_two_sided']:.4f} | "
              f"err: partial {g['partial_rho_structures']:+.2f} p={g['perm_p_two_sided']:.4f}"
              f" | noButte est partial {res_nb[k]['estimate']['partial_rho_structures']:+.2f}")
    print(out["spearman_structures_vs_each_input"])


if __name__ == "__main__":
    main()
