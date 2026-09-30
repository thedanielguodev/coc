#!/usr/bin/env python3
"""
Per-CoC place characteristics, for asking where the AI-vs-ground-truth gap is
larger or smaller (see analyze_error_heterogeneity.py).

Three groups of covariates, each aggregated to CoC boundaries by assigning a
small unit to the CoC whose polygon contains its internal point:

  demographics  ACS 2019-2023 5-year, census tracts (keyless table-based
                summary files from www2.census.gov, CA rows only). Counts are
                summed; medians are population-weighted means of tract medians,
                an approximation (the true CoC median can't be rebuilt from
                tract medians).
  insurance     CA Dept. of Insurance voluntary-market homeowners/dwelling
                policies by ZIP, 2015-2021 (new, renewed, insured- and
                insurer-initiated nonrenewals), ZIP -> ZCTA internal point.
                The insurer nonrenewal rate is insurer-initiated nonrenewals /
                policies up for renewal, the standard CDI "availability"
                measure.
  fire          from the existing joins: total and peak-year acres burned
                (2000-2024), structures destroyed (DINS, 2013-2024).

Inputs are cached under data/_raw/acs and data/_raw/cdi (downloaded if absent).
Output: data/ca_coc_covariates.csv
"""

import csv
import io
import pathlib
import urllib.request
import zipfile
from collections import defaultdict

import json
import openpyxl
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = pathlib.Path(__file__).parent
DATA_DIR = ROOT / "data"
ACS_DIR = DATA_DIR / "_raw" / "acs"
CDI_DIR = DATA_DIR / "_raw" / "cdi"
DEST = DATA_DIR / "ca_coc_covariates.csv"

ACS_BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/acsdt5y2023-{}.dat"
GAZ_TRACTS = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_gaz_tracts_06.txt"
GAZ_ZCTA = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_Gaz_zcta_national.zip"
CDI_URL = "https://www.insurance.ca.gov/01-consumers/200-wrr/upload/Residential-Property-Voluntary-Market-New-Renew-NonRenew-by-ZIP-2015-2021.xlsx"

LAST_PIT_YEAR = 2024  # fire totals stop where the PIT series does

ACS_TABLES = ["b01003", "b19013", "b17001", "b25003", "b25064", "b25070", "b03002", "b25002", "b27010", "b01001", "b25077"]


def fetch(url, dest):
    if not dest.exists():
        print(f"downloading {url}")
        dest.write_bytes(urllib.request.urlopen(url, timeout=600).read())
    return dest


def load_acs_table(table):
    """Return {tract GEOID (11 digits): {column: value}} for California tracts."""
    dest = ACS_DIR / f"{table}.ca.dat"
    if not dest.exists():
        print(f"downloading ACS {table}")
        raw = urllib.request.urlopen(ACS_BASE.format(table), timeout=600).read().decode()
        lines = raw.splitlines()
        dest.write_text("\n".join([lines[0]] + [l for l in lines[1:] if l.startswith("1400000US06")]) + "\n")
    rows = {}
    with open(dest) as f:
        header = f.readline().strip().split("|")
        for line in f:
            vals = line.strip().split("|")
            rec = {}
            for k, v in zip(header[1:], vals[1:]):
                try:
                    rec[k] = float(v)
                except ValueError:
                    rec[k] = None
            rows[vals[0][-11:]] = rec
    return rows


def num(v):
    # ACS uses large negative sentinels (e.g. -666666666) for suppressed estimates.
    return None if v is None or v < 0 else v


def load_coc_index():
    feats = json.loads((DATA_DIR / "ca_coc_boundaries.geojson").read_text())["features"]
    geoms = [shape(f["geometry"]) for f in feats]
    return STRtree(geoms), geoms, [f["properties"]["COCNUM"] for f in feats]


def locate(tree, geoms, ids, lon, lat):
    # HUD's Los Angeles polygon overlaps the Pasadena and Glendale CoCs it
    # surrounds, so prefer the smallest polygon containing the point.
    p = Point(lon, lat)
    hits = [i for i in tree.query(p) if geoms[i].contains(p)]
    return ids[min(hits, key=lambda i: geoms[i].area)] if hits else None


