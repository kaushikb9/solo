# Status

Living doc. Update as part of any non-trivial change so the next agent (possibly on a different machine and/or tool) has a clear "where were we" anchor.

---

## Last updated

**2026-05-23** — by Claude Code (Opus 4.7).

## Current state

**V0 slice 4 (`/top3` + `/log`) implemented.** The bot now accepts two commands in addition to plain-text capture:

- `/top3` — synchronously drains any classifier backlog via `await classify_pending(...)`, then ranks `soft_task` + `idea` entries by `(priority desc, created_at desc)` and replies with the top 3.
- `/log` — replies with the last 20 entries grouped by `kind` in a fixed section order (`idea`, `soft_task`, `hard_task`, `note`, `unclassified`).

`LLMClient` is now instantiated in `bot.main()`. `OPENROUTER_API_KEY` is required at boot (fail-fast).

Done in slice 4:
- `src/solo/rank.py` — pure `top3(entries)` deterministic ranker.
- `src/solo/commands.py` — `handle_top3`, `handle_log` + pure formatters `format_top3`, `format_log`.
- `src/solo/db.py` — `fetch_classified(conn, kinds, limit)` helper.
- `src/solo/bot.py` — `CommandHandler` wiring + `LLMClient` instantiation.
- `tests/test_rank.py`, `tests/test_commands.py` — full TDD coverage of pure + handler paths.
- `tests/test_db.py` — extended with `TestFetchClassified`.
- `docs/decisions/0004-llmclient-connection-lifecycle.md` — ADR-0004.
- `docs/decisions/0005-heuristic-only-ranking.md` — ADR-0005.
- `docs/walkthrough.html` — visual end-to-end explainer, updated through slice 4.

Pending manual verification:
- Live classifier test against OpenRouter — `OPENROUTER_API_KEY=… uv run pytest tests/test_classifier_live.py -v`.
- End-to-end smoke of `/top3` and `/log` against a live Telegram chat — bot wiring is untested except via handler-level integration tests.

## What's next

Per `AGENTS.md` V0 scope, in order:

1. ~~Telegram capture → SQLite~~ — done (slice 1)
2. ~~`LLMClient` (OpenRouter) + `llm_calls` trace table~~ — done (slice 2)
3. ~~Lazy classifier~~ — done (slice 3)
4. ~~`/top3` and `/log` commands~~ — done (slice 4)
5. **Classifier eval harness** (`evals/classify.jsonl` + `scripts/eval.py`). Single biggest classifier quality win — turns "is this prompt better" from vibes into a number.

## Open decisions deferred to implementation

- After slice 5: A/B the heuristic-only ranker (ADR-0005) against a Heuristic + LLM scoring pass shape. Decision criterion = measurable improvement on the eval set.
- Verify `MODEL_PRICING` rates against openrouter.ai/models when running real `/top3` traffic.
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
