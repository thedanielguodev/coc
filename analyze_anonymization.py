#!/usr/bin/env python3
"""
Named vs. anonymous regions: does the destruction pattern survive when the
model cannot see which CoC it is estimating?

Inputs (same Nov 5 batch, neutral prompt, 10 Claude trials each):
  data/ai_estimates_claude_named_nov5.json   CoC names shown
  data/ai_estimates_claude_anon_nov5.json    names replaced by shuffled codes
Compared against the observed same-year r (2021 excluded) and structures
destroyed 2013-2024, for the 40 CoCs with a usable observed r.

Reports per condition: mean estimate, bias (SE), rank agreement with truth,
Spearman with structures, gaps by destruction group with a one-sided sign-flip
test on the 1,000+ group, split-half reliability, and the input-feature
control (partial rho of structures after the 5 acreage features). Then the
paired named-minus-anonymous change per CoC, and a CoC bootstrap of the drop
in the structures rho.

Output: data/anonymization_test.json
"""

import csv
import itertools
import json
import pathlib
import random
import statistics as st

import numpy as np

from analyze_input_feature_control import FEATURES, analyze, prompt_features, rk
from compare_ai_conditions import ranks

DATA_DIR = pathlib.Path(__file__).parent / "data"
DEST = DATA_DIR / "anonymization_test.json"
COND = {"named": "ai_estimates_claude_named_nov5.json", "anon": "ai_estimates_claude_anon_nov5.json"}
random.seed(0)
np.random.seed(0)


def spearman(a, b):
    return float(np.corrcoef(ranks(list(a)), ranks(list(b)))[0, 1])


def sign_flip_p(v):
    """One-sided exact sign-flip test that mean(v) > 0."""
    obs, hits, n = sum(v), 0, 0
    for signs in itertools.product((1, -1), repeat=len(v)):
        n += 1
        hits += sum(s * x for s, x in zip(signs, v)) >= obs - 1e-12
    return hits / n


def load(fn, cocs):
    trials = json.loads((DATA_DIR / fn).read_text())["trials"]
    per = {c: [] for c in cocs}
    for t in trials:
        for r in t:
            if r["coc_number"] in per:
                per[r["coc_number"]].append(float(r["estimated_correlation"]))
    half = lambda idx: [st.mean(per[c][i] for i in idx) for c in cocs]
    n = len(trials)
    a, b = half(range(0, n, 2)), half(range(1, n, 2))
    r = float(np.corrcoef(a, b)[0, 1])
    return [st.mean(per[c]) for c in cocs], round(2 * r / (1 + r), 3), sum(v < 0 for t in trials for v in [x["estimated_correlation"] for x in t])


def main():
    het = json.loads((DATA_DIR / "error_heterogeneity.json").read_text())["by_coc"]
    cocs = [r["coc_number"] for r in het]
    truth = [r["truth_lag0_drop2021"] for r in het]
    cov = {r["coc_number"]: float(r["structures_destroyed_total"]) for r in csv.DictReader(open(DATA_DIR / "ca_coc_covariates.csv"))}
    s = [cov[c] for c in cocs]
    group = ["hi" if x >= 1000 else "mid" if x >= 100 else "lo" for x in s]
    feats = prompt_features()
    F = [rk([feats[c][f] for c in cocs]) for f in FEATURES]
    out = {"n_cocs": len(cocs), "observed_mean_r": round(st.mean(truth), 4),
           "observed_rho_structures": round(spearman(truth, s), 3), "conditions": {}}
    est = {}
    for k, fn in COND.items():
        e, rel, neg = load(fn, cocs)
        est[k] = e
        gap = [a - b for a, b in zip(e, truth)]
        gg = {g: [x for x, gr in zip(gap, group) if gr == g] for g in ("lo", "mid", "hi")}
        out["conditions"][k] = {
            "mean_estimate": round(st.mean(e), 4), "bias": round(st.mean(gap), 4),
            "bias_se": round(st.stdev(gap) / len(gap) ** 0.5, 4),
            "rank_agreement_rho": round(spearman(e, truth), 3), "rho_structures": round(spearman(e, s), 3),
            "gap_by_group": {g: round(st.mean(v), 3) for g, v in gg.items()},
            "n_by_group": {g: len(v) for g, v in gg.items()},
            "p_hi_gap_above_zero": round(sign_flip_p(gg["hi"]), 4),
            "split_half_reliability": rel, "n_negative_estimates": neg,
            "input_control_estimate": analyze(e, s, F), "input_control_error": analyze(gap, s, F)}
    d = [a - b for a, b in zip(est["anon"], est["named"])]
    rho_drop = []
    idx = np.arange(len(cocs))
    for _ in range(5000):
        b = np.random.choice(idx, len(idx))
        sb = [s[i] for i in b]
        rho_drop.append(spearman([est["named"][i] for i in b], sb) - spearman([est["anon"][i] for i in b], sb))
    out["anon_minus_named"] = {
        "mean_change": round(st.mean(d), 4), "se": round(st.stdev(d) / len(d) ** 0.5, 4),
        "n_lower": sum(x < 0 for x in d), "n_higher": sum(x > 0 for x in d),
        "rho_named_vs_anon_estimates": round(spearman(est["named"], est["anon"]), 3),
        "rho_change_vs_structures": round(spearman(d, s), 3),
        "rho_structures_drop": round(out["conditions"]["named"]["rho_structures"] - out["conditions"]["anon"]["rho_structures"], 3),
        "rho_structures_drop_boot95": [round(float(np.percentile(rho_drop, q)), 3) for q in (2.5, 97.5)],
        "butte_named": round(est["named"][cocs.index("CA-519")], 3), "butte_anon": round(est["anon"][cocs.index("CA-519")], 3),
        "butte_rank_named": int(sorted(est["named"], reverse=True).index(est["named"][cocs.index("CA-519")]) + 1),
        "butte_rank_anon": int(sorted(est["anon"], reverse=True).index(est["anon"][cocs.index("CA-519")]) + 1)}
    out["by_coc"] = [{"coc_number": c, "structures": s[i], "truth": truth[i], "named": round(est["named"][i], 3),
                      "anon": round(est["anon"][i], 3)} for i, c in enumerate(cocs)]
    DEST.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "by_coc"}, indent=1))


if __name__ == "__main__":
    main()