def tract_demographics(tree, geoms, ids):
    ACS_DIR.mkdir(parents=True, exist_ok=True)
    gaz = fetch(GAZ_TRACTS, ACS_DIR / "gaz_tracts_06.txt")
    tract_coc, tract_land = {}, {}
    with open(gaz) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            row = {k.strip(): v.strip() for k, v in row.items()}
            tract_coc[row["GEOID"]] = locate(tree, geoms, ids, float(row["INTPTLONG"]), float(row["INTPTLAT"]))
            tract_land[row["GEOID"]] = float(row["ALAND_SQMI"])

    t = {name: load_acs_table(name) for name in ACS_TABLES}
    sums = defaultdict(lambda: defaultdict(float))
    unassigned = 0

    def add(coc, key, value):
        if value is not None:
            sums[coc][key] += value

    for geoid, coc in tract_coc.items():
        if coc is None:
            unassigned += 1
            continue
        g = lambda table, col: num(t[table].get(geoid, {}).get(col))
        pop = g("b01003", "B01003_E001") or 0.0
        add(coc, "pop", pop)
        add(coc, "land_sqmi", tract_land[geoid])
        add(coc, "pov_universe", g("b17001", "B17001_E001"))
        add(coc, "pov_below", g("b17001", "B17001_E002"))
        add(coc, "hh", g("b25003", "B25003_E001"))
        add(coc, "hh_renter", g("b25003", "B25003_E003"))
        add(coc, "rent_universe", (g("b25070", "B25070_E001") or 0) - (g("b25070", "B25070_E011") or 0))
        add(coc, "rent_burdened", sum(g("b25070", f"B25070_E{c:03d}") or 0 for c in (7, 8, 9, 10)))
        add(coc, "race_total", g("b03002", "B03002_E001"))
        add(coc, "white_nh", g("b03002", "B03002_E003"))
        add(coc, "black_nh", g("b03002", "B03002_E004"))
        add(coc, "hispanic", g("b03002", "B03002_E012"))
        add(coc, "units", g("b25002", "B25002_E001"))
        add(coc, "units_vacant", g("b25002", "B25002_E003"))
        add(coc, "ins_universe", g("b27010", "B27010_E001"))
        add(coc, "uninsured", sum(g("b27010", f"B27010_E{c:03d}") or 0 for c in (17, 33, 50, 66)))
        add(coc, "age_total", g("b01001", "B01001_E001"))
        add(coc, "age65", sum(g("b01001", f"B01001_E{c:03d}") or 0 for c in (*range(20, 26), *range(44, 50))))
        for key, table, col in (("income", "b19013", "B19013_E001"), ("rent", "b25064", "B25064_E001"), ("value", "b25077", "B25077_E001")):
            v = g(table, col)
            if v is not None and pop:
                add(coc, f"{key}_w", v * pop)
                add(coc, f"{key}_wpop", pop)
    print(f"tracts: {len(tract_coc)} ({unassigned} with internal point outside every CoC, dropped)")

    out = {}
    for coc, s in sums.items():
        ratio = lambda a, b: round(s[a] / s[b], 4) if s[b] else None
        out[coc] = {
            "population": int(s["pop"]),
            "pop_density_sqmi": round(s["pop"] / s["land_sqmi"], 1) if s["land_sqmi"] else None,
            "median_hh_income": round(s["income_w"] / s["income_wpop"]) if s["income_wpop"] else None,
            "median_gross_rent": round(s["rent_w"] / s["rent_wpop"]) if s["rent_wpop"] else None,
            "median_home_value": round(s["value_w"] / s["value_wpop"]) if s["value_wpop"] else None,
            "poverty_rate": ratio("pov_below", "pov_universe"),
            "renter_share": ratio("hh_renter", "hh"),
            "rent_burdened_share": ratio("rent_burdened", "rent_universe"),
            "vacancy_rate": ratio("units_vacant", "units"),
            "white_nh_share": ratio("white_nh", "race_total"),
            "black_nh_share": ratio("black_nh", "race_total"),
            "hispanic_share": ratio("hispanic", "race_total"),
            "age65_share": ratio("age65", "age_total"),
            "uninsured_health_share": ratio("uninsured", "ins_universe"),
        }
    return out


