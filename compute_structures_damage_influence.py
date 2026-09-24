#!/usr/bin/env python3
"""
Ground-truth statistical methodology for structure-destruction ->
homelessness influence, mirroring compute_fire_influence.py but using
CAL FIRE DINS structures-destroyed counts (data/ca_structures_damage_by_coc_year.csv)
instead of fire-perimeter acreage.

join_dins_to_coc.py's docstring frames this directly: destroyed acreage of
wildland is not obviously a housing-loss signal, but a destroyed structure
is -- this script is the analysis that was supposed to test that, and
never got run. It answers a specific version of the project's research
question: does a more causally direct proxy for housing loss (homes
actually destroyed, not acres burned) show a relationship with homeless
counts that acres-burned does not?

DINS coverage starts in 2013 (see paper_response.md's Limitations section),
so this necessarily uses a shorter, more recent window (2013-2024) than the
acres-burned analysis (2007-2024) -- results are not directly comparable in
n, only in whether either shows a real relationship.

Output: data/ground_truth_structures_influence.json
"""

import csv
import json
import math
import pathlib
from collections import defaultdict

DATA_DIR = pathlib.Path(__file__).parent / "data"
PIT_SRC = DATA_DIR / "ca_coc_pit_by_year.csv"
DINS_SRC = DATA_DIR / "ca_structures_damage_by_coc_year.csv"
DEST = DATA_DIR / "ground_truth_structures_influence.json"

METRIC = "Overall Homeless"
MIN_YEAR = 2013  # first year of DINS coverage


def load_pit():
    by_coc = defaultdict(list)
    names = {}
    with open(PIT_SRC, newline="") as f:
        for row in csv.DictReader(f):
            val = row[METRIC]
            if val == "" or int(row["year"]) < MIN_YEAR:
                continue
            by_coc[row["coc_number"]].append((int(row["year"]), float(val)))
            names[row["coc_number"]] = row["coc_name"]
    return by_coc, names


def load_structures():
    destroyed = {}
    with open(DINS_SRC, newline="") as f:
        for row in csv.DictReader(f):
            destroyed[(row["coc_number"], int(row["year"]))] = float(row["structures_destroyed"])
    return destroyed


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


def build_points(rows, destroyed, coc_num, lag):
    points = []
    for year, val in rows:
        struct_year = year - lag
        if struct_year < MIN_YEAR:
            continue
        x = destroyed.get((coc_num, struct_year), 0.0)
        points.append((x, val))
    return points


def stats_for(points):
    n = len(points)
    r = pearson(points)
    rho = spearman(points)
    p = pearson_p_value(r, n)
    slope, intercept = linear_fit(points) if n >= 2 else (None, None)
    mean_x = sum(pt[0] for pt in points) / n if n else None
    mean_y = sum(pt[1] for pt in points) / n if n else None
    return {
        "n": n,
        "pearson_r": round(r, 4) if r is not None else None,
        "spearman_rho": round(rho, 4) if rho is not None else None,
        "p_value": round(p, 5) if p is not None else None,
        "slope": round(slope, 6) if slope is not None else None,
        "intercept": round(intercept, 3) if intercept is not None else None,
        "strength": strength(r),
        "mean_structures_destroyed": round(mean_x, 2) if mean_x is not None else None,
        "mean_homeless": round(mean_y, 1) if mean_y is not None else None,
    }


def main():
    pit_by_coc, names = load_pit()
    destroyed = load_structures()

    by_coc = {}
    all_points_lag0, all_points_lag1 = [], []
    for coc_num, rows in sorted(pit_by_coc.items()):
        lag0_points = build_points(rows, destroyed, coc_num, 0)
        lag1_points = build_points(rows, destroyed, coc_num, 1)
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
            "Pearson r / Spearman rho / least-squares fit between CAL FIRE DINS "
            "structures destroyed (>50% damage) within a CoC's boundary and that "
            "CoC's HUD Point-in-Time homeless count, pooled across 2013-2024 (the "
            "years DINS coverage overlaps PIT data). lag0 pairs same-year structures "
            "destroyed with the PIT count; lag1 pairs a year's destroyed structures "
            "with next year's PIT count. This is the same statistical design as "
            "compute_fire_influence.py, substituting structures-destroyed for "
            "acres-burned as a more causally direct housing-loss proxy -- burned "
            "wildland doesn't display anyone, a destroyed home might."
        ),
        "statewide": {
            "lag0": stats_for(all_points_lag0),
            "lag1": stats_for(all_points_lag1),
        },
        "by_coc": by_coc,
    }
    DEST.write_text(json.dumps(result, indent=2))
    print(f"-> {DEST} ({len(by_coc)} CoCs, statewide lag0 r={result['statewide']['lag0']['pearson_r']}, n={result['statewide']['lag0']['n']})")


if __name__ == "__main__":
    main()
