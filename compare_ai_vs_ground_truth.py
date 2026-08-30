#!/usr/bin/env python3
"""
Diffs the AI's per-CoC wildfire -> homelessness estimates
(ai_fire_influence_estimates.json) against the real per-CoC Pearson r
computed directly from HUD PIT + CAL FIRE data
(ground_truth_fire_influence.json, lag0). This is the actual "how much
does AI exaggerate" measurement -- everything upstream just produces the
two numbers compared here.

Output: data/ai_vs_ground_truth.json
"""

import json
import pathlib

DATA_DIR = pathlib.Path(__file__).parent / "data"
GROUND_TRUTH_SRC = DATA_DIR / "ground_truth_fire_influence.json"
AI_SRC = DATA_DIR / "ai_fire_influence_estimates.json"
DEST = DATA_DIR / "ai_vs_ground_truth.json"

MIN_N = 3          # minimum CoC-year pairs before a ground-truth r is trusted at all
SIGN_EPS = 0.05     # |r| or |estimate| below this counts as "no relationship" for sign comparison
MATCH_TOL = 0.1     # within this much of ground truth r counts as "roughly matches"


def classify(gt_r, ai_r):
    gt_sign = 0 if abs(gt_r) < SIGN_EPS else (1 if gt_r > 0 else -1)
    ai_sign = 0 if abs(ai_r) < SIGN_EPS else (1 if ai_r > 0 else -1)
    if gt_sign != 0 and ai_sign != 0 and gt_sign != ai_sign:
        return "sign_flip"
    diff = abs(ai_r) - abs(gt_r)
    if diff > MATCH_TOL:
        return "exaggerates"
    if diff < -MATCH_TOL:
        return "underestimates"
    return "roughly_matches"


def pearson(points):
    n = len(points)
    if n < 2:
        return None
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    num = dx2 = dy2 = 0.0
    for x, y in points:
        dx, dy = x - mx, y - my
        num += dx * dy
        dx2 += dx * dx
        dy2 += dy * dy
    denom = (dx2 * dy2) ** 0.5
    return None if denom == 0 else num / denom


def main():
    if not GROUND_TRUTH_SRC.exists():
        raise SystemExit(f"Missing {GROUND_TRUTH_SRC}. Run compute_fire_influence.py first.")
    if not AI_SRC.exists():
        raise SystemExit(f"Missing {AI_SRC}. Run ai_estimate_influence.py first.")

    ground_truth = json.loads(GROUND_TRUTH_SRC.read_text())
    ai = json.loads(AI_SRC.read_text())

    by_coc = []
    skipped_insufficient = 0
    for est in ai["estimates"]:
        coc_num = est["coc_number"]
        gt = ground_truth["by_coc"].get(coc_num)
        if not gt or gt["lag0"]["n"] < MIN_N or gt["lag0"]["pearson_r"] is None:
            skipped_insufficient += 1
            continue
        gt_r = gt["lag0"]["pearson_r"]
        ai_r = est["estimated_correlation"]
        by_coc.append({
            "coc_number": coc_num,
            "coc_name": est["coc_name"],
            "ground_truth_r": gt_r,
            "ground_truth_n": gt["lag0"]["n"],
            "ai_estimate": ai_r,
            "ai_confidence": est["confidence"],
            "ai_reasoning": est["reasoning"],
            "signed_error": round(ai_r - gt_r, 4),
            "abs_error": round(abs(ai_r - gt_r), 4),
            "classification": classify(gt_r, ai_r),
        })

    n = len(by_coc)
    summary = {"n_compared": n, "n_skipped_insufficient_data": skipped_insufficient}
    if n:
        signed_errors = [r["signed_error"] for r in by_coc]
        abs_errors = [r["abs_error"] for r in by_coc]
        summary["mean_signed_error"] = round(sum(signed_errors) / n, 4)
        summary["mean_abs_error"] = round(sum(abs_errors) / n, 4)
        for label in ("exaggerates", "underestimates", "sign_flip", "roughly_matches"):
            count = sum(1 for r in by_coc if r["classification"] == label)
            summary[f"pct_{label}"] = round(100 * count / n, 1)
        summary["rank_agreement_r"] = pearson([(r["ground_truth_r"], r["ai_estimate"]) for r in by_coc])

    DEST.write_text(json.dumps({
        "methodology": (
            "For each CoC, ai_estimate is the model's estimated correlation (from "
            "wildfire history alone, no PIT data shown) and ground_truth_r is the "
            "real Pearson r between that CoC's annual acres burned and its "
            "same-year PIT homeless count. mean_signed_error > 0 means the model "
            "systematically overstates a positive fire->homelessness relationship "
            "versus what the data shows. classification labels each CoC as "
            "exaggerates/underestimates/sign_flip/roughly_matches "
            f"(sign_flip needs both values past +/-{SIGN_EPS}; roughly_matches needs "
            f"abs-error within {MATCH_TOL})."
        ),
        "summary": summary,
        "by_coc": sorted(by_coc, key=lambda r: -r["abs_error"]),
    }, indent=2))
    print(f"-> {DEST} ({n} CoCs compared, {skipped_insufficient} skipped for insufficient ground-truth data)")
    if n:
        print(f"   mean signed error (AI bias): {summary['mean_signed_error']:+.3f}   mean abs error: {summary['mean_abs_error']:.3f}")


if __name__ == "__main__":
    main()
