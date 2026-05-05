# Status

Living doc. Update as part of any non-trivial change so the next agent (possibly on a different machine and/or tool) has a clear "where were we" anchor.

---

## Last updated

**2026-05-05** — by Claude Code (Opus 4.6).

## Current state

**V0 slice 1 (Telegram capture → SQLite) implemented.** Bot captures raw text messages and stores them in SQLite.

Done:
- `src/solo/db.py` — SQLite schema (`entries` table), `get_connection`, `insert_entry`, `get_recent_entries`
- `src/solo/bot.py` — Telegram long-polling bot, `handle_message` with chat allowlist and defensive error handling
- `tests/test_db.py` — 8 tests (schema, insert, query)
- `tests/test_bot.py` — 6 tests (capture, metadata, allowlist, empty message, open allowlist, failure resilience)
- 14 tests passing, ruff clean
- `data/` directory set up with `.gitkeep`, gitignored for DB files

Pending manual verification:
- Smoke test with a real Telegram bot token (see Task 7 in `docs/superpowers/plans/2026-05-05-telegram-capture.md`)

## What's next

Per `AGENTS.md` V0 scope, in order:

1. ~~Telegram capture → SQLite~~ — done
2. **`LLMClient` (OpenRouter) + `llm_calls` trace table.** Foundation for every subsequent LLM call.
3. **Lazy classifier.** When `/top3` is invoked, classify any unclassified rows first.
4. **`/top3` and `/log` commands.**
5. **Classifier eval harness** (`evals/classify.jsonl` + `scripts/eval.py`).

## Open decisions deferred to implementation

- Exact OpenRouter model IDs (verify at https://openrouter.ai/models when wiring `LLMClient`)
- Whether to keep raw Telegram message JSON alongside `raw_text` (probably yes — cheap, future-proof)
- Schema specifics: column types, indexes, FTS for `/log` search
- Apple Reminders bridge approach (V2 — out of V0 scope)

## Blockers

None.

## How to use this doc going forward

- Update **Last updated** with date and tool/model on every change.
- Update **Current state** with what's actually true now (not what was decided).
- Update **What's next** with the immediately-next slice. Keep it small.
- Move resolved decisions out of **Open decisions deferred** and into `docs/decisions/NNNN-*.md` ADRs.
- Add to **Blockers** the moment something blocks progress; remove when unblocked.

This doc is not a journal. It's a snapshot. If you want a journal, that's what git log is for.
