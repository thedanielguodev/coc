# Do Wildfires Show Up in California's Homeless Counts?

A data project comparing HUD homeless counts for California's 44 Continuums of Care (CoCs) with CAL FIRE wildfire records, 2007–2024, and testing how well AI models estimate the relationship without seeing the counts.

**Live dashboard:** https://research.danielguo.xyz/

## Research question

Can an AI model, given only a region's wildfire history, estimate the relationship between wildfire and the homeless count that HUD's data actually shows? If not, are its errors random or systematic, and where are they largest?

Homelessness is difficult to measure, and the datasets used to represent it are shaped by specific definitions, collection methods, and institutions. It seems intuitive that destroying homes through wildfire would increase homelessness. At the CoC level, though, fire exposure shows no detectable pooled association with Point-in-Time homeless counts (acres burned r = 0.027; structures destroyed r = 0.003). A two-way fixed-effects model finds small positive estimates, and the one that reaches significance depends entirely on Butte County (its same-year timing pairs the Camp Fire with a count taken before it, so it is not a Camp Fire effect). The 2021 count is excluded throughout, because HUD let CoCs skip the unsheltered count that year and 36 of California's 44 did. PIT counts miss many people displaced by fire, so this does not show that wildfire has no effect on housing loss. The project asks whether an AI model recognizes how weak the relationship is in this data or infers a stronger one from the intuitive story.

## What's in the dashboard

The page is laid out as a research report with numbered figures and tables:

- **Map**: a MapLibre GL JS choropleth of the 44 CoCs on a gray-scale CARTO basemap, shaded by the selected year and measure, with that year's fire perimeters. Clicking a region opens its history beside the map.
- **Statewide trends** (Figure 1): homeless count and acres burned, 2007–2024.
- **Fire and homeless counts** (Figures 2–3, Tables 1–2): the pooled scatter with a same-year or next-year toggle, year-by-year correlations with a Bonferroni correction and leave-one-out check, pooled correlations for acres burned and structures destroyed, and the fixed-effects estimates.
- **AI estimates** (Figures 4–7, Tables 3–4): each CoC's AI estimate against its observed correlation, error by stated confidence, a recency check, and the comparison across models and prompts. A sortable table lists every CoC.
- **Where the AI is most wrong** (Figure 8, Tables 5–6): the AI's estimate and the observed correlation plotted against structures destroyed, a test of whether observed correlations differ across CoCs beyond sampling noise, and rank correlations with census and insurance measures.
- **Butte County** (Figure 9): the Camp Fire against Butte County's count.
- **Data and methods**, limitations, data downloads, and a suggested citation.

## Data sources

- **Homelessness**: HUD Point-in-Time (PIT), Housing Inventory Count (HIC), and CoC boundary data, via HUD-eGIS Open Data and huduser.gov (fetched in `we.py`).
- **Wildfire**: CAL FIRE FRAP historical fire perimeters, ≥1,000 acres, 2000–present, via ArcGIS FeatureServer (fetched in `fetch_fires.py`).
- **Geographic boundaries**: U.S. Census TIGER/Line CA state outline (fetched in `fetch_ca_outline.py`), used to clip fire perimeters and CoC boundaries to the actual state border.
- **Demographics**: American Community Survey 2019–2023 five-year tract tables, from the Census Bureau's keyless summary files (fetched in `build_coc_covariates.py`).
- **Insurance**: California Department of Insurance new, renewed, and nonrenewed homeowners policies by ZIP code, 2015–2021 (fetched in `build_coc_covariates.py`).

Fire acreage is attributed to CoCs by a spatial join (`join_fires_to_coc.py`): each fire perimeter is intersected against all 44 CoC polygons and its acreage is split proportionally where a fire straddles more than one CoC. This is what makes the correlation "real" — fires *within a CoC's boundary* — rather than a statewide fire-total vs. statewide-homeless comparison.

## Methodology (AI vs. ground truth)

1. `compute_fire_influence.py` computes the ground-truth per-CoC Pearson r / Spearman ρ / linear fit between fire acreage and PIT homeless count, directly from the joined data.
2. `ai_estimate_influence.py` sends Claude each CoC's name and fire history (year → acres burned) *only* — no PIT counts — and asks it to independently estimate that CoC's Pearson r.
3. `compare_ai_vs_ground_truth.py` diffs the AI's estimate against the real value per CoC (signed error, absolute error, and a exaggerates / underestimates / sign-flip / roughly-matches classification) and computes the statewide bias summary the dashboard's "AI vs. ground truth" panel renders.