def insurance(tree, geoms, ids):
    CDI_DIR.mkdir(parents=True, exist_ok=True)
    zpath = fetch(GAZ_ZCTA, CDI_DIR / "zcta.zip")
    zip_coc = {}
    with zipfile.ZipFile(zpath) as z:
        text = z.read(z.namelist()[0]).decode()
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        row = {k.strip(): v.strip() for k, v in row.items()}
        if "90000" <= row["GEOID"] <= "96199":
            zip_coc[row["GEOID"]] = locate(tree, geoms, ids, float(row["INTPTLONG"]), float(row["INTPTLAT"]))

    wb = openpyxl.load_workbook(fetch(CDI_URL, CDI_DIR / CDI_URL.rsplit("/", 1)[1]), read_only=True)
    s = defaultdict(lambda: defaultdict(float))
    unmatched = 0
    for r in list(wb.worksheets[0].iter_rows(values_only=True))[1:]:
        _, zipcode, year, new, renewed, insured_nr, insurer_nr = r[:7]
        coc = zip_coc.get(f"{int(zipcode):05d}") if zipcode else None
        if coc is None:
            unmatched += 1
            continue
        up = (renewed or 0) + (insured_nr or 0) + (insurer_nr or 0)
        s[coc]["up"] += up
        s[coc]["insurer_nr"] += insurer_nr or 0
        s[(coc, int(year))]["up"] += up
        s[(coc, int(year))]["insurer_nr"] += insurer_nr or 0
    print(f"insurance rows without a CoC-matched ZCTA: {unmatched}")

    out = {}
    for coc in {k for k in s if isinstance(k, str)}:
        rate = lambda k: s[k]["insurer_nr"] / s[k]["up"] if s[k]["up"] else None
        early = [rate((coc, y)) for y in (2015, 2016) if rate((coc, y)) is not None]
        late = [rate((coc, y)) for y in (2020, 2021) if rate((coc, y)) is not None]
        out[coc] = {
            "insurer_nonrenewal_rate": round(rate(coc), 5),
            "insurer_nonrenewal_change": round(sum(late) / len(late) - sum(early) / len(early), 5) if early and late else None,
            "policies_per_year": round(s[coc]["up"] / 7),
        }
    return out


def fire_history():
    acres = defaultdict(dict)
    with open(DATA_DIR / "ca_fires_by_coc_year.csv", newline="") as f:
        for row in csv.DictReader(f):
            if int(row["year"]) <= LAST_PIT_YEAR:
                acres[row["coc_number"]][int(row["year"])] = float(row["acres_burned"])
    destroyed = defaultdict(float)
    with open(DATA_DIR / "ca_structures_damage_by_coc_year.csv", newline="") as f:
        for row in csv.DictReader(f):
            if int(row["year"]) <= LAST_PIT_YEAR:
                destroyed[row["coc_number"]] += float(row["structures_destroyed"])
    out = defaultdict(lambda: {"fire_acres_total": 0, "fire_acres_peak_year": 0, "fire_years": 0, "structures_destroyed_total": 0})
    for coc in set(acres) | set(destroyed):
        a = acres.get(coc, {})
        out[coc] = {
            "fire_acres_total": round(sum(a.values())),
            "fire_acres_peak_year": round(max(a.values(), default=0)),
            "fire_years": sum(v > 0 for v in a.values()),
            "structures_destroyed_total": int(destroyed.get(coc, 0)),
        }
    return out


def main():
    tree, geoms, ids = load_coc_index()
    names = {}
    with open(DATA_DIR / "ca_coc_pit_by_year.csv", newline="") as f:
        for row in csv.DictReader(f):
            names[row["coc_number"]] = row["coc_name"]
    demo, ins, fire = tract_demographics(tree, geoms, ids), insurance(tree, geoms, ids), fire_history()

    rows = []
    for coc in sorted(names):
        row = {"coc_number": coc, "coc_name": names[coc]}
        for src in (demo, ins):
            row.update(src.get(coc, {}))
        row.update(fire[coc])
        rows.append(row)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(DEST, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"-> {DEST} ({len(rows)} CoCs, {len(cols) - 2} covariates)")


if __name__ == "__main__":
    main()
