# Reading Response — Week 9

**Daniel Guo**

## Primary paper (project-specific pick)

Jin, Zhijing, et al. 2024. *"Can Large Language Models Infer Causation from Correlation?"* ICLR 2024. (Introduces the **Corr2Cause** benchmark.)

**Research question.** Given a purely statistical description of a system (a correlation or conditional-independence structure among variables, with the variable names deliberately kept abstract or unfamiliar), can an LLM correctly infer the underlying causal structure — without leaning on memorized real-world facts about what those variables "usually" do?

**Data / evidence.** The authors built Corr2Cause, a benchmark of over 200,000 examples, each a formally correct correlational statement paired with a causal-structure question, generated so that solving it requires actual causal-inference rules (e.g. d-separation) rather than world knowledge. They evaluated 17 LLMs (both prompted and fine-tuned).

**Main finding.** All 17 models performed close to random chance at pure causal inference from correlational structure. Fine-tuning improved in-distribution performance but the resulting skill did not transfer to out-of-distribution phrasings or variable names — meaning the models weren't learning the underlying causal-inference rule, they were pattern-matching to phrasings similar to their training data.

**One idea for my project.** Jin et al. test the direction *correlation → causal structure* and show LLMs fail it by defaulting to surface pattern-matching instead of genuine inference. My project tests the mirror-image direction — *plausible causal story → expected correlation* (I give the model a CoC's fire history, no homelessness data, and ask it to estimate what the wildfire-homelessness correlation would be). The result rhymes with theirs: instead of reasoning about what the actual joint statistics of a sparse, noisy 44-region dataset would look like, the model reaches for a strong real-world prior ("fire destroys homes → homelessness should rise") and reports that prior back with high confidence, regardless of whether the specific region's fire history is even substantial. Corr2Cause's framing gives me useful language for this: the model isn't doing causal *or* correlational reasoning about the specific data in front of it — it's substituting a memorized narrative for either, in both their causation-from-correlation direction and my correlation-from-causation direction. That's a stronger claim to make in my write-up than "the AI is biased" on its own.

## Shared paper

Manvi, Rohin, et al. 2024. *"Large Language Models Are Geographically Biased."* ICML 2024.

Manvi et al. compare LLM zero-shot predictions against real geospatial ground truth (LLMs actually do well on objective measures, up to ρ = 0.89) but find a specific, quantifiable bias against lower-socioeconomic regions on *subjective* questions (attractiveness, morality, intelligence), correlated with regional wealth (up to r = 0.70). Two things from their method map directly onto mine: (1) they don't just say "biased" — they build a quantitative bias score comparing model output to ground truth, which is exactly what `compare_ai_vs_ground_truth.py` does (mean signed error, sign-flip rate); (2) their bias is systematic and directional (against poorer regions specifically), not random noise — mine is also systematic and directional (positive-skewed, not symmetric noise around the true value), which is the detail that makes both papers' findings a claim about *bias*, not just *imprecision*.

## Synthesis for my own framing

Both papers reinforce the same structural point I should lean on in my write-up: an LLM's error against ground truth is more interesting, and more publishable, when it is *systematic* (same direction every time, replicates across independent trials) rather than merely noisy. My own results already show this — across 10 independent blind trials, 0 of 440 per-CoC estimates were ever negative, and the bias direction (overstating the fire→homelessness relationship) was stable across every trial. That stability is what elevates "the AI got this wrong" into "the AI has a specific, repeatable failure mode," which is the same evidentiary bar both assigned papers use.

## Robustness check: is year a factor in the bias? (raised in class, 2026-09-06)

Bo Zhao's direct suggestion after seeing the dashboard's year control: since the ground truth and the AI's bias both vary across CoCs, does *when* a CoC's fire history happened change anything? I checked this three ways rather than picking whichever framing looked most favorable:

| Check | Result |
|---|---|
| Correlation between a CoC's peak (largest-acreage) fire year and the AI's signed error for that CoC | r = -0.017 |
| Same, against absolute error | r = +0.007 |
| Mean absolute error grouped by decade of peak fire year (2000s / 2010s / 2020s) | 0.264 / 0.421 / 0.290 — no monotonic trend |
| Ground truth statewide pooled r, first half of the data (2007–2015) vs. second half (2016–2024) | +0.041 vs. -0.001 — both still ≈ zero |

**Conclusion: no, year is not a factor.** The null ground-truth result and the AI's overestimation bias are both stable across the full 2007–2024 period — not concentrated in, or explained by, any particular era, and not correlated with how recent (and presumably how well-covered in the model's training data) a CoC's worst fire was. This is a useful negative result in its own right: it rules out "the AI is just overweighting recent, widely-reported disasters" as the specific mechanism, even though that was my leading hypothesis for *why* the bias exists. The bias appears to be a more general prior about wildfire and housing instability, not narrowly anchored to famous recent events. This check is also computed live on the dashboard (AI vs. Ground Truth tab, "Is year a factor?" line) from the same underlying data, so it stays correct if the estimates are regenerated.

## Limitations (raised in class, 2026-09-06)

Bo Zhao asked everyone to discuss, in a limitations/discussion section, that the underlying data itself can carry bias or gaps independent of anything the AI does. For this project:

- **HUD PIT counts are a single-night snapshot**, taken by volunteer counts that vary in coverage and methodology year to year and CoC to CoC — not a continuous census. Two CoCs' counts in the same year aren't necessarily comparable in *how* thoroughly they were counted, only in what each reports.
- **HUD's homelessness definition is narrow by design**: it excludes people doubled up with family/friends, in motels via insurance, or in FEMA transitional housing — exactly the categories a lot of disaster-displaced people fall into (see the Butte County case study). The near-zero correlation may partly reflect this definitional boundary, not just an absence of real-world effect.
- **CAL FIRE's DINS structure-damage data only starts in 2013** — the "structures destroyed" robustness check earlier in this project silently has no signal for 2000-2012 fires, which could bias that specific check toward the modern era without it being visible in the results.
- **The ≥1,000-acre fire filter** (kept for dataset size/browser performance) excludes smaller fires that still destroyed housing — a small subdivision fire under 1,000 acres wouldn't appear in this dataset at all, even if it displaced people.
- **CoC boundaries are treated as fixed** across 2007–2024 in this analysis (the current boundary set is applied to all years), when in reality HUD has periodically merged, split, or renamed CoCs over that period. Years compared for the "same" CoC number may not correspond to exactly the same geographic footprint throughout.
- **The AI estimates were produced via batched sub-agent calls** (all 44 regions given to the model in one context per trial, not fully isolated one-at-a-time API calls) because no billed Anthropic API key was available. This means a trial's estimate for one region could in principle be influenced by seeing the other 43 in the same context, which a fully isolated per-region call (the original design) would have prevented.
- **Some per-CoC ground-truth Pearson r values rest on very few data points** — a handful of CoCs have only 1-2 recorded fire-years, making their individual "ground truth" r a noisy estimate in its own right, not a fixed truth. The statewide pooled r (n=756) is the more reliable headline number for this reason.
