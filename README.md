# California CoC: Wildfire &amp; Homelessness Dashboard

**Live dashboard:** https://thedanielguodev.github.io/coc/

## Research question

How accurately can AI estimate and interpret the relationship between wildfire-related housing destruction and homelessness across California Continuums of Care (CoCs), compared with the relationship observed in real-world data?

Homelessness is difficult to measure, and the datasets used to represent it are shaped by specific definitions, collection methods, and institutions. It seems intuitive that destroying homes through wildfire would increase homelessness — but the ground-truth analysis here finds no meaningful relationship between fire acreage and Point-in-Time homeless counts at the CoC level (Pearson r close to 0, not statistically significant, in both the same-year and fire-year-→-next-year framings). This project asks whether an AI model, given only a CoC's wildfire history and asked to estimate that same relationship, recognizes that uncertainty or instead infers a stronger connection based on the intuitive but unsupported narrative.

## What's in the dashboard

- **Map** — a MapLibre GL JS choropleth of California's 44 CoCs on a gray-scale vector basemap (CARTO Dark Matter), colored by homeless count for the selected year/metric, with wildfire perimeters (CAL FIRE FRAP, ≥1,000 acres) overlaid per year.
- **Statewide trend** — homeless count and acres burned, 2007–2024, as D3 line charts.
- **Fire → homelessness correlation** — a D3 scatter of acres burned (within a CoC's boundary) vs. that CoC's homeless count, one point per CoC-year, with a least-squares fit line, Pearson r, and Spearman ρ. Toggle between same-year and fire-year-→-next-year timing.
- **AI vs. ground truth** — an LLM (Claude) is shown *only* each CoC's fire history — never the actual homeless counts — and asked to estimate the same per-CoC Pearson r. This panel plots the AI's estimate against the real value to see whether the model systematically exaggerates, underestimates, or roughly tracks the (mostly negligible) real relationship.
- **Selected CoC** — click any region for its own homeless-count trend over time.

## Data sources

- **Homelessness**: HUD Point-in-Time (PIT), Housing Inventory Count (HIC), and CoC boundary data, via HUD-eGIS Open Data and huduser.gov (fetched in `we.py`).
- **Wildfire**: CAL FIRE FRAP historical fire perimeters, ≥1,000 acres, 2000–present, via ArcGIS FeatureServer (fetched in `fetch_fires.py`).
- **Geographic boundaries**: U.S. Census TIGER/Line CA state outline (fetched in `fetch_ca_outline.py`), used to clip fire perimeters and CoC boundaries to the actual state border.

Fire acreage is attributed to CoCs by a spatial join (`join_fires_to_coc.py`): each fire perimeter is intersected against all 44 CoC polygons and its acreage is split proportionally where a fire straddles more than one CoC. This is what makes the correlation "real" — fires *within a CoC's boundary* — rather than a statewide fire-total vs. statewide-homeless comparison.

## Methodology (AI vs. ground truth)

1. `compute_fire_influence.py` computes the ground-truth per-CoC Pearson r / Spearman ρ / linear fit between fire acreage and PIT homeless count, directly from the joined data.
2. `ai_estimate_influence.py` sends Claude each CoC's name and fire history (year → acres burned) *only* — no PIT counts — and asks it to independently estimate that CoC's Pearson r.
3. `compare_ai_vs_ground_truth.py` diffs the AI's estimate against the real value per CoC (signed error, absolute error, and a exaggerates / underestimates / sign-flip / roughly-matches classification) and computes the statewide bias summary the dashboard's "AI vs. ground truth" panel renders.

This arm is optional and needs an `ANTHROPIC_API_KEY`; see `CLAUDE.md` for the full pipeline run order.

## Running locally

```bash
python3 -m http.server 8000
# open http://localhost:8000/
```

Must be served over HTTP (not opened as a `file://` URL), since the page `fetch()`s its data files. See `CLAUDE.md` for the full data pipeline (only needed to regenerate `site/data/`, which is already checked in).
