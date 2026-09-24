#!/usr/bin/env python3
"""
Two-way fixed-effects panel regression of PIT homeless count on fire exposure,
as a stricter version of compute_fire_influence.py's pooled Pearson r.

The pooled r treats every CoC-year as an independent observation, which they
aren't: Los Angeles is large every year, and a statewide shock (a recession,
a change in HUD counting guidance) moves every CoC in the same year. This
script instead asks: when a CoC has unusually high fire exposure *relative to
its own history*, net of whatever happened statewide that year, is its PIT
count unusually high too?

Model, per exposure variable and lag:
    y_ct = b * x_c,t-lag + a_c (CoC fixed effect) + g_t (year fixed effect) + e_ct
estimated by Frisch-Waugh (alternating two-way demeaning, then OLS of the
demeaned y on the demeaned x), with standard errors clustered by CoC (CR1
small-sample correction). Run in log1p (elasticity-like) and level forms.

Exposures: acres burned (PIT years 2007-2024) and CAL FIRE DINS structures
destroyed (2013-2024, first year of DINS coverage; lag1 therefore starts 2014). CoC-years with no fire or no
DINS record count as 0, same as the other ground-truth scripts.

p-values use the same normal approximation as the other ground-truth scripts;
with 44 clusters a t(43) reference distribution would give slightly larger p-values.

Output: data/panel_fe_influence.json
"""

import csv
import json
import math
import pathlib

DATA_DIR = pathlib.Path(__file__).parent / "data"
PIT_SRC = DATA_DIR / "ca_coc_pit_by_year.csv"
FIRE_SRC = DATA_DIR / "ca_fires_by_coc_year.csv"
DINS_SRC = DATA_DIR / "ca_structures_damage_by_coc_year.csv"
DEST = DATA_DIR / "panel_fe_influence.json"

METRIC = "Overall Homeless"

EXPOSURES = {
    "acres_burned": (FIRE_SRC, "acres_burned", 2000),  # FRAP pull starts 2000; PIT starts 2007
    "structures_destroyed": (DINS_SRC, "structures_destroyed", 2013),
}


def load_pit():
    pit = {}
    with open(PIT_SRC, newline="") as f:
        for row in csv.DictReader(f):
            if row[METRIC] != "":
                pit[(row["coc_number"], int(row["year"]))] = float(row[METRIC])
    return pit


def load_exposure(path, col):
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out[(row["coc_number"], int(row["year"]))] = float(row[col])
    return out


def demean_two_way(values, cocs, years, tol=1e-10, max_iter=10000):
    """Alternately subtract CoC means and year means until stable (handles an unbalanced panel)."""
    v = list(values)
    groups = []
    for keys in (cocs, years):
        g = {}
        for i, k in enumerate(keys):
            g.setdefault(k, []).append(i)
        groups.append(list(g.values()))
    for _ in range(max_iter):
        biggest = 0.0
        for g in groups:
            for idx in g:
                m = sum(v[i] for i in idx) / len(idx)
                biggest = max(biggest, abs(m))
                for i in idx:
                    v[i] -= m
        if biggest < tol:
            break
    return v


# Abramowitz & Stegun 7.1.26 approximation, matching compute_fire_influence.py's erf().
def erf(x):
    sign = -1 if x < 0 else 1
    x = abs(x)
    a1, a2, a3, a4, a5, p = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429, 0.3275911
    t = 1 / (1 + p * x)
    y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return sign * y


def normal_cdf(z):
    return 0.5 * (1 + erf(z / math.sqrt(2)))


def fe_regression(pit, exposure, min_year, lag, log):
    rows = [
        (coc, year, pit[(coc, year)], exposure.get((coc, year - lag), 0.0))
        for (coc, year) in sorted(pit)
        if year - lag >= min_year
    ]
    tf = math.log1p if log else (lambda v: v)
    cocs = [r[0] for r in rows]
    years = [r[1] for r in rows]
    y = demean_two_way([tf(r[2]) for r in rows], cocs, years)
    x = demean_two_way([tf(r[3]) for r in rows], cocs, years)

    sxx = sum(xi * xi for xi in x)
    b = sum(xi * yi for xi, yi in zip(x, y)) / sxx
    resid = [yi - b * xi for xi, yi in zip(x, y)]

    score = {}
    for c, xi, ei in zip(cocs, x, resid):
        score[c] = score.get(c, 0.0) + xi * ei
    n, g = len(rows), len(score)
    k = 1 + len(set(cocs)) + len(set(years)) - 1  # slope + CoC dummies + year dummies (one dropped)
    correction = (g / (g - 1)) * ((n - 1) / (n - k))
    se = math.sqrt(correction * sum(s * s for s in score.values())) / sxx
    p = 2 * (1 - normal_cdf(abs(b / se)))
    return {
        "n": n,
        "n_clusters": g,
        "years": [min(years), max(years)],
        "coef": round(b, 6),
        "se_clustered": round(se, 6),
        "p_value": round(p, 4),
    }


def main():
    pit = load_pit()
    results = {}
    for name, (path, col, min_year) in EXPOSURES.items():
        exposure = load_exposure(path, col)
        results[name] = {
            f"lag{lag}_{form}": fe_regression(pit, exposure, min_year, lag, form == "log")
            for lag in (0, 1)
            for form in ("log", "level")
        }

    DEST.write_text(json.dumps({
        "metric": METRIC,
        "methodology": (
            "Two-way fixed-effects OLS: PIT homeless count on fire exposure within "
            "the CoC's boundary, with CoC and year fixed effects, standard errors "
            "clustered by CoC (CR1). 'log' uses log1p of both sides (coef ~ "
            "elasticity: % change in homeless count per % change in exposure); "
            "'level' uses raw counts (coef = additional homeless per acre or per "
            "structure destroyed). lag1 pairs exposure in year t-1 with the PIT "
            "count in year t. Tests within-CoC variation over time rather than the "
            "pooled cross-section compute_fire_influence.py uses."
        ),
        "results": results,
    }, indent=2))
    for name, models in results.items():
        for key, m in models.items():
            print(f"{name:21s} {key:10s} coef={m['coef']:+.5f}  se={m['se_clustered']:.5f}  p={m['p_value']:.3f}  n={m['n']}")
    print(f"-> {DEST}")


if __name__ == "__main__":
    main()
