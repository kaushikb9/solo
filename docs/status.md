# Status

Living doc. Update as part of any non-trivial change so the next agent (possibly on a different machine and/or tool) has a clear "where were we" anchor.

---

## Last updated

**2026-05-24** — by Claude Code (Opus 4.7).

## Current state

**V0.1 is complete.** V0 (capture → classifier → /top3 + /log → trace table → prompts-as-files → eval harness) shipped over slices 1–5. Slice 6 added the admin surface and visual refresh kb wanted after a few days of real use.

Commands available:

- `/top3` — top 3 from `soft_task` + `idea`, terse format with emoji, age, and aging-items section.
- `/list` — active items only, grouped by kind, with IDs.
- `/all` — everything including done items (✅ marker).
- `/drop <id> [<id>...]` — hard delete.
- `/done <id> [<id>...]` — soft mark complete; stays in `/all`.
- `/redo <id>` — reset classification fields; next `/top3` re-classifies.
- `/help` — list of commands.

Schema additions in slice 6: `done` (boolean, default 0) and `mentions` (CSV from `@\w+` regex at insert time).

Slice 6 manifest:
- `src/solo/mentions.py` — pure `extract(raw_text)`.
- `src/solo/db.py` — added `mark_done`, `delete_entry`, `reset_for_reclassification`, `fetch_active`; `fetch_classified` now filters `done=0`; `insert_entry` populates `mentions`; migration adds the two new columns idempotently.
- `src/solo/commands.py` — rewritten formatters (`format_top3`, `format_list`, `format_all`) with `_age` and `_marker` helpers; new handlers for `/list`, `/all`, `/drop`, `/done`, `/redo`, `/help`; `handle_top3` now surfaces an aging-items section.
- `src/solo/bot.py` — registers all new `CommandHandler`s; `/log` removed.
- `docs/decisions/0007-drop-is-hard-delete.md` — ADR-0007.
- `docs/decisions/0008-mention-extraction-is-regex.md` — ADR-0008.
- `docs/walkthrough.html` updated through slice 6.

Pending manual verification:
- Live classifier test against OpenRouter — `OPENROUTER_API_KEY=… uv run pytest tests/test_classifier_live.py -v`.
- End-to-end smoke of all V0.1 commands against a live Telegram chat.
- Real eval run: `OPENROUTER_API_KEY=… uv run python scripts/eval.py`.

## What's next

1. ~~Telegram capture → SQLite~~ — done (slice 1)
2. ~~`LLMClient` + `llm_calls` trace table~~ — done (slice 2)
3. ~~Lazy classifier~~ — done (slice 3)
4. ~~`/top3` + `/log` commands~~ — done (slice 4)
5. ~~Classifier eval harness~~ — done (slice 5)
6. ~~Admin surface (/list, /all, /drop, /done, /redo, /help) + visual refresh~~ — done (slice 6)
7. **V1 — `/expand`**: the first hand-rolled agent loop, per `docs/architecture.md` §1/§3. Sub-slices likely: `agent_runs` + `agent_steps` tables, the loop itself, the `expand` prompt, the Telegram surface, evals for `expand` quality. Earns its own brainstorm + spec + plan cycle.

## Open decisions deferred to implementation

- After a real eval run lands: A/B the heuristic-only ranker (ADR-0005) against a Heuristic + LLM scoring pass.
- After a week of real use of V0.1: reconsider whether nameless external asks (the 🔔 slot reserved in ADR-0008) are common enough to add LLM-inferred source.
- After an embedding pipeline lands (V1+): revisit ADR-0006 (auto-grading summary text).
- Verify `MODEL_PRICING` rates against openrouter.ai/models once real eval cost numbers come in.
- Apple Reminders bridge approach (V2).

## Blockers

None.

## How to use this doc going forward

- Update **Last updated** with date and tool/model on every change.
- Update **Current state** with what's actually true now (not what was decided).
- Update **What's next** with the immediately-next slice. Keep it small.
- Move resolved decisions out of **Open decisions deferred** and into `docs/decisions/NNNN-*.md` ADRs.
- Add to **Blockers** the moment something blocks progress; remove when unblocked.

This doc is not a journal. It's a snapshot. If you want a journal, that's what git log is for.
