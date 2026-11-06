#!/usr/bin/env python3
"""
Same-batch Gemini comparison: original vs neutral prompt (framing, now matched)
and named vs anonymous regions (name recognition), all run on 2026-11-05.

Main batch: data/ai_estimates_gemini_{baseline,neutral,anon_neutral}_nov6.json
(10 trials each). Replication: the _nov files (6 trials each, same day).
Statistics mirror analyze_anonymization.py.

Output: data/gemini_matched_test.json
"""

import csv
import json
import pathlib
import statistics as st

import numpy as np

from analyze_anonymization import load, sign_flip_p, spearman
from analyze_input_feature_control import FEATURES, analyze, prompt_features, rk

DATA_DIR = pathlib.Path(__file__).parent / "data"
DEST = DATA_DIR / "gemini_matched_test.json"
np.random.seed(0)


def run(suffix):
    het = json.loads((DATA_DIR / "error_heterogeneity.json").read_text())["by_coc"]
    cocs = [r["coc_number"] for r in het]
    truth = [r["truth_lag0_drop2021"] for r in het]
    cov = {r["coc_number"]: float(r["structures_destroyed_total"]) for r in csv.DictReader(open(DATA_DIR / "ca_coc_covariates.csv"))}
    s = [cov[c] for c in cocs]
    group = ["hi" if x >= 1000 else "mid" if x >= 100 else "lo" for x in s]
    feats = prompt_features()
    F = [rk([feats[c][f] for c in cocs]) for f in FEATURES]
    out, est = {"conditions": {}}, {}
    for k in ("baseline", "neutral", "anon_neutral"):
        fn = f"ai_estimates_gemini_{k}{suffix}.json"
        e, rel, neg = load(fn, cocs)
        est[k] = e
        gap = [a - b for a, b in zip(e, truth)]
        gg = {g: [x for x, gr in zip(gap, group) if gr == g] for g in ("lo", "mid", "hi")}
        ic = analyze(e, s, F)
        out["conditions"][k] = {
            "n_trials": len(json.loads((DATA_DIR / fn).read_text())["trials"]),
            "mean_estimate": round(st.mean(e), 4), "bias": round(st.mean(gap), 4),
            "bias_se": round(st.stdev(gap) / len(gap) ** 0.5, 4),
            "rank_agreement_rho": round(spearman(e, truth), 3), "rho_structures": round(spearman(e, s), 3),
            "gap_by_group": {g: round(st.mean(v), 3) for g, v in gg.items()},
            "p_hi_gap_above_zero": round(sign_flip_p(gg["hi"]), 4),
            "split_half_reliability": rel, "n_negative_estimates": neg,
            "partial_rho_structures": ic["partial_rho_structures"], "partial_p": ic["perm_p_two_sided"],
            "loo_r2_gain": ic["loo_delta_r2_structures"],
            "butte": round(e[cocs.index("CA-519")], 3),
            "butte_rank": int(sorted(e, reverse=True).index(e[cocs.index("CA-519")]) + 1)}

    def paired(a, b):
        d = [x - y for x, y in zip(est[a], est[b])]
        boot = []
        idx = np.arange(len(cocs))
        for _ in range(5000):
            i = np.random.choice(idx, len(idx))
            sb = [s[j] for j in i]
            boot.append(spearman([est[b][j] for j in i], sb) - spearman([est[a][j] for j in i], sb))
        return {"mean_change": round(st.mean(d), 4), "se": round(st.stdev(d) / len(d) ** 0.5, 4),
                "n_lower": sum(x < 0 for x in d), "n_higher": sum(x > 0 for x in d),
                "rho_structures_drop": round(spearman(est[b], s) - spearman(est[a], s), 3),
                "rho_structures_drop_boot95": [round(float(np.percentile(boot, q)), 3) for q in (2.5, 97.5)],
                "rho_change_vs_structures": round(spearman(d, s), 3)}
    out["neutral_minus_baseline"] = paired("neutral", "baseline")
    out["anon_minus_named"] = paired("anon_neutral", "neutral")
    return out


def main():
    res = {"main_nov6_10_trials": run("_nov6"), "replication_nov_6_trials": run("_nov")}
    DEST.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
