# Proof of concept: study-paper literature graph x local Ollama for rich tooltips (2026-11-17)

Tags: **E** executed, **M** my manual judgement (subjective, n is small), **U** not verified.

## Question
Can the study PDFs behind `energy_market_intelligence` (`~/Documents/ngl_study_journals`: 10 academic papers + 6 news PDFs, about 170k words) be turned into a graph/vector library that a local Ollama model uses to improve the rich tooltips and pricing explanations in this repo?

## What was built (all new files; nothing existing in the live DB or `kb_ingest.py` was modified)
- `literature_kb.py`: separate store `runtime/literature_kb.db` (gitignored). `lit_docs`, `lit_chunks` (nomic-embed-text vectors), `lit_edges` (`part_of`, `next_chunk` structural; `semantic_neighbor` similarity only). PIT: `search()` returns only chunks with `available_epoch <= as_of`; availability = our ingest time. Reuses `kb_ingest.chunk_text` unchanged. Provenance is `source_document`, never `measured`, and it is in a different file so existing agents cannot retrieve it by accident.
- `scripts/poc_literature_tooltips.py`: stages `ingest | retrieval | generate | evidence | evidence_v3 | evidence_v4`.
- `tests/test_literature_kb.py`: 10 tests (PIT filter, idempotence, edges, per-doc cap, verbatim and abstention). Full suite: **193 passed** (E).

## Results (E: real run against live Ollama, qwen3:4b + nomic-embed-text, live engine payload)
**Ingest:** 16 docs, 667 chunks, 651 `next_chunk` + 667 `part_of` + 640 similarity edges, about 5 min on this machine.

**Retrieval sanity (10 concept queries, gold doc fixed in advance):** hit@1 9/10. The miss ("why do prices spike when supply capacity is tight") ranked the right paper's best chunk 36th; the same paper is rank 1 for concept-dense phrasings. Retrieval is phrasing-sensitive.

**Experiment 1, generative RAG (5 tooltip subjects x 3 conditions, same model, temp 0):** facts (every number computed by code) + literature.
| | A facts only | B +3 chunks | C +2 chunks +graph neighbours |
|---|---|---|---|
| passes guard | 5/5 | 2/5 | 4/5 (1 error: output truncated) |
| ungrounded numbers | 0 | 2 | 0 |
| invalid citation ids | n/a | 2 | 0 |
| avg latency | 10 s | 38 s | 37 s |
| pre-registered concept groups hit | 9/15 | 12/15 | 7/12 |
Observed failures (M): B echoed its own instructions on one subject; B wrote "2020s" from a paper title (caught by the number guard); B cited the literal string "FACTS". **Valid citation ids were frequently not supportive**: of 4 cited chunks I read, 1 supported (EU winter storage depletion, but EU not Henry Hub), 1 was a non sequitur (a supply-curve fit cited for a forward-curve shape), 2 did not support the sentence at all. A passed the guard while corrupting a formula ("* 10:00" for "* 100"): the guard ignores integers 0-10, a hole. All conditions repeated the engine's `CONTANGO` label on a seasonal curve (see FC-7). **Verdict: generative literature RAG with a 4B model is not an improvement; it lowers reliability and adds laundered citations.**

**Experiment 2, extractive evidence (verbatim sentence + verified source, abstain when below threshold; no generated literature prose):**
- Every quote is a verified verbatim substring of a PIT-available chunk (E, 100% across all runs); about 0.6-1.2 s per subject, no generation.
- Hold-out 1 (thresholds 0.70, partly informed by experiment 1): supported 3/3, abstained 0/2 (**failed**: a risk-premia sentence for "contract expiry", a title-page line for "settlement price").
- Hold-out 2 then exposed that "supported" quotes were titles (unterminated lines). Fix: a sentence must end in terminal punctuation and may not span a paragraph break. Hold-out 2 is contaminated by that fix (re-run: supported 2/3, abstained 3/3).
- **Clean hold-out 3** (pre-registered, threshold 0.72, fixed code): relevant quotes for all 3 expected-support questions (M: one specific figure about Russian gas share, one method abstract, one generic sentence); abstained 2/3 correctly; **false positive** on "current Brent price" (an ICE margin-rate sentence at 0.81 similarity: topically related, does not answer).
- Headline: **extractive evidence is trustworthy about provenance, fast and useful for conceptual tooltips; it cannot tell "related" from "answers the question"**, so the sample is small (n=14 over three rounds) and thresholds are tuned partly on seen data.

## Does it improve pricing calculations? No, and it should not be claimed to
No paper contains Henry Hub or NGL values for this period, so the literature cannot change a computed price, spread or ratio. For lineage and ratio tooltips (A vs B/C) the model added nothing over a deterministic template; the template (already in `web/app.js` as the richer forward-point tooltip) is more reliable. The only measured benefit is for *conceptual* tooltips (curve shape, seasonality, volatility): a labelled, verifiable "background" sentence with document and chunk id, shown beside the code-computed numbers.

## Recommendation
1. Do **not** pursue LLM-written explanations from literature on a 4B model.
2. If pursued, ship only extractive background quotes behind an explicit label ("Background, from <paper>"), threshold 0.72, with abstention; keep the store separate from `kb_nodes`. This needs an API/UI change and a release; **not built into the product** (U).
3. Higher value, no literature needed: derive structural curve facts deterministically (peak/trough month, winter-vs-shoulder spread) instead of the single `CONTANGO` label (FC-7), then let tooltips use them.
4. Close the guard hole (ignore-list for integers) before any LLM text is shown.

## Limits and unverified
Small n; my relevance judgements are subjective and unblinded; thresholds partly fit on seen data; only the first 520 characters of 4 cited chunks were read for support; qwen3:4b only (no larger model tried); no UI rendering; caption remnants can still pass as sentences; ingest/refresh is manual.

## Reproduce
```bash
cd /home/joey/Projects/henry_hub_atomic_agents
.venv/bin/python -m pytest tests/test_literature_kb.py -q
.venv/bin/python scripts/poc_literature_tooltips.py ingest       # idempotent; writes runtime/literature_kb.db only
.venv/bin/python scripts/poc_literature_tooltips.py retrieval
.venv/bin/python scripts/poc_literature_tooltips.py evidence_v4  # results in docs/poc/*.json
```
Raw outputs: `docs/poc/literature_tooltips_results.json`, `literature_evidence_results.json`, `literature_evidence_v3_results.json`, `literature_evidence_v4_results.json`.

## Model decision (2026-11-17)
Installed models are `qwen3:4b` and `nomic-embed-text` only; no larger model was pulled. Generative literature tooltips on `qwen3:4b` did not deliver what a user needs (reliable, supportable explanations): 2/5 passed the number/citation guard, citations were frequently unsupportive, one output echoed its prompt and one was truncated. Rather than download a larger model without evidence it would fix citation laundering, the approach was changed so that no generated prose is shown from the literature: **`nomic-embed-text` embeddings only, verbatim verified quotes with abstention.** Deterministic code (`curve_shape`) produces the explanatory numbers and structure shown in the shipped tooltip. The extractive literature evidence is **not wired into the public service** (it has no Ollama dependency by design, and the false-positive case "Brent today" means it needs a labelled, opt-in UI first).
