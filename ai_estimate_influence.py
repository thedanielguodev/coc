#!/usr/bin/env python3
"""
Ask an LLM to estimate, per CoC, how strongly wildfire history correlates
with homelessness counts -- WITHOUT showing it the actual PIT counts or
the ground-truth statistics from compute_fire_influence.py. Only the
region's name and its major-fire history (year: acres burned) go into
the prompt.

This is one half of an experiment: compare_ai_vs_ground_truth.py diffs
these AI estimates against the real per-CoC Pearson r to see where (and
by how much) an LLM's causal intuition about wildfire and homelessness
diverges from what the actual joined data shows.

Requires ANTHROPIC_API_KEY in the environment.
Output: data/ai_fire_influence_estimates.json
"""

import csv
import json
import os
import pathlib
import sys
from collections import defaultdict

import anthropic

DATA_DIR = pathlib.Path(__file__).parent / "data"
PIT_SRC = DATA_DIR / "ca_coc_pit_by_year.csv"
FIRE_SRC = DATA_DIR / "ca_fires_by_coc_year.csv"
DEST = DATA_DIR / "ai_fire_influence_estimates.json"

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

ESTIMATE_TOOL = {
    "name": "record_estimate",
    "description": "Record the wildfire-to-homelessness influence estimate for this region.",
    "input_schema": {
        "type": "object",
        "properties": {
            "estimated_correlation": {
                "type": "number",
                "description": (
                    "-1.0 to 1.0. Your best estimate of what a Pearson correlation "
                    "coefficient between this region's annual acres burned and its "
                    "same-year homeless count would show."
                ),
            },
            "direction": {
                "type": "string",
                "enum": ["increases", "decreases", "no_relationship"],
            },
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "reasoning": {
                "type": "string",
                "description": "1-2 sentences on why.",
            },
        },
        "required": ["estimated_correlation", "direction", "confidence", "reasoning"],
    },
}

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


def load_fire_histories():
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


def build_prompt(coc_num, coc_name, fire_rows):
    if fire_rows:
        lines = "\n".join(f"  {y}: {a:,.0f} acres burned" for y, a in fire_rows)
    else:
        lines = "  No major (>=1,000-acre) fires on record, 2000-2024."
    return (
        f"Region: {coc_name} ({coc_num})\n"
        f"Major wildfire history within this region's boundary, 2000-2024:\n{lines}\n\n"
        "Estimate this region's wildfire-to-homelessness correlation and call "
        "record_estimate with your answer."
    )


def main():
    if "ANTHROPIC_API_KEY" not in os.environ:
        sys.exit("ANTHROPIC_API_KEY is not set. Export it and re-run.")

    client = anthropic.Anthropic()
    names, history = load_fire_histories()

    results = []
    coc_nums = sorted(names)
    for i, coc_num in enumerate(coc_nums, 1):
        coc_name = names[coc_num]
        fire_rows = history.get(coc_num, [])
        prompt = build_prompt(coc_num, coc_name, fire_rows)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            tools=[ESTIMATE_TOOL],
            tool_choice={"type": "tool", "name": "record_estimate"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_use = next(b for b in resp.content if b.type == "tool_use")
        est = tool_use.input
        results.append({
            "coc_number": coc_num,
            "coc_name": coc_name,
            "n_fire_years": len(fire_rows),
            "estimated_correlation": est["estimated_correlation"],
            "direction": est["direction"],
            "confidence": est["confidence"],
            "reasoning": est["reasoning"],
        })
        print(f"  [{i}/{len(coc_nums)}] {coc_num}: {est['estimated_correlation']:+.2f} ({est['direction']})")

    DEST.write_text(json.dumps({
        "model": MODEL,
        "methodology": (
            "Each CoC's fire history (year: acres burned within its boundary, no "
            "homeless counts) was sent to the model in a separate call; it was "
            "asked to estimate what a Pearson r between fire acreage and homeless "
            "count would show, from reasoning alone. Compare against "
            "ground_truth_fire_influence.json via compare_ai_vs_ground_truth.py."
        ),
        "estimates": results,
    }, indent=2))
    print(f"-> {DEST} ({len(results)} CoCs)")


if __name__ == "__main__":
    main()
