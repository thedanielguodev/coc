#!/usr/bin/env python3
"""
Shrink data/ca_coc_boundaries.geojson for use in the browser map:
  - drop the ~50 mostly-null HUD contact/subpopulation columns, keep only
    COCNUM / COCNAME
  - simplify geometry (Douglas-Peucker, ~20m tolerance) since the site
    only needs a statewide overview, not survey-grade boundaries
  - clip every CoC polygon to the actual California state outline (fetched
    fresh from Census TIGERweb) so simplification can't leave slivers that
    bulge past the coastline or state line

Overwrites nothing; writes data/ca_coc_boundaries.min.geojson.
"""

import json
import pathlib
import subprocess
import sys

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

DATA_DIR = pathlib.Path(__file__).parent / "data"
SRC = DATA_DIR / "ca_coc_boundaries.geojson"
DEST = DATA_DIR / "ca_coc_boundaries.min.geojson"
CA_OUTLINE = DATA_DIR / "ca_state_outline.geojson"

TOLERANCE_DEG = 0.0002  # ~20m at CA latitudes


def round_coords(obj, ndigits=5):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, ndigits) for v in obj]
        return [round_coords(o, ndigits) for o in obj]
    return obj


def load_ca_outline():
    if not CA_OUTLINE.exists():
        subprocess.run([sys.executable, str(pathlib.Path(__file__).parent / "fetch_ca_outline.py")], check=True)
    data = json.loads(CA_OUTLINE.read_text())
    return unary_union([shape(f["geometry"]) for f in data["features"]])


def main():
    ca_outline = load_ca_outline()

    src = json.loads(SRC.read_text())
    out_features = []
    for feat in src["features"]:
        props = feat["properties"]
        geom = shape(feat["geometry"])
        geom = geom.simplify(TOLERANCE_DEG, preserve_topology=True)
        geom = geom.intersection(ca_outline)
        if geom.is_empty:
            continue
        geojson_geom = mapping(geom)
        geojson_geom["coordinates"] = round_coords(geojson_geom["coordinates"])
        out_features.append({
            "type": "Feature",
            "properties": {
                "COCNUM": props.get("COCNUM"),
                "COCNAME": props.get("COCNAME"),
            },
            "geometry": geojson_geom,
        })

    out = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": out_features,
    }
    DEST.write_text(json.dumps(out))
    print(f"{SRC.stat().st_size / 1e6:.1f} MB -> {DEST.stat().st_size / 1e6:.2f} MB ({DEST})")


if __name__ == "__main__":
    main()
