# 0006 — Skip auto-grading the classifier `summary` field in evals

**Status:** accepted
**Date:** 2026-05-23

## Context

The classifier produces three fields per entry: `kind`, `priority`, `summary`. The first two are categorical and easy to grade against a labeled set. `summary` is free text — one short line capturing the essence of the input. Grading prose is fundamentally different from grading categories.

Three options for grading summary text:

1. **Skip auto-grading; surface predicted summaries in the JSON sidecar for human spot-check.** Cheapest. Schema already enforces non-empty + ≤120 chars.
2. **Character or word-overlap heuristic (Jaccard, BLEU).** Cheap but noisy — a perfectly correct rephrasing scores low.
3. **Embedding-based cosine similarity.** Captures semantic match but requires an embedding pipeline (Voyage API or `sentence-transformers`) we don't have yet — that's slice 6+ territory per `docs/architecture.md` §10.

## Decision

Option 1 for V0. Don't auto-grade summary. Predictions are recorded in the JSON sidecar; a human can scan them in seconds to catch obvious regressions.

## Consequences

**Easier:**
- No false signal from naive overlap metrics.
- No new dependency (embeddings) until we actually need it for dedup.
- Eval runtime stays predictable — one LLM call per row, no embedding round-trip.

**Harder:**
- Summary regressions could ship without being caught by a number.
- The eval table presents only kind+priority scores; "is this prompt better at summarising?" remains a vibes call until we have embeddings.

## Alternatives considered

- **Word-overlap (Jaccard, ROUGE-L)** — rejected; noisy enough that a stylistic rephrase looks like a regression. False signal is worse than no signal here.
- **Embedding cosine** — rejected for now; revisit when slice 6 (dedup) introduces an embedding pipeline. At that point both consumers (dedup + eval) share the same Voyage/local-model dependency.
