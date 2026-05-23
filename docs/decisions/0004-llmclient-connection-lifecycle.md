# 0004 — `LLMClient` opens a fresh SQLite connection per trace write

**Status:** accepted
**Date:** 2026-05-23

## Context

`LLMClient` writes one row to the `llm_calls` table for every call (`solo.llm._write_trace`, `src/solo/llm.py:161`). Today, each trace write opens a fresh SQLite connection via `get_connection(self._db_path)`, calls `trace.record_call`, and closes the connection again. The same shape applies on the error path — both `chat` and `structured` route through `_write_trace`.

Three reasonable shapes exist:

1. **Fresh connection per write (current).** Cheapest in lifecycle complexity. Each write self-contains its connect/commit/close. No thread-safety surprises. Higher per-call latency cost (~1–2ms of `open + WAL pragma + executescript + migration check`).
2. **One connection cached on the `LLMClient` instance.** One open, many writes. Faster per-call (no reopen overhead). Lifecycle is now tied to client lifetime; tests need to remember to close. SQLite connections aren't async-safe across the asyncio loop, but `LLMClient` is single-threaded in V0, so practical risk is low.
3. **Connection injected from the caller.** The caller (Telegram bot) owns the connection and threads it through. Cleanest from a dependency-flow perspective, but forces every call site to know that the LLM client needs a DB connection — a leaky abstraction for a project where the trace table is meant to be invisible.

V0 has one Telegram process, single asyncio loop, very low call volume (one classifier call per pending entry per `/top3` invocation — order of dozens per day at most). The reopen cost is negligible at this volume.

The hot path that would care is `/top3`: if a backlog of 50 unclassified entries piles up, `classify_pending` makes 50 sequential `structured` calls, each opening and closing a connection twice (once at start of call for the trace, plus the call site's own DB connection for `apply_classification`). At ~2ms of overhead each, that's ~100ms of pure reopen latency in a `/top3` worst case — still imperceptible against the network latency of 50 LLM calls.

## Decision

Keep the fresh-connection-per-trace-write shape (shape 1) for V0.

Revisit when **any** of these triggers fire:

1. `/top3` measured latency budget gets blown by trace-write overhead (use the `latency_ms` we already record to detect).
2. We add a second writer surface (Mac CLI, eval harness) that also wants to share trace infrastructure — at that point a shared `LLMClient` lifetime makes sense.
3. Trace volume jumps by an order of magnitude (e.g. when `expand`/`review` agent loops land in V1 — each loop iteration is a trace row).

## Consequences

**Easier:**
- Zero connection-lifecycle bugs to chase. Each write is fully self-contained.
- Tests don't need to teardown a long-lived connection — `LLMClient` can be GC'd freely.
- The single-process WAL-mode database tolerates concurrent open/close without contention at V0 volume.

**Harder:**
- Per-call latency overhead (~2ms) that compounds linearly with trace volume.
- Repeated `executescript(_SCHEMA)` + `_migrate_entries` runs on every connection open. Both are idempotent and fast, but they're wasted work.
- If we ever move to a remote DB (Turso/libSQL), reopen cost becomes a round-trip and the calculus changes — this ADR will need re-litigating then, not just revisiting.

## Alternatives considered

- **Cache one connection on `LLMClient`** — rejected for V0 because the latency savings are imperceptible and lifecycle complexity is real. Reconsider when triggers above fire.
- **Inject the connection from the caller** — rejected because it leaks the trace-table dependency into every LLM call site. The trace table is supposed to be a passive observer.
