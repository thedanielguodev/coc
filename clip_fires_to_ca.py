#!/usr/bin/env python3
"""
Clip data/ca_fire_perimeters.geojson to the real California state outline.

CAL FIRE's dataset includes fires that spilled across the OR/NV/AZ state
lines (the perimeter is the whole fire, not just the CA portion), so without
this step those fires render with chunks sitting outside California on the
map.
"""

import json
import pathlib
import subprocess
import sys

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

DATA_DIR = pathlib.Path(__file__).parent / "data"
SRC = DATA_DIR / "ca_fire_perimeters.geojson"
CA_OUTLINE = DATA_DIR / "ca_state_outline.geojson"


def round_coords(obj, ndigits=4):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, ndigits) for v in obj]
        return [round_coords(o, ndigits) for o in obj]
    return obj


def main():
    if not CA_OUTLINE.exists():
        subprocess.run([sys.executable, str(pathlib.Path(__file__).parent / "fetch_ca_outline.py")], check=True)
    ca_data = json.loads(CA_OUTLINE.read_text())
    ca_outline = unary_union([shape(f["geometry"]) for f in ca_data["features"]])

    src = json.loads(SRC.read_text())
    out_features = []
    dropped = 0
    for feat in src["features"]:
        geom = shape(feat["geometry"])
        if not geom.is_valid:
            geom = geom.buffer(0)
        clipped = geom.intersection(ca_outline)
        if clipped.is_empty:
            dropped += 1
            continue
        geojson_geom = mapping(clipped)
        geojson_geom["coordinates"] = round_coords(geojson_geom["coordinates"])
        out_features.append({
            "type": "Feature",
            "properties": feat["properties"],
            "geometry": geojson_geom,
        })

    out = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": out_features,
    }
    SRC.write_text(json.dumps(out))
    print(f"Clipped {len(out_features)} fires to CA border ({dropped} fell entirely outside) -> {SRC} ({SRC.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
