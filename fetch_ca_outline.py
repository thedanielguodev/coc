#!/usr/bin/env python3
"""
Fetch the authoritative California state outline from Census TIGERweb.
Used to clip both CoC boundaries and wildfire perimeters so nothing in the
site can render outside the real state border (fires and CoC service areas
both occasionally spill across state lines or into the ocean in the source
data / after simplification).

Output: data/ca_state_outline.geojson
"""

import json
import pathlib

import requests

DATA_DIR = pathlib.Path(__file__).parent / "data"
DEST = DATA_DIR / "ca_state_outline.geojson"

CA_STATE_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/"
    "MapServer/0/query?where=STATE%3D%2706%27&outFields=STATE&outSR=4326&f=geojson"
)


def main():
    DATA_DIR.mkdir(exist_ok=True)
    print("Fetching authoritative CA state outline from Census TIGERweb...")
    resp = requests.get(CA_STATE_URL, timeout=30)
    resp.raise_for_status()
    DEST.write_text(resp.text)
    print(f"-> {DEST} ({DEST.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
