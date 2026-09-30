#!/usr/bin/env python3
"""
Ground-truth statistical methodology for fire -> homelessness influence,
computed directly from HUD PIT counts and CAL FIRE FRAP acreage already
joined to CoC regions (data/ca_fires_by_coc_year.csv). Mirrors the Pearson
r / Spearman rho / linear-fit math in site/index.html so these numbers
match what the dashboard's pooled statewide correlation chart shows, but
adds a per-CoC breakdown (the site only computes one pooled statewide
figure) so an AI's per-CoC estimate (see ai_estimate_influence.py) can be
checked against a real per-CoC statistic instead of one aggregate number.

Output: data/ground_truth_fire_influence.json
"""

import csv
import json
import math
import pathlib
from collections import defaultdict

DATA_DIR = pathlib.Path(__file__).parent / "data"
PIT_SRC = DATA_DIR / "ca_coc_pit_by_year.csv"
FIRE_SRC = DATA_DIR / "ca_fires_by_coc_year.csv"
DEST = DATA_DIR / "ground_truth_fire_influence.json"

METRIC = "Overall Homeless"
MIN_FIRE_YEAR = 2000
# HUD let CoCs skip the 2021 unsheltered count (COVID-19); 36 of 44 CA CoCs
# report 0 unsheltered that year, so 2021 totals are not comparable.
EXCLUDE_PIT_YEARS = {2021}


def load_pit(exclude_years=EXCLUDE_PIT_YEARS):
    by_coc = defaultdict(list)
    names = {}
    with open(PIT_SRC, newline="") as f:
        for row in csv.DictReader(f):
            val = row[METRIC]
            if val == "" or int(row["year"]) in exclude_years:
                continue
            by_coc[row["coc_number"]].append((int(row["year"]), float(val)))
            names[row["coc_number"]] = row["coc_name"]
    return by_coc, names


def load_fires():
    acres = {}
    with open(FIRE_SRC, newline="") as f:
        for row in csv.DictReader(f):
            acres[(row["coc_number"], int(row["year"]))] = float(row["acres_burned"])
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


def rank_of(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman(points):
    if len(points) < 2:
        return None
    rx = rank_of([p[0] for p in points])
    ry = rank_of([p[1] for p in points])
    return pearson(list(zip(rx, ry)))


# Abramowitz & Stegun 7.1.26 approximation, matching site/index.html's erf().
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


def linear_fit(points):
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    num = den = 0.0
    for x, y in points:
        num += (x - mx) * (y - my)
        den += (x - mx) * (x - mx)
    slope = 0.0 if den == 0 else num / den
    intercept = my - slope * mx
    return slope, intercept


def strength(r):
    if r is None:
        return "n/a"
    a = abs(r)
    if a >= 0.5:
        return "strong"
    if a >= 0.3:
        return "moderate"
    if a >= 0.1:
        return "weak"
    return "negligible"


def build_points(rows, acres, coc_num, lag):
    points = []
    for year, val in rows:
        fire_year = year - lag
        if fire_year < MIN_FIRE_YEAR:
            continue
        x = acres.get((coc_num, fire_year), 0.0)
        points.append((x, val))
    return points


def stats_for(points):
    n = len(points)
    r = pearson(points)
    rho = spearman(points)
    p = pearson_p_value(r, n)
    slope, intercept = linear_fit(points) if n >= 2 else (None, None)
    mean_acres = sum(pt[0] for pt in points) / n if n else None
    mean_metric = sum(pt[1] for pt in points) / n if n else None
    return {
        "n": n,
        "pearson_r": round(r, 4) if r is not None else None,
        "spearman_rho": round(rho, 4) if rho is not None else None,
        "p_value": round(p, 5) if p is not None else None,
        "slope": round(slope, 6) if slope is not None else None,
        "intercept": round(intercept, 3) if intercept is not None else None,
        "strength": strength(r),
        "mean_acres_burned": round(mean_acres, 1) if mean_acres is not None else None,
        "mean_homeless": round(mean_metric, 1) if mean_metric is not None else None,
    }


def main():
    pit_by_coc, names = load_pit()
    acres = load_fires()

    by_coc = {}
    all_points_lag0, all_points_lag1 = [], []
    for coc_num, rows in sorted(pit_by_coc.items()):
        lag0_points = build_points(rows, acres, coc_num, 0)
        lag1_points = build_points(rows, acres, coc_num, 1)
        all_points_lag0.extend(lag0_points)
        all_points_lag1.extend(lag1_points)
        by_coc[coc_num] = {
            "coc_name": names[coc_num],
            "lag0": stats_for(lag0_points),
            "lag1": stats_for(lag1_points),
        }

    result = {
        "metric": METRIC,
        "methodology": (
            "Pearson r / Spearman rho / least-squares fit between acres burned by "
            "major fires (>=1,000 acres) within a CoC's boundary and that CoC's HUD "
            "Point-in-Time homeless count, pooled across all available years. lag0 "
            "pairs same-year fire acreage with the PIT count; lag1 pairs a year's "
            "fire acreage with next year's PIT count. Same math as the pooled "
            "statewide chart in site/index.html, computed here per-CoC as well so "
            "an AI's per-CoC estimate can be checked against a real statistic "
            "instead of one aggregate number."
        ),
        "statewide": {
            "lag0": stats_for(all_points_lag0),
            "lag1": stats_for(all_points_lag1),
        },
        "by_coc": by_coc,
    }
    DEST.write_text(json.dumps(result, indent=2))
    print(f"-> {DEST} ({len(by_coc)} CoCs, statewide lag0 r={result['statewide']['lag0']['pearson_r']})")


if __name__ == "__main__":
    main()
