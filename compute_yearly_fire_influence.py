#!/usr/bin/env python3
"""
Year-by-year cross-sectional fire -> homelessness correlation: instead of
pooling all 18 years together (compute_fire_influence.py), compute a
separate Pearson r *within* each single year, across all 44 CoCs. This
tests whether the pooled null result is hiding a real effect that only
shows up in specific catastrophic-fire years (e.g. 2018 Camp Fire, 2017
Tubbs Fire, 2020's record acreage) -- rather than averaging every year
together and never looking at any one of them on its own.

Also flags single-CoC sensitivity: with only 40-44 points per year, one
outlier region (typically Los Angeles, which is simultaneously the
largest homeless population in the state and periodically has large
fire years for reasons unrelated to that) can manufacture an apparent
correlation on its own. leave_one_out_max_drop reports how much a
year's r changes when its single largest-acreage CoC is excluded, so a
result driven by one region is visible rather than hidden.

Output: data/yearly_fire_influence.json
"""

import csv
import json
import math
import pathlib
from collections import defaultdict

DATA_DIR = pathlib.Path(__file__).parent / "data"
PIT_SRC = DATA_DIR / "ca_coc_pit_by_year.csv"
FIRE_SRC = DATA_DIR / "ca_fires_by_coc_year.csv"
DEST = DATA_DIR / "yearly_fire_influence.json"

METRIC = "Overall Homeless"
YEARS = range(2007, 2025)


def load_pit():
    by_year = defaultdict(dict)  # year -> coc_number -> homeless
    with open(PIT_SRC, newline="") as f:
        for row in csv.DictReader(f):
            val = row[METRIC]
            if val == "":
                continue
            by_year[int(row["year"])][row["coc_number"]] = float(val)
    return by_year


def load_fires():
    acres = defaultdict(dict)  # year -> coc_number -> acres_burned
    with open(FIRE_SRC, newline="") as f:
        for row in csv.DictReader(f):
            acres[int(row["year"])][row["coc_number"]] = float(row["acres_burned"])
    return acres


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
    denom = math.sqrt(dx2 * dy2)
    return None if denom == 0 else num / denom


def erf(x):
    sign = -1 if x < 0 else 1
    x = abs(x)
    a1, a2, a3, a4, a5, p = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429, 0.3275911
    t = 1 / (1 + p * x)
    y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return sign * y


def normal_cdf(z):
    return 0.5 * (1 + erf(z / math.sqrt(2)))


def pearson_p_value(r, n):
    if r is None or n < 3 or abs(r) >= 1:
        return None
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return 2 * (1 - normal_cdf(abs(t)))


def main():
    pit_by_year = load_pit()
    acres_by_year = load_fires()

    results = []
    for year in YEARS:
        homeless = pit_by_year.get(year, {})
        fire_year_acres = acres_by_year.get(year, {})
        rows = []  # (coc_number, acres, homeless)
        for coc_num, val in homeless.items():
            a = fire_year_acres.get(coc_num, 0.0)
            rows.append((coc_num, a, val))
        points = [(a, v) for _, a, v in rows]
        n = len(points)
        r = pearson(points)
        p = pearson_p_value(r, n)

        # Leave-one-out: drop the single largest-acreage CoC this year and
        # recompute, to surface whether one region is doing all the work.
        loo_r = None
        loo_dropped_coc = None
        if rows:
            rows_sorted = sorted(rows, key=lambda t: -t[1])
            top_coc = rows_sorted[0][0]
            trimmed_points = [(a, v) for coc_num, a, v in rows if coc_num != top_coc]
            loo_r = pearson(trimmed_points)
            loo_dropped_coc = top_coc

        results.append({
            "year": year,
            "n": n,
            "pearson_r": round(r, 4) if r is not None else None,
            "p_value": round(p, 5) if p is not None else None,
            "significant_p05": bool(p is not None and p < 0.05),
            "leave_one_out_r": round(loo_r, 4) if loo_r is not None else None,
            "leave_one_out_dropped_coc": loo_dropped_coc,
        })

    n_years = len(results)
    bonferroni_alpha = 0.05 / n_years
    for r in results:
        r["significant_bonferroni"] = bool(
            r["p_value"] is not None and r["p_value"] < bonferroni_alpha
        )

    out = {
        "metric": METRIC,
        "methodology": (
            "For each year, a single cross-sectional Pearson r is computed across "
            "all CoCs with a PIT count that year, pairing that CoC's same-year "
            "acres burned (0 if no major fire) against its homeless count -- i.e. "
            "44 separate single-year snapshots instead of one pooled 18-year "
            "regression. significant_p05 flags r's with an uncorrected p < 0.05; "
            "significant_bonferroni applies a Bonferroni correction for testing "
            f"{n_years} years at once (alpha = 0.05/{n_years} = {bonferroni_alpha:.5f}), "
            "since testing many years is expected to produce a small number of "
            "false positives by chance alone. leave_one_out_r recomputes r after "
            "dropping that year's single largest-acreage CoC, to check whether an "
            "apparent year-level correlation is actually driven by one outlier "
            "region (typically Los Angeles) rather than a real pattern."
        ),
        "years": results,
    }
    DEST.write_text(json.dumps(out, indent=2))
    n_sig_uncorrected = sum(1 for r in results if r["significant_p05"])
    n_sig_corrected = sum(1 for r in results if r["significant_bonferroni"])
    print(f"-> {DEST} ({n_years} years)")
    print(f"   {n_sig_uncorrected}/{n_years} years significant at p<0.05 (uncorrected)")
    print(f"   {n_sig_corrected}/{n_years} years significant after Bonferroni correction")


if __name__ == "__main__":
    main()
