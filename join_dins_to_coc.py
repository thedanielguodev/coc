#!/usr/bin/env python3
"""
Spatially join CAL FIRE DINS structure records to CoC regions: for each
damaged/destroyed structure, find which CoC boundary it falls inside
(point-in-polygon) and aggregate counts to (coc_number, year).

This gives a housing-loss-by-CoC-year signal to test against homeless
counts, as a more causally plausible alternative to fire-perimeter acreage
(see join_fires_to_coc.py) -- destroying homes is a mechanism that could
plausibly displace people into homelessness; burning empty wildland is not.

Output: data/ca_structures_damage_by_coc_year.csv
"""

import csv
import json
import pathlib

from shapely.geometry import shape, Point
from shapely.prepared import prep

DATA_DIR = pathlib.Path(__file__).parent / "data"
DINS_SRC = DATA_DIR / "ca_dins_structures.geojson"
COC_SRC = DATA_DIR / "ca_coc_boundaries.min.geojson"
DEST = DATA_DIR / "ca_structures_damage_by_coc_year.csv"

RESIDENTIAL_CATEGORIES = {"Single Residence", "Multiple Residence", "Mixed Commercial/Residential"}


def main():
    structures = json.loads(DINS_SRC.read_text())["features"]
    cocs = json.loads(COC_SRC.read_text())["features"]

    coc_geoms = []
    for feat in cocs:
        geom = shape(feat["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        coc_geoms.append((feat["properties"]["COCNUM"], prep(geom)))

    totals = {}  # (coc_number, year) -> counts
    matched, unmatched = 0, 0

    for i, s in enumerate(structures):
        props = s["properties"]
        year = props.get("YEAR")
        damage = props.get("DAMAGE")
        if year is None or damage is None:
            continue
        try:
            point = Point(s["geometry"]["coordinates"])
        except Exception:
            continue

        coc_num = None
        for cn, prepared in coc_geoms:
            if prepared.contains(point):
                coc_num = cn
                break

        if coc_num is None:
            unmatched += 1
            continue
        matched += 1

        key = (coc_num, year)
        rec = totals.setdefault(
            key, {"destroyed": 0, "destroyed_residential": 0, "damaged": 0}
        )
        category = props.get("STRUCTURECATEGORY")
        if damage == "Destroyed (>50%)":
            rec["destroyed"] += 1
            if category in RESIDENTIAL_CATEGORIES:
                rec["destroyed_residential"] += 1
        else:
            rec["damaged"] += 1

        if (i + 1) % 5000 == 0:
            print(f"  processed {i + 1}/{len(structures)} structures...")

    print(f"Matched {matched} structures to a CoC, {unmatched} fell outside all CoC boundaries.")

    with open(DEST, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "coc_number", "year", "structures_destroyed",
            "structures_destroyed_residential", "structures_damaged",
            "structures_impacted_total",
        ])
        for (coc_num, year), rec in sorted(totals.items()):
            total = rec["destroyed"] + rec["damaged"]
            writer.writerow([
                coc_num, year, rec["destroyed"], rec["destroyed_residential"],
                rec["damaged"], total,
            ])

    print(f"-> {DEST} ({len(totals)} coc-year rows)")


if __name__ == "__main__":
    main()
