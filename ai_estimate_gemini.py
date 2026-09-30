#!/usr/bin/env python3
"""
Second-model replication of the blind AI-estimation experiment, using Google
Gemini instead of Claude. Same batched design as the Claude sub-agent trials:
each trial sends all 44 CoCs' fire histories (never PIT counts) in one request
and asks for a per-CoC Pearson r estimate.

Three prompt conditions:
  baseline      ai_estimate_influence.SYSTEM_PROMPT + the batched region list
  pit_informed  the same, plus PIT_CONTEXT describing what the HUD
                Point-in-Time count does and does not measure
  neutral       baseline with exactly two things removed: the list of
                housing-loss mechanisms and "not a hedge toward zero"

Comparing the two tells whether the model's overstatement shrinks once it knows
how the outcome is measured (i.e. whether it's reasoning about the world or
about this data).

Requires GEMINI_API_KEY in the environment (never hardcode it).
Usage: python ai_estimate_gemini.py [--condition baseline|pit_informed|neutral|both|all] [--trials 10] [--model gemini-3.8-flash]
Output: data/ai_estimates_gemini_<condition>.json (raw per-trial output + prompt)
"""

import argparse
import csv
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

DATA_DIR = pathlib.Path(__file__).parent / "data"
PIT_SRC = DATA_DIR / "ca_coc_pit_by_year.csv"
FIRE_SRC = DATA_DIR / "ca_fires_by_coc_year.csv"

# Kept verbatim from ai_estimate_influence.py so both models see the same framing.
SYSTEM_PROMPT = (
    "You are participating in a research study on how well AI causal/statistical "
    "intuition matches real data. You will be given a U.S. Continuum of Care (CoC) "
    "homelessness-services region's wildfire history and asked to estimate its "
    "statistical relationship to that region's homeless count. You are NOT given "
    "the actual homeless counts -- estimate from first-principles reasoning about "
    "wildfire's plausible effects on housing stability (destroyed housing stock, "
    "displacement, evacuation, insurance/rebuilding costs, economic disruption) "
    "plus whatever general knowledge you have of this region, not from being told "
    "the answer. Give your honest best estimate, not a hedge toward zero."
)

# SYSTEM_PROMPT minus the mechanism list and the "not a hedge toward zero"
# instruction; every other word is unchanged, so any difference in estimates
# is attributable to those two phrases.
NEUTRAL_PROMPT = (
    "You are participating in a research study on how well AI causal/statistical "
    "intuition matches real data. You will be given a U.S. Continuum of Care (CoC) "
    "homelessness-services region's wildfire history and asked to estimate its "
    "statistical relationship to that region's homeless count. You are NOT given "
    "the actual homeless counts -- estimate from your own reasoning "
    "plus whatever general knowledge you have of this region, not from being told "
    "the answer. Give your honest best estimate."
)

PIT_CONTEXT = (
    "About the homeless counts you are estimating against: they are HUD Point-in-Time (PIT) counts. "
    "A PIT count is a single-night count, taken in late January, of people staying in emergency shelters, "
    "transitional housing, or unsheltered locations such as streets, cars, and encampments. It does not count "
    "people staying with friends or family, people in hotels or rentals paid for by insurance or FEMA, or people "
    "who moved out of the region. Counting methods differ across regions and change over time, and in 2021 most "
    "California regions skipped the unsheltered count because of COVID-19. The correlation you are estimating is "
    "between each year's acres burned and that same year's PIT count, over roughly 2007 to 2024."
)

OUTPUT_SPEC = (
    'Return ONLY a JSON array with one object per region, in the order given, with exactly these keys:\n'
    '"coc_number" (string), "estimated_correlation" (number, -1.0 to 1.0), '
    '"direction" ("increases" | "decreases" | "no_relationship"), '
    '"confidence" ("low" | "medium" | "high"), "reasoning" (one sentence).'
)


def load_regions():
    names = {}
    with open(PIT_SRC, newline="") as f:
        for row in csv.DictReader(f):
            names[row["coc_number"]] = row["coc_name"]
    history = defaultdict(list)
    with open(FIRE_SRC, newline="") as f:
        for row in csv.DictReader(f):
            history[row["coc_number"]].append((int(row["year"]), float(row["acres_burned"])))
    for rows in history.values():
        rows.sort()
    return names, history


