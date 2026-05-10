# Status

Living doc. Update as part of any non-trivial change so the next agent (possibly on a different machine and/or tool) has a clear "where were we" anchor.

---

## Last updated

**2026-05-10** — by Claude Code (Opus 4.7).

## Current state

**V0 slice 3 (lazy classifier) implemented.** Each `entries` row can be turned into a `(kind, summary, priority)` triple by `solo.classifier.classify_pending`, written back to the row. Bounded-retry failure handling. Sequential. Never raises.

Done in slice 3:
- `src/solo/classifier.py` — `ClassifyResult` Pydantic schema + `classify_pending`
- `src/solo/prompts/classifier.md` — first prompt-as-file
- `src/solo/db.py` — schema extension + idempotent migration; `fetch_unclassified`, `apply_classification`, `record_classification_failure`
- `tests/test_classifier.py`, `tests/test_classifier_live.py` — unit + gated live tests
- `tests/test_db.py` — migration + helper tests
- `docs/concepts/structured-outputs.md` — concept primer
- `docs/decisions/0003-classifier-on-entries-vs-side-table.md` — ADR

Pending manual verification:
- Live test against OpenRouter — `OPENROUTER_API_KEY=… uv run pytest tests/test_classifier_live.py -v`.

## What's next

Per `AGENTS.md` V0 scope, in order:

1. ~~Telegram capture → SQLite~~ — done (slice 1)
2. ~~`LLMClient` (OpenRouter) + `llm_calls` trace table~~ — done (slice 2)
3. ~~Lazy classifier~~ — done (slice 3)
4. **`/top3` and `/log` commands.** `/top3` invokes `classify_pending` first, then ranks by `(priority desc, created_at desc)` filtered to soft tasks + ideas. `/log` groups by `kind` and prints recent.
5. **Classifier eval harness** (`evals/classify.jsonl` + `scripts/eval.py`).

## Open decisions deferred to implementation

- Verify `MODEL_PRICING` rates against openrouter.ai/models when wiring real classifier calls.
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
