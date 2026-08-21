#!/usr/bin/env python3
"""
Spatially join wildfire perimeters to CoC regions: for each major fire,
find which CoC boundary/boundaries it burned in and attribute acreage
proportionally to the overlap area. Aggregates to (coc_number, year).

This lets the site correlate wildfire activity *in a given CoC's area*
against that CoC's homeless counts, rather than only comparing statewide
totals.

Output: data/ca_fires_by_coc_year.csv
"""

import csv
import json
import pathlib

from shapely.geometry import shape
from shapely.prepared import prep

DATA_DIR = pathlib.Path(__file__).parent / "data"
FIRES_SRC = DATA_DIR / "ca_fire_perimeters.geojson"
COC_SRC = DATA_DIR / "ca_coc_boundaries.min.geojson"
DEST = DATA_DIR / "ca_fires_by_coc_year.csv"


def main():
    fires = json.loads(FIRES_SRC.read_text())["features"]
    cocs = json.loads(COC_SRC.read_text())["features"]

    coc_geoms = []
    for feat in cocs:
        geom = shape(feat["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        coc_geoms.append((feat["properties"]["COCNUM"], geom, prep(geom)))

    totals = {}  # (coc_number, year) -> {fire_count, acres_burned}
    matched, unmatched = 0, 0

    for i, fire in enumerate(fires):
        props = fire["properties"]
        year = props.get("YEAR_")
        acres = props.get("GIS_ACRES") or 0
        if year is None or acres <= 0:
            continue
        try:
            fire_geom = shape(fire["geometry"])
        except Exception:
            continue
        if not fire_geom.is_valid:
            fire_geom = fire_geom.buffer(0)
        fire_area = fire_geom.area
        if fire_area <= 0:
            continue

        hit_any = False
        for coc_num, geom, prepared in coc_geoms:
            if not prepared.intersects(fire_geom):
                continue
            try:
                overlap = geom.intersection(fire_geom)
            except Exception:
                continue
            if overlap.is_empty:
                continue
            hit_any = True
            frac = overlap.area / fire_area
            key = (coc_num, year)
            rec = totals.setdefault(key, {"fire_count": 0, "acres_burned": 0.0})
            rec["fire_count"] += frac  # fractional attribution, summed later rounds fine
            rec["acres_burned"] += acres * frac

        if hit_any:
            matched += 1
        else:
            unmatched += 1

        if (i + 1) % 200 == 0:
            print(f"  processed {i + 1}/{len(fires)} fires...")

    print(f"Matched {matched} fires to at least one CoC, {unmatched} fell outside all CoC boundaries.")

    with open(DEST, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["coc_number", "year", "fire_count", "acres_burned"])
        for (coc_num, year), rec in sorted(totals.items()):
            writer.writerow([coc_num, year, round(rec["fire_count"], 2), round(rec["acres_burned"], 1)])

    print(f"-> {DEST} ({len(totals)} coc-year rows)")


if __name__ == "__main__":
    main()
