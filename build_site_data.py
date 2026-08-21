#!/usr/bin/env python3
"""
Convert the downloaded CSVs into JSON for the static site (site/data/) so the
browser doesn't need a CSV parser. Run after we.py and fetch_fires.py.
"""

import csv
import json
import pathlib

DATA_DIR = pathlib.Path(__file__).parent / "data"
SITE_DATA_DIR = pathlib.Path(__file__).parent / "site" / "data"

CSV_TO_JSON = [
    "ca_coc_pit_by_year.csv",
    "ca_coc_hic_by_year.csv",
    "ca_coc_pit_veterans_by_year.csv",
    "ca_fires_by_year.csv",
    "ca_fires_by_coc_year.csv",
]

GEOJSON_COPY = [
    "ca_coc_boundaries.min.geojson",
    "ca_fire_perimeters.geojson",
    "ca_state_outline.geojson",
]


def csv_to_records(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        records = []
        for row in reader:
            rec = {}
            for k, v in row.items():
                if v == "":
                    rec[k] = None
                else:
                    try:
                        rec[k] = int(v)
                    except ValueError:
                        try:
                            rec[k] = float(v)
                        except ValueError:
                            rec[k] = v
            records.append(rec)
        return records


def main():
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    for name in CSV_TO_JSON:
        src = DATA_DIR / name
        records = csv_to_records(src)
        dest = SITE_DATA_DIR / (src.stem + ".json")
        dest.write_text(json.dumps(records))
        print(f"{name} -> {dest.name} ({len(records)} rows, {dest.stat().st_size / 1e3:.0f} KB)")

    for name in GEOJSON_COPY:
        src = DATA_DIR / name
        dest = SITE_DATA_DIR / name
        dest.write_text(src.read_text())
        print(f"{name} -> site/data/{name} ({dest.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