Follow-up runs (`ai_estimate_gemini.py`, `compare_ai_conditions.py`) repeat the test with a paragraph describing what the PIT count measures, and on a second model (Gemini). Adding the description lowered Claude's average estimate from 0.28 to 0.19 against an observed 0.06; Gemini 3.5 Flash-Lite estimated 0.13 and 0.06. A neutral prompt without the original's list of housing-loss mechanisms and its "not a hedge toward zero" instruction lowered Claude's estimate in every region (−0.06, compared with the original prompt re-run in the same batch) and cut its overstatement roughly in half; on Gemini the neutral prompt brought the average estimate to the observed value. Both models' estimates still rose with structures destroyed. Across 3,080 estimates only one was negative, and no model could rank regions by their observed relationship.

`analyze_error_heterogeneity.py` asks where the AI's error is largest. The observed per-CoC correlations do not vary beyond sampling noise (Cochran's Q), so the variation in error comes almost entirely from the AI side. The AI's estimate tracks structures destroyed (Spearman ρ = 0.80 for Claude) and rurality; after holding those fixed, no census or insurance measure predicts it. The AI overstates most in the CoCs with the most destructive fires.

This arm is optional. The Claude script needs `ANTHROPIC_API_KEY` and the Gemini script needs `GEMINI_API_KEY`; see the pipeline run order below.

## Running locally

```bash
python3 -m http.server 8000
# open http://localhost:8000/
```

Must be served over HTTP (not opened as a `file://` URL), since the page `fetch()`s its data files. Regenerating `site/data/` (already checked in) means running the pipeline below.

## Pipeline

Run in this order; each step reads the previous step's output in `data/`:

```bash
.venv/bin/python we.py                    # HUD: CoC boundaries + PIT/HIC/veteran CSVs -> data/
.venv/bin/python fetch_fires.py           # CAL FIRE FRAP: major fire perimeters -> data/ca_fire_perimeters.geojson
.venv/bin/python fetch_ca_outline.py      # Census TIGERweb: CA state border -> data/ca_state_outline.geojson (cached; skipped if already present)
.venv/bin/python clip_fires_to_ca.py      # clips fire perimeters to the CA outline (fires often spill across state lines)
.venv/bin/python simplify_boundaries.py   # simplifies + clips CoC boundaries to the CA outline -> data/ca_coc_boundaries.min.geojson
.venv/bin/python join_fires_to_coc.py     # spatial join: attributes fire acreage to CoC regions -> data/ca_fires_by_coc_year.csv
.venv/bin/python fetch_dins.py            # CAL FIRE DINS: structure-damage inspection points (2013+) -> data/ca_dins_structures.geojson
.venv/bin/python join_dins_to_coc.py      # spatial join: counts destroyed structures per CoC-year -> data/ca_structures_damage_by_coc_year.csv
.venv/bin/python compute_fire_influence.py       # ground-truth stats: per-CoC + statewide Pearson r/Spearman rho/linear fit -> data/ground_truth_fire_influence.json
.venv/bin/python compute_yearly_fire_influence.py # per-year (not pooled) cross-sectional Pearson r across all CoCs, + leave-one-out outlier check -> data/yearly_fire_influence.json
.venv/bin/python compute_structures_damage_influence.py # robustness check: same Pearson r/rho design, structures-destroyed (2013-2024) instead of acres-burned -> data/ground_truth_structures_influence.json
.venv/bin/python compute_panel_fe.py            # stricter check: two-way (CoC + year) fixed-effects regression, CoC-clustered SEs, acres + structures, lag0/lag1, log/level -> data/panel_fe_influence.json
.venv/bin/python ai_estimate_influence.py        # optional, needs ANTHROPIC_API_KEY: per-CoC LLM influence estimate from fire history alone (PIT data withheld) -> data/ai_fire_influence_estimates.json
.venv/bin/python compare_ai_vs_ground_truth.py   # optional, needs the previous two: diffs AI estimates against ground truth -> data/ai_vs_ground_truth.json
.venv/bin/python ai_estimate_gemini.py --condition all --model gemini-3.5-flash-lite  # optional, needs GEMINI_API_KEY; baseline, pit_informed, neutral -> data/ai_estimates_gemini_<condition>.json
.venv/bin/python compare_ai_conditions.py   # compares each model x prompt condition -> data/ai_condition_comparison.json
.venv/bin/python build_coc_covariates.py     # ACS tract demographics + CDI insurance nonrenewals + fire totals per CoC -> data/ca_coc_covariates.csv
.venv/bin/python analyze_error_heterogeneity.py  # where the AI-vs-observed gap is largest, and what predicts it -> data/error_heterogeneity.json
.venv/bin/python build_site_data.py       # converts CSVs to JSON and stages everything into site/data/
```
