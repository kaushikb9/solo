# Architecture Decision Records

Short ADRs for non-trivial decisions made during implementation. Top-level decisions made before code lived in [`../architecture.md`](../architecture.md) and don't need duplicating here.

## How to write one

Use `/decision <topic>` or this structure:

```
# NNNN. <Title>

**Status**: proposed | accepted | superseded by NNNN
**Date**: YYYY-MM-DD

## Context
What's the situation, what forces are at play.

## Decision
What was chosen.

## Consequences
What becomes easier. What becomes harder.

## Alternatives considered
- **Option B** — one line, reason rejected.
- **Option C** — one line, reason rejected.
```

Length: ~250 words. The point is recording *why*, not exhaustive prose.

## Index

- [0001 — Trace write timing](0001-trace-write-timing.md)
- [0002 — Three-module split: `llm.py` / `prompts.py` / `trace.py`](0002-llm-module-split.md)
- [0003 — Classifier output on entries vs side table](0003-classifier-on-entries-vs-side-table.md)
- [0004 — `LLMClient` opens a fresh SQLite connection per trace write](0004-llmclient-connection-lifecycle.md)
- [0005 — `/top3` uses a heuristic-only ranker, no second LLM pass](0005-heuristic-only-ranking.md)
- [0006 — Skip auto-grading the classifier `summary` field in evals](0006-skip-summary-auto-grading.md)
- [0007 — `/drop` is a hard delete; `/done` is the soft-state half](0007-drop-is-hard-delete.md)
- [0008 — `@name` extraction is a regex at insert time, not an LLM-inferred field](0008-mention-extraction-is-regex.md)
