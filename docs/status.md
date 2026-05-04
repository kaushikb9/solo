# Status

Living doc. Update as part of any non-trivial change so the next agent (possibly on a different machine and/or tool) has a clear "where were we" anchor.

---

## Last updated

**2026-05-04** — by Claude Code (Opus 4.7).

## Current state

V0 scaffolding complete. **No implementation code yet.** Repo is set up for cross-tool agent collaboration:

- Design docs settled (`docs/requirements.md`, `docs/architecture.md`, `docs/alternates/pi-runtime.md`)
- Agent guidance written (`AGENTS.md` canonical, `CLAUDE.md` pointer)
- Convention scaffolding in place (`.claude/agents/solo-reviewer.md`, `.claude/commands/{concept,decision}.md`)
- Documentation rituals in place (`docs/concepts/`, `docs/decisions/`)
- Project skeleton (`pyproject.toml`, `src/solo/__init__.py`, `.env.example`, `.gitignore`)
- superpowers plugin installed at user level (Claude Code only — re-install on each machine)

## What's next

Per `AGENTS.md` V0 scope, in order:

1. **Telegram capture → SQLite.** Smallest first slice. Bot polls Telegram, every message becomes a raw row in `entries`. Reply with `captured`. No classification yet.
2. **`LLMClient` (OpenRouter) + `llm_calls` trace table.** Foundation for every subsequent LLM call.
3. **Lazy classifier.** When `/top3` is invoked, classify any unclassified rows first.
4. **`/top3` and `/log` commands.**
5. **Classifier eval harness** (`evals/classify.jsonl` + `scripts/eval.py`).

Recommended first slice: **#1 alone**. Ship Telegram capture before LLM anything. Validates the bot stack and the SQLite schema with zero LLM cost.

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
