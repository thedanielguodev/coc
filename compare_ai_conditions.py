#!/usr/bin/env python3
"""
Compare every AI estimation run (model x prompt condition) against the same
per-CoC ground truth, with identical metrics, so the conditions can be read
side by side:

  claude  baseline      data/ai_fire_influence_estimates.json (original 10 trials)
  claude  pit_informed  data/ai_estimates_claude_pit_informed.json
  gemini  baseline      data/ai_estimates_gemini_baseline.json
  gemini  pit_informed  data/ai_estimates_gemini_pit_informed.json

Ground truth is each CoC's same-year Pearson r (acres burned vs. PIT count),
taken from ai_vs_ground_truth.json's by_coc (the 41 CoCs with enough data).
Missing files are skipped.

Output: data/ai_condition_comparison.json
"""

import json
import math
import pathlib
import statistics as st

DATA_DIR = pathlib.Path(__file__).parent / "data"
DEST = DATA_DIR / "ai_condition_comparison.json"


def pearson(a, b):
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return None if den == 0 else num / den


def ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def load_trials(model, condition):
    """Return a list of trials, each a dict coc_number -> (estimate, confidence)."""
    if model == "claude" and condition == "baseline":
        path = DATA_DIR / "ai_fire_influence_estimates.json"
        if not path.exists():
            return None
        ests = json.loads(path.read_text())["estimates"]
        n = len(ests[0]["estimated_correlation_trials"])
        return [{e["coc_number"]: (e["estimated_correlation_trials"][i], e["confidence_trials"][i]) for e in ests} for i in range(n)]
    path = DATA_DIR / f"ai_estimates_{model}_{condition}.json"
    if not path.exists():
        return None
    return [{r["coc_number"]: (float(r["estimated_correlation"]), r.get("confidence")) for r in t}
            for t in json.loads(path.read_text())["trials"]]


def summarize(trials, truth):
    cocs = sorted(truth)
    mean_est = {c: st.mean(t[c][0] for t in trials) for c in cocs}
    est = [mean_est[c] for c in cocs]
    gt = [truth[c] for c in cocs]
    err = [e - g for e, g in zip(est, gt)]
    all_vals = [v for t in trials for v, _ in t.values()]
    by_conf = {}
    for t in trials:
        for c in cocs:
            v, conf = t[c]
            by_conf.setdefault(conf, []).append(abs(v - truth[c]))
    return {
        "n_trials": len(trials),
        "n_cocs": len(cocs),
        "mean_estimate": round(st.mean(est), 4),
        "mean_signed_error": round(st.mean(err), 4),
        "mean_signed_error_se": round(st.stdev(err) / math.sqrt(len(err)), 4),
        "mean_abs_error": round(st.mean(abs(e) for e in err), 4),
        "agreement_pearson_r": round(pearson(est, gt), 4),
        "agreement_spearman_rho": round(pearson(ranks(est), ranks(gt)), 4),
        "n_estimates": len(all_vals),
        "n_negative_estimates": sum(v < 0 for v in all_vals),
        "mean_trial_sd": round(st.mean(st.pstdev([t[c][0] for t in trials]) for c in cocs), 4),
        "abs_error_by_confidence": {k: {"n": len(v), "mean": round(st.mean(v), 4)} for k, v in sorted(by_conf.items()) if k},
        "_mean_estimate_by_coc": mean_est,
    }


def main():
    truth = {r["coc_number"]: r["ground_truth_r"] for r in json.loads((DATA_DIR / "ai_vs_ground_truth.json").read_text())["by_coc"]}
    obs_mean = st.mean(truth.values())
    results = {}
    for model in ("claude", "gemini"):
        for condition in ("baseline", "pit_informed"):
            trials = load_trials(model, condition)
            if trials:
                results[f"{model}_{condition}"] = summarize(trials, truth)

    # Paired effect of adding the PIT description, per model (same CoCs, same truth).
    for model in ("claude", "gemini"):
        a, b = results.get(f"{model}_baseline"), results.get(f"{model}_pit_informed")
        if a and b:
            d = [b["_mean_estimate_by_coc"][c] - a["_mean_estimate_by_coc"][c] for c in truth]
            results[f"{model}_pit_effect"] = {
                "mean_change": round(st.mean(d), 4),
                "se": round(st.stdev(d) / math.sqrt(len(d)), 4),
                "n_cocs_lower": sum(x < 0 for x in d),
                "n_cocs": len(d),
            }
    for v in results.values():
        v.pop("_mean_estimate_by_coc", None)

    DEST.write_text(json.dumps({
        "methodology": (
            "Each condition's per-CoC estimate is the mean across its trials, compared with that CoC's observed "
            "same-year Pearson r (acres burned vs. PIT count). mean_signed_error > 0 means overstating the "
            "relationship. pit_effect is the paired per-CoC change in mean estimate from adding a description of "
            "what the PIT count measures."
        ),
        "observed_mean_r": round(obs_mean, 4),
        "results": results,
    }, indent=2))
    print(f"observed mean per-CoC r = {obs_mean:.3f}")
    for k, v in results.items():
        if "pit_effect" in k:
            print(f"{k:22s} change {v['mean_change']:+.3f} (se {v['se']:.3f}), lower in {v['n_cocs_lower']}/{v['n_cocs']} CoCs")
        else:
            print(f"{k:22s} mean est {v['mean_estimate']:.3f}  bias {v['mean_signed_error']:+.3f} (se {v['mean_signed_error_se']:.3f})  "
                  f"MAE {v['mean_abs_error']:.3f}  rho {v['agreement_spearman_rho']:+.3f}  negative {v['n_negative_estimates']}/{v['n_estimates']}")
    print(f"-> {DEST}")


if __name__ == "__main__":
    main()
