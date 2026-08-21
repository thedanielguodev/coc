#!/usr/bin/env python3
"""
Download CAL FIRE Damage Inspection (DINS) records: individual structures
damaged/destroyed by wildland fire in California, 2013-present. This is a
much closer proxy for actual housing loss than fire-perimeter acreage (a
50,000-acre wildland burn with zero structures lost looks very different
from a fire that leveled a neighborhood).

Source (official CAL FIRE / FRAP "POSTFIRE" dataset, hosted on ArcGIS Online):
  https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/
  POSTFIRE_MASTER_DATA_SHARE/FeatureServer/0

Filtered to CA records with actual damage (excludes "No Damage" and
"Inaccessible" inspections, which make up ~40% of the raw dataset and
aren't useful for a housing-loss signal).

Output: ./data/ca_dins_structures.geojson
        ./data/ca_structures_damage_by_year.csv (yearly summary)
"""

import csv
import datetime
import json
import pathlib
import urllib.parse

import requests

OUTPUT_DIR = pathlib.Path(__file__).parent / "data"

BASE_URL = (
    "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/"
    "POSTFIRE_MASTER_DATA_SHARE/FeatureServer/0/query"
)

FIELDS = (
    "DAMAGE,STRUCTURECATEGORY,STRUCTURETYPE,COUNTY,INCIDENTNAME,"
    "INCIDENTSTARTDATE,LATITUDE,LONGITUDE"
)
WHERE = "STATE='CA' AND DAMAGE NOT IN ('No Damage','Inaccessible')"
PAGE_SIZE = 2000


def fetch_all_structures():
    print("Fetching CA DINS damaged/destroyed structure records from CAL FIRE...")
    all_features = []
    offset = 0
    while True:
        params = {
            "where": WHERE,
            "outFields": FIELDS,
            "outSR": 4326,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "orderByFields": "OBJECTID",
        }
        url = BASE_URL + "?" + urllib.parse.urlencode(params)
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if not features:
            break
        all_features.extend(features)
        print(f"  fetched {len(all_features)} structures so far...")
        offset += PAGE_SIZE
        if len(features) < PAGE_SIZE:
            break

    for f in all_features:
        props = f["properties"]
        ms = props.get("INCIDENTSTARTDATE")
        props["YEAR"] = (
            datetime.datetime.utcfromtimestamp(ms / 1000).year if ms else None
        )

    out = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": all_features,
    }
    dest = OUTPUT_DIR / "ca_dins_structures.geojson"
    dest.write_text(json.dumps(out))
    print(f"  {len(all_features)} structures -> {dest} ({dest.stat().st_size / 1e6:.2f} MB)")
    return all_features


def write_yearly_summary(features):
    by_year = {}
    for f in features:
        p = f["properties"]
        year = p.get("YEAR")
        if year is None:
            continue
        rec = by_year.setdefault(
            year, {"year": year, "destroyed": 0, "major": 0, "minor": 0, "affected": 0}
        )
        damage = p.get("DAMAGE")
        if damage == "Destroyed (>50%)":
            rec["destroyed"] += 1
        elif damage == "Major (25-50%)":
            rec["major"] += 1
        elif damage == "Minor (10-25%)":
            rec["minor"] += 1
        elif damage == "Affected (>0-10%)":
            rec["affected"] += 1

    dest = OUTPUT_DIR / "ca_structures_damage_by_year.csv"
    with open(dest, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["year", "destroyed", "major", "minor", "affected"])
        writer.writeheader()
        for year in sorted(by_year):
            writer.writerow(by_year[year])
    print(f"  yearly summary -> {dest}")


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    features = fetch_all_structures()
    write_yearly_summary(features)
    print("\nDone.")


if __name__ == "__main__":
    main()
