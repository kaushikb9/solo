# 0001 — Single post-call write to `llm_calls`

**Status:** accepted
**Date:** 2026-05-09

## Context

Every LLM call must write a row to `llm_calls` for observability. Two reasonable patterns:

1. **Post-call only.** One INSERT after the API call returns (or errors). One row per call.
2. **Pre-call + update.** INSERT a `status='pending'` row at the start, UPDATE on completion. Two writes per call. Survives mid-call process crashes (the row is visible while the call is in flight).

V0 has very short calls (a few hundred ms), low call volume (one user), and no production-grade need to debug crash-mid-call scenarios.

## Decision

Single post-call write. The whole API call is wrapped in `try/except`; both success and failure paths write exactly one row.

## Consequences

**Easier:**
- One INSERT per call, less code, fewer failure modes.
- The row is "complete" when read — no `pending` rows to filter out.

**Harder:**
- A process crash mid-call leaves no record of the call. OpenRouter's logs (or local stderr) are the only trace.
- Long-running calls (e.g. multi-minute streaming) won't appear in queries until they complete.

## Alternatives considered

- **Pre-call + update** — rejected for V0 because crash visibility is not a current pain point and the 2x write cost (in code complexity) outweighs the benefit at this scale.
- **Append-only event stream** (one row per state transition) — rejected as overengineered for a single-user system.

Revisit if/when calls reliably take >5s or process crashes start hiding work.