def region_block(coc_num, coc_name, fire_rows):
    if fire_rows:
        lines = "\n".join(f"  {y}: {a:,.0f} acres burned" for y, a in fire_rows)
    else:
        lines = "  No major (>=1,000-acre) fires on record, 2000-2024."
    return f"Region: {coc_name} ({coc_num})\nMajor wildfire history within this region's boundary, 2000-2024:\n{lines}"


def build_prompt(condition, names, history):
    parts = [NEUTRAL_PROMPT if condition == "neutral" else SYSTEM_PROMPT]
    if condition == "pit_informed":
        parts.append(PIT_CONTEXT)
    parts.append(
        f"Below are {len(names)} regions. For EACH region, estimate what a Pearson correlation "
        "coefficient (-1.0 to 1.0) between this region's annual acres burned and its same-year "
        "homeless count would show."
    )
    parts.append("\n\n".join(region_block(c, names[c], history.get(c, [])) for c in sorted(names)))
    parts.append(OUTPUT_SPEC)
    return "\n\n".join(parts)


def _texts(node, out):
    """Collect model output text from an Interactions API response, skipping thought steps."""
    if isinstance(node, dict):
        if "thought" in str(node.get("type", "")).lower():
            return
        if isinstance(node.get("text"), str):
            out.append(node["text"])
        for v in node.values():
            _texts(v, out)
    elif isinstance(node, list):
        for v in node:
            _texts(v, out)


def parse_json_array(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text[text.index("["): text.rindex("]") + 1])


def call_gemini(model, prompt, key, retries=8):
    # Gemini's Interactions API (v1beta/interactions); older generateContent models
    # are closed to new keys. Free tier allows 5 requests/minute, so calls are paced.
    url = "https://generativelanguage.googleapis.com/v1beta/interactions"
    body = json.dumps({"model": model, "input": prompt}).encode()
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.load(resp)
            texts = []
            _texts(data.get("steps", data), texts)
            return parse_json_array(texts[-1])
        except urllib.error.HTTPError as err:
            wait = 65 if err.code == 429 else 20 * (attempt + 1)
            print(f"    HTTP {err.code}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
        except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as err:
            wait = 20 * (attempt + 1)
            print(f"    attempt {attempt + 1} failed ({err}); retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("Gemini call failed after retries")


def validate(trial, names):
    if not all(isinstance(r, dict) and "coc_number" in r and "estimated_correlation" in r for r in trial):
        raise ValueError("malformed rows")
    got = {r["coc_number"]: r for r in trial}
    missing = set(names) - set(got)
    if missing:
        raise ValueError(f"missing CoCs: {sorted(missing)}")
    return [got[c] for c in sorted(names)]


def run(condition, n_trials, model, key):
    names, history = load_regions()
    prompt = build_prompt(condition, names, history)
    dest = DATA_DIR / f"ai_estimates_gemini_{condition}.json"
    # Resume: keep trials already saved for this model/prompt (free-tier quotas are small).
    trials = []
    if dest.exists():
        prev = json.loads(dest.read_text())
        if prev.get("model") == model and prev.get("prompt") == prompt:
            trials = prev["trials"]
    while len(trials) < n_trials:
        i = len(trials) + 1
        for attempt in range(3):
            try:
                trials.append(validate(call_gemini(model, prompt, key), names))
                break
            except ValueError as err:
                print(f"  trial {i}: invalid output ({err}), re-asking", file=sys.stderr)
        else:
            raise RuntimeError(f"trial {i} never returned all CoCs")
        dest.write_text(json.dumps({
            "model": model,
            "condition": condition,
            "run_date": time.strftime("%Y-%m-%d"),
            "design": "batched: all 44 CoCs in one request per trial, independent requests, no conversation history",
            "prompt": prompt,
            "trials": trials,
        }, indent=1))
        mean = sum(r["estimated_correlation"] for r in trials[-1]) / len(trials[-1])
        print(f"  {condition} trial {i}/{n_trials}: mean estimate {mean:+.3f}")
        time.sleep(20)  # stay under the free-tier 5 requests/minute
    print(f"-> {dest}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", choices=["baseline", "pit_informed", "neutral", "both", "all"], default="both")
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--model", default="gemini-3.8-flash")
    args = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set.")
    conds = {"both": ["baseline", "pit_informed"], "all": ["baseline", "pit_informed", "neutral"]}.get(args.condition, [args.condition])
    for cond in conds:
        run(cond, args.trials, args.model, key)


if __name__ == "__main__":
    main()
