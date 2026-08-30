# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A data pipeline + static site that visualizes California Continuum of Care (CoC) homelessness data (HUD PIT/HIC counts, 2007–2024) against major wildfire history (CAL FIRE FRAP perimeters, ≥1,000 acres, 2000–present) on an interactive map, including a spatial fire→homelessness correlation view.

## Setup

```bash
.venv/bin/pip install requests pyxlsb openpyxl shapely anthropic   # no requirements.txt; installed ad hoc
```

`anthropic` is only needed for `ai_estimate_influence.py`, which also requires an `ANTHROPIC_API_KEY` env var — everything else in the pipeline needs no credentials.

There is no build tool, package.json, or test suite — this is a linear Python data pipeline that writes static files, plus one hand-written HTML/JS page (`index.html`, at the repo root for GitHub Pages) that reads them.

## Commands

Run the pipeline scripts **in this order** (each depends on the previous step's output in `data/`):

```bash
.venv/bin/python we.py                    # HUD: CoC boundaries + PIT/HIC/veteran CSVs -> data/
.venv/bin/python fetch_fires.py           # CAL FIRE FRAP: major fire perimeters -> data/ca_fire_perimeters.geojson
.venv/bin/python fetch_ca_outline.py      # Census TIGERweb: CA state border -> data/ca_state_outline.geojson (cached; skipped if already present)
.venv/bin/python clip_fires_to_ca.py      # clips fire perimeters to the CA outline (fires often spill across state lines)
.venv/bin/python simplify_boundaries.py   # simplifies + clips CoC boundaries to the CA outline -> data/ca_coc_boundaries.min.geojson
.venv/bin/python join_fires_to_coc.py     # spatial join: attributes fire acreage to CoC regions -> data/ca_fires_by_coc_year.csv
.venv/bin/python compute_fire_influence.py       # ground-truth stats: per-CoC + statewide Pearson r/Spearman rho/linear fit -> data/ground_truth_fire_influence.json
.venv/bin/python ai_estimate_influence.py        # optional, needs ANTHROPIC_API_KEY: per-CoC LLM influence estimate from fire history alone (PIT data withheld) -> data/ai_fire_influence_estimates.json
.venv/bin/python compare_ai_vs_ground_truth.py   # optional, needs the previous two: diffs AI estimates against ground truth -> data/ai_vs_ground_truth.json
.venv/bin/python build_site_data.py       # converts CSVs to JSON and stages everything into site/data/
```

Serve and view the site (must be HTTP, not `file://`, since it `fetch()`s JSON/GeoJSON) from the **repo root**, not `site/` — `index.html` lives at the root and fetches `site/data/*`:

```bash
python3 -m http.server 8000   # then open http://localhost:8000/
```

The published GitHub Pages URL (Pages configured as "Deploy from branch: main / (root)") is https://thedanielguodev.github.io/coc/.

## Architecture

**Pipeline is one-directional and file-based** — each script reads from `data/`, writes back to `data/`, and there's no orchestration/Makefile tying them together; run them by hand in the order above whenever upstream data changes. `build_site_data.py` is the only step that touches `site/` — it copies/converts the final `data/*.geojson` and `data/*.csv` into `site/data/*.json` for the browser to fetch directly (no server-side code at runtime). `site/` holds only staged data now; the page itself is `index.html` at the repo root (required for GitHub Pages' root-folder deploy mode).

**Why the extra geometry passes exist**: raw HUD CoC boundaries are ~16MB with ~50 mostly-null HUD contact columns, and raw CAL FIRE perimeters include fires that burned across the OR/NV/AZ lines. `simplify_boundaries.py` and `clip_fires_to_ca.py` both fetch/reuse `data/ca_state_outline.geojson` (authoritative CA border from Census TIGERweb) and use Shapely `.intersection()` to hard-clip geometry to it — this is what prevents fire perimeters or CoC polygons from rendering outside the actual state border. Don't skip the clip steps after re-fetching source data.

**Spatial join (`join_fires_to_coc.py`)** overlaps each fire perimeter against all 44 CoC polygons and attributes acreage proportionally by intersection area (a fire straddling two CoCs splits its acres between them). This produces the CoC-year fire acreage used by the correlation feature — it's what makes the correlation "real" (fires *within a CoC's boundary*) rather than just a statewide fire-total vs. statewide-homeless comparison.

