# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A data pipeline + static site that visualizes California Continuum of Care (CoC) homelessness data (HUD PIT/HIC counts, 2007–2024) against major wildfire history (CAL FIRE FRAP perimeters, ≥1,000 acres, 2000–present) on an interactive map, including a spatial fire→homelessness correlation view.

## Setup

```bash
.venv/bin/pip install requests pyxlsb openpyxl shapely   # no requirements.txt; installed ad hoc
```

There is no build tool, package.json, or test suite — this is a linear Python data pipeline that writes static files, plus one hand-written HTML/JS page that reads them.

## Commands

Run the pipeline scripts **in this order** (each depends on the previous step's output in `data/`):

```bash
.venv/bin/python we.py                    # HUD: CoC boundaries + PIT/HIC/veteran CSVs -> data/
.venv/bin/python fetch_fires.py           # CAL FIRE FRAP: major fire perimeters -> data/ca_fire_perimeters.geojson
.venv/bin/python fetch_ca_outline.py      # Census TIGERweb: CA state border -> data/ca_state_outline.geojson (cached; skipped if already present)
.venv/bin/python clip_fires_to_ca.py      # clips fire perimeters to the CA outline (fires often spill across state lines)
.venv/bin/python simplify_boundaries.py   # simplifies + clips CoC boundaries to the CA outline -> data/ca_coc_boundaries.min.geojson
.venv/bin/python join_fires_to_coc.py     # spatial join: attributes fire acreage to CoC regions -> data/ca_fires_by_coc_year.csv
.venv/bin/python build_site_data.py       # converts CSVs to JSON and stages everything into site/data/
```

Serve and view the site (must be HTTP, not `file://`, since it `fetch()`s JSON/GeoJSON):

```bash
cd site && python3 -m http.server 8000
```

## Architecture

**Pipeline is one-directional and file-based** — each script reads from `data/`, writes back to `data/`, and there's no orchestration/Makefile tying them together; run them by hand in the order above whenever upstream data changes. `build_site_data.py` is the only step that touches `site/` — it copies/converts the final `data/*.geojson` and `data/*.csv` into `site/data/*.json` for the browser to fetch directly (no server-side code at runtime).

**Why the extra geometry passes exist**: raw HUD CoC boundaries are ~16MB with ~50 mostly-null HUD contact columns, and raw CAL FIRE perimeters include fires that burned across the OR/NV/AZ lines. `simplify_boundaries.py` and `clip_fires_to_ca.py` both fetch/reuse `data/ca_state_outline.geojson` (authoritative CA border from Census TIGERweb) and use Shapely `.intersection()` to hard-clip geometry to it — this is what prevents fire perimeters or CoC polygons from rendering outside the actual state border. Don't skip the clip steps after re-fetching source data.

**Spatial join (`join_fires_to_coc.py`)** overlaps each fire perimeter against all 44 CoC polygons and attributes acreage proportionally by intersection area (a fire straddling two CoCs splits its acres between them). This produces the CoC-year fire acreage used by the correlation feature — it's what makes the correlation "real" (fires *within a CoC's boundary*) rather than just a statewide fire-total vs. statewide-homeless comparison.

**`site/index.html` is a single self-contained file** (Leaflet + Chart.js via CDN, no build step, no framework) with a plain global `state` object holding all loaded data (indexed by CoC number via `indexByCoc()`) and one `update()` function that re-renders the map style, on-map labels, stat tiles, trend chart, and correlation scatter chart whenever the year/metric/lag selection changes. Key pieces if modifying it:
- `styleCocFeature()` / `colorScale()` — choropleth coloring, driven by `state.metric` + `state.year`.
- `refreshLabels()` / `updateLabelVisibility()` — permanent on-map count labels; visibility is zoom-dependent (`LABEL_MIN_PX` threshold on each polygon's on-screen pixel bounds) to avoid overlapping labels where small CoCs cluster tightly (e.g. LA basin, Bay Area) — recomputed on every `zoomend`/`moveend`.
- `buildCorrelationPoints()` / `pearson()` / `linearFit()` — the fire→homelessness scatter chart; `state.corrLag` (0 = same year, 1 = fire year vs. next year's count) shifts which year's fire acreage is paired with which year's homeless count.

**Data joins are by `coc_number`** (e.g. `"CA-500"`) across all CSVs/GeoJSON — this is the only key linking PIT/HIC/veteran records, CoC boundary polygons, and the fire spatial-join output.

## Data sources

- CoC boundaries + PIT/HIC/veteran counts: HUD-eGIS Open Data and huduser.gov AHAR downloads (fetched in `we.py`).
- Fire perimeters: CAL FIRE FRAP historical wildland fire perimeter dataset, via ArcGIS FeatureServer (fetched in `fetch_fires.py`), filtered to ≥1,000 acres since 2000 to keep the dataset browser-sized — a full re-fetch of the unfiltered dataset (~8,900 fires) is significantly heavier and should not be attempted without re-confirming the size tradeoff.
- CA state outline: Census TIGERweb (fetched in `fetch_ca_outline.py`), used only for clipping.

`data/_raw/` (gitignored) holds the original downloaded `.xlsb`/`.xlsx` files from HUD so `we.py` doesn't re-download on repeat runs.
