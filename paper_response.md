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

Both papers reinforce the same structural point I should lean on in my write-up: an LLM's error against ground truth is more interesting, and more publishable, when it is *systematic* (same direction every time, replicates across independent trials) rather than merely noisy. My own results already show this — across 5 (soon 10) independent blind trials, 0 of 220+ per-CoC estimates were ever negative, and the bias direction (overstating the fire→homelessness relationship) was stable across every trial. That stability is what elevates "the AI got this wrong" into "the AI has a specific, repeatable failure mode," which is the same evidentiary bar both assigned papers use.
