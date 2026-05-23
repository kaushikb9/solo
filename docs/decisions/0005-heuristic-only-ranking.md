# 0005 — `/top3` uses a heuristic-only ranker, no second LLM pass

**Status:** accepted
**Date:** 2026-05-23

## Context

`docs/architecture.md` §1 lists `/top3` ranking as "Heuristic + single LLM scoring pass" — a heuristic narrows the pool, then an LLM picks the best 3 from the candidate set. That shape is what most agentic systems converge on for ranking.

Slice 3 introduced a classifier that already assigns a `priority` (low/medium/high) at the moment each entry is captured-and-classified. Once that signal exists, a second LLM call to "rank" the already-prioritised entries does very little additional work: the high-priority items are already the candidates a scoring pass would pick.

V0 also has no metric for what "good ranking" means. Without an eval harness (slice 5), we'd be choosing between two opaque rankers with no way to compare them. Better to ship the simpler one and *measure*.

## Decision

`/top3` ranks purely by `(priority desc, created_at desc)` filtered to `soft_task` + `idea`. No second LLM call. Implementation lives in `src/solo/rank.py` as a pure function.

## Consequences

**Easier:**
- Zero per-`/top3` LLM cost beyond the classifier backlog drain.
- Latency for `/top3` is dominated by classification, not ranking.
- The ranker is deterministic — testable as a pure function, no flakiness, no eval needed.

**Harder:**
- Two high-priority `idea`s captured minutes apart are sorted only by recency; an LLM scorer might surface a better contextual choice.
- If the classifier mis-assigns priority for a single entry, `/top3` is wrong by that exact amount — there's no second-opinion layer.

## Alternatives considered

- **Heuristic + LLM scoring pass** — rejected for V0; revisit after the slice-5 eval harness exists and we can measure whether the second pass improves a real metric.
- **LLM-only ranking** (ask the model to rank a pool of N) — rejected; the classifier-assigned `priority` is the signal we already paid for; ignoring it doubles cost without adding information.
