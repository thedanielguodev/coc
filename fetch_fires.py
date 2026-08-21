#!/usr/bin/env python3
"""
Download major California wildfire perimeters (>= 1,000 acres, 2000-present)
from CAL FIRE FRAP (Fire and Resource Assessment Program), for use alongside
the CoC homelessness data.

Source (official CAL FIRE / FRAP, hosted on ArcGIS Online):
  https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/
  California_Historic_Fire_Perimeters/FeatureServer/0

Kept deliberately small: only fires >= MIN_ACRES, geometry simplified.
Output: ./data/ca_fire_perimeters.geojson
        ./data/ca_fires_by_year.csv (yearly summary: count, total acres)
"""

import csv
import json
import pathlib
import urllib.parse

import requests

OUTPUT_DIR = pathlib.Path(__file__).parent / "data"

BASE_URL = (
    "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/"
    "California_Historic_Fire_Perimeters/FeatureServer/0/query"
)

FIELDS = "YEAR_,FIRE_NAME,AGENCY,ALARM_DATE,CONT_DATE,CAUSE,GIS_ACRES"
MIN_YEAR = 2000
MIN_ACRES = 1000
PAGE_SIZE = 1000

CAUSE_NAMES = {
    1: "Lightning", 2: "Equipment Use", 3: "Smoking", 4: "Campfire",
    5: "Debris", 6: "Railroad", 7: "Arson", 8: "Playing with fire",
    9: "Miscellaneous", 10: "Vehicle", 11: "Power line", 12: "Firefighter training",
    13: "Non-firefighter training", 14: "Unknown/unidentified", 15: "Structure",
    16: "Aircraft", 17: "Volcanic", 18: "Escaped prescribed burn", 19: "Illegal alien campfire",
}


def fetch_all_fires():
    print(f"Fetching CA wildfires >= {MIN_ACRES} acres since {MIN_YEAR} from CAL FIRE FRAP...")
    all_features = []
    offset = 0
    while True:
        params = {
            "where": f"YEAR_ >= {MIN_YEAR} AND GIS_ACRES >= {MIN_ACRES}",
            "outFields": FIELDS,
            "outSR": 4326,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "geometryPrecision": 4,
            "maxAllowableOffset": 0.002,
        }
        url = BASE_URL + "?" + urllib.parse.urlencode(params)
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if not features:
            break
        all_features.extend(features)
        print(f"  fetched {len(all_features)} fires so far...")
        offset += PAGE_SIZE
        if len(features) < PAGE_SIZE:
            break

    for f in all_features:
        props = f["properties"]
        cause = props.get("CAUSE")
        props["CAUSE_NAME"] = CAUSE_NAMES.get(cause, "Unknown")

    out = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": all_features,
    }
    dest = OUTPUT_DIR / "ca_fire_perimeters.geojson"
    dest.write_text(json.dumps(out))
    print(f"  {len(all_features)} fires -> {dest} ({dest.stat().st_size / 1e6:.2f} MB)")
    return all_features


def write_yearly_summary(features):
    by_year = {}
    for f in features:
        p = f["properties"]
        year = p.get("YEAR_")
        acres = p.get("GIS_ACRES") or 0
        if year is None:
            continue
        rec = by_year.setdefault(year, {"year": year, "fire_count": 0, "total_acres": 0.0})
        rec["fire_count"] += 1
        rec["total_acres"] += acres

    dest = OUTPUT_DIR / "ca_fires_by_year.csv"
    with open(dest, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["year", "fire_count", "total_acres"])
        writer.writeheader()
        for year in sorted(by_year):
            row = by_year[year]
            row["total_acres"] = round(row["total_acres"], 1)
            writer.writerow(row)
    print(f"  yearly summary -> {dest}")


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    features = fetch_all_fires()
    write_yearly_summary(features)
    print("\nDone.")


if __name__ == "__main__":
    main()
