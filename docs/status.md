# Status

Living doc. Update as part of any non-trivial change so the next agent (possibly on a different machine and/or tool) has a clear "where were we" anchor.

---

## Last updated

**2026-05-10** — by Claude Code (Opus 4.7).

## Current state

**V0 slice 2 (LLMClient + `llm_calls` trace table) implemented.** Every LLM call in solo now goes through `solo.llm.LLMClient` and writes one row to `llm_calls`.

Done in slice 2:
- `src/solo/trace.py` — `ensure_schema`, `record_call`
- `src/solo/prompts.py` — `load`, `render`
- `src/solo/llm.py` — `MODEL_PRICING`, `compute_cost`, `LLMClient` (async, `chat` + `structured`)
- `src/solo/prompts/` — directory created (empty; first prompt lands in slice 3)
- `src/solo/bot.py` — calls `trace.ensure_schema` on startup
- `tests/test_trace.py`, `tests/test_prompts.py`, `tests/test_llm.py`, `tests/test_llm_live.py` — 25 new tests, all green
- `docs/concepts/llm-api-basics.md` and `docs/concepts/observability-trace-table.md` — first concept primers
- `docs/decisions/0001-trace-write-timing.md` and `0002-llm-module-split.md` — first ADRs
- `README.md` — Environment section added

Pending manual verification:
- Live integration test against OpenRouter — run `OPENROUTER_API_KEY=… uv run pytest tests/test_llm_live.py -v` once.

## What's next

Per `AGENTS.md` V0 scope, in order:

1. ~~Telegram capture → SQLite~~ — done (slice 1)
2. ~~`LLMClient` (OpenRouter) + `llm_calls` trace table~~ — done (slice 2)
3. **Lazy classifier.** Write `src/solo/prompts/classifier.md`, write `src/solo/classifier.py` that calls `LLMClient.structured("classifier", ClassifyResult, model=os.environ["SOLO_CLASSIFY_MODEL"], vars=...)`. Triggered when `/top3` is invoked: classify any unclassified rows first.
4. **`/top3` and `/log` commands.**
5. **Classifier eval harness** (`evals/classify.jsonl` + `scripts/eval.py`).

## Open decisions deferred to implementation

- Verify `MODEL_PRICING` rates against openrouter.ai/models when wiring real classifier calls.
- Whether OpenRouter's `response_format=BaseModel` works reliably across the Minimax/Kimi backends (flagged risk in slice-2 spec). Live integration test will tell us.
- Schema specifics for the classifier: column types, indexes, FTS for `/log` search.
- Apple Reminders bridge approach (V2 — out of V0 scope).

## Blockers

None.

## How to use this doc going forward

- Update **Last updated** with date and tool/model on every change.
- Update **Current state** with what's actually true now (not what was decided).
- Update **What's next** with the immediately-next slice. Keep it small.
- Move resolved decisions out of **Open decisions deferred** and into `docs/decisions/NNNN-*.md` ADRs.
- Add to **Blockers** the moment something blocks progress; remove when unblocked.

This doc is not a journal. It's a snapshot. If you want a journal, that's what git log is for.