**AI-vs-ground-truth experiment** (`compute_fire_influence.py` → `ai_estimate_influence.py` → `compare_ai_vs_ground_truth.py`) is a separate, optional arm of the pipeline that asks how well an LLM's causal intuition about wildfire and homelessness matches the actual joined data. `compute_fire_influence.py` re-derives the Pearson r / Spearman rho / linear fit math from `index.html`'s correlation chart in Python, per-CoC (the site only ever computes one pooled statewide number) — this is the "ground truth." `ai_estimate_influence.py` then sends Claude *only* each CoC's fire history (year → acres burned, no PIT counts) and asks it to estimate the same correlation from reasoning alone; withholding the real counts is what makes the comparison meaningful rather than the model just restating numbers it was shown. `compare_ai_vs_ground_truth.py` diffs the two per CoC (signed/absolute error, exaggerates/underestimates/sign_flip/roughly_matches classification) and writes the summary bias stats that `index.html`'s "AI vs. ground truth" panel renders. This arm needs `ANTHROPIC_API_KEY`; the rest of the pipeline does not, and `build_site_data.py` silently skips staging these three JSON files if they haven't been generated yet.

**Without an `ANTHROPIC_API_KEY`** (e.g. a Claude Pro subscription only, no console.anthropic.com billing), `data/ai_fire_influence_estimates.json` can instead be produced by a *freshly spawned* Claude Code sub-agent that has no memory of this project's conversation history or ground-truth results — critical, since a sub-agent that had already seen `ground_truth_fire_influence.json` or the correlation chart's real numbers would no longer be a blind estimate. Give it only the per-CoC `coc_number`/`coc_name`/fire-year-history data (never PIT counts), the same system-prompt framing as `ai_estimate_influence.py`'s `SYSTEM_PROMPT`, and the same output schema (`coc_number`, `coc_name`, `n_fire_years`, `estimated_correlation`, `direction`, `confidence`, `reasoning` per CoC); validate the result against the real CoC list and fire-year counts before writing it to `data/ai_fire_influence_estimates.json`, then run `compare_ai_vs_ground_truth.py` and `build_site_data.py` as usual. Note the `model` field of the resulting JSON honestly, since this is a batched sub-agent call through Claude Code rather than 44 separate billed API calls.

**`index.html` is a single self-contained file** at the repo root (MapLibre GL JS + D3 v7 via CDN, no build step, no framework — required by the course assignment: MapLibre on a gray-scale vector basemap, D3 for charts) with a plain global `state` object holding all loaded data (indexed by CoC number via `indexByCoc()`) and one `update()` function that re-renders the map style, on-map labels, stat tiles, trend chart, and correlation scatter chart whenever the year/metric/lag selection changes. Key pieces if modifying it:
- The basemap style is CARTO's free `dark-matter-nolabels-gl-style` vector style (no API key) — a monochrome/gray-scale style consistent with the dashboard's dark theme.
- `refreshMapStyle()` / `colorScale()` — choropleth coloring, driven by `state.metric` + `state.year`, applied via `map.setFeatureState()` on the `coc` GeoJSON source (`promoteId: "COCNUM"`) rather than restyling each feature individually.
- `refreshLabels()` / `updateLabelVisibility()` — permanent on-map count labels; visibility is zoom-dependent (`LABEL_MIN_PX` threshold on each polygon's on-screen pixel bounds, computed via `map.project()`) to avoid overlapping labels where small CoCs cluster tightly (e.g. LA basin, Bay Area) — recomputed on every `zoomend`/`moveend`. Label *text* has to live on the GeoJSON feature itself (updated via `source.setData()`) rather than feature-state, because MapLibre's `text-field` is a layout property and layout properties can't read feature-state — only paint properties (like the fill/outline colors and label opacity) can.
- `buildCorrelationPoints()` / `pearson()` / `linearFit()` — the fire→homelessness scatter chart; `state.corrLag` (0 = same year, 1 = fire year vs. next year's count, the default) shifts which year's fire acreage is paired with which year's homeless count.
- `drawLineChart()` / `drawScatterChart()` — small D3 chart helpers reused across the trend, correlation, AI-compare, and per-CoC detail charts; tooltips are native `<title>` elements on each mark rather than custom hover tracking.

**Data joins are by `coc_number`** (e.g. `"CA-500"`) across all CSVs/GeoJSON — this is the only key linking PIT/HIC/veteran records, CoC boundary polygons, and the fire spatial-join output.

## Data sources

- CoC boundaries + PIT/HIC/veteran counts: HUD-eGIS Open Data and huduser.gov AHAR downloads (fetched in `we.py`).
- Fire perimeters: CAL FIRE FRAP historical wildland fire perimeter dataset, via ArcGIS FeatureServer (fetched in `fetch_fires.py`), filtered to ≥1,000 acres since 2000 to keep the dataset browser-sized — a full re-fetch of the unfiltered dataset (~8,900 fires) is significantly heavier and should not be attempted without re-confirming the size tradeoff.
- CA state outline: Census TIGERweb (fetched in `fetch_ca_outline.py`), used only for clipping.

`data/_raw/` (gitignored) holds the original downloaded `.xlsb`/`.xlsx` files from HUD so `we.py` doesn't re-download on repeat runs.
