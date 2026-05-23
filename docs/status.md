# Status

Living doc. Update as part of any non-trivial change so the next agent (possibly on a different machine and/or tool) has a clear "where were we" anchor.

---

## Last updated

**2026-05-23** — by Claude Code (Opus 4.7).

## Current state

**V0 is complete.** All six items in `AGENTS.md` §V0 scope ship:

1. Telegram capture → SQLite (slice 1)
2. `LLMClient` + `llm_calls` trace table (slice 2)
3. Lazy classifier (slice 3)
4. `/top3` and `/log` commands (slice 4)
5. Prompts as files in `src/solo/prompts/` (continuous, slices 3+)
6. Classifier eval harness (slice 5 — just landed)

Slice 5 added:
- `src/solo/evals.py` — pure scoring (`score_kind`, `score_priority`), confusion matrix builder, and `summarize` aggregator.
- `src/solo/trace.py` — new `aggregate_range(conn, id_min, id_max)` helper for cost/latency reporting scoped to one eval run.
- `scripts/eval.py` — sequential runner. Reads `evals/classify.jsonl`, calls `LLMClient.structured`, scores, prints a terminal table, writes a JSON sidecar to `evals/results/<UTC-ISO>.json`.
- `evals/classify.jsonl` — 15 hand-labeled seed entries covering all 4 kinds × 3 priorities, with a few intentional edges.
- `evals/results/.gitkeep` + `.gitignore` rule to keep run outputs local.
- `docs/decisions/0006-skip-summary-auto-grading.md` — ADR-0006.
- `docs/concepts/evaluating-llm-outputs.md` — concept primer (also backfills the concepts index).
- `docs/walkthrough.html` updated; slice 5 card flipped to done, V1 promoted to next.

Pending manual verification:
- Live classifier test against OpenRouter — `OPENROUTER_API_KEY=… uv run pytest tests/test_classifier_live.py -v`.
- End-to-end smoke of `/top3` + `/log` against a live Telegram chat.
- Real eval run: `OPENROUTER_API_KEY=… uv run python scripts/eval.py` — the harness shape is unit-tested, but the first real run is the signal on whether MiniMax M2.7 produces sane numbers on this seed set.

## What's next

V0 is done. V1 work begins. Per `docs/architecture.md` §1, V1 introduces the small agent surface:

1. ~~Telegram capture → SQLite~~ — done (slice 1)
2. ~~`LLMClient` + `llm_calls` trace table~~ — done (slice 2)
3. ~~Lazy classifier~~ — done (slice 3)
4. ~~`/top3` + `/log` commands~~ — done (slice 4)
5. ~~Classifier eval harness~~ — done (slice 5)
6. **V1 — `/expand`**: hand-rolled tool-use loop for open-ended thinking. Per `docs/architecture.md` §3, this is the first command where solo earns a real agent loop (~100 lines). Likely sub-slices: trace `agent_runs` + `agent_steps` tables, the loop itself, the `expand` prompt, the Telegram surface, evals for `expand` quality.

Before starting V1, brainstorm the agent loop shape. The whole point of solo's pedagogical bent is owning that loop — don't skip the design conversation.

## Open decisions deferred to implementation

- After a real eval run lands: A/B the heuristic-only ranker (ADR-0005) against a Heuristic + LLM scoring pass shape. Decision criterion = measurable improvement on the eval set.
- After embedding pipeline lands (V1+): revisit ADR-0006 (auto-grading summary text via cosine similarity).
- Verify `MODEL_PRICING` rates against openrouter.ai/models once real eval cost numbers come in.
- Apple Reminders bridge approach (V2 — out of V0+V1 scope).

## Blockers

None.

## How to use this doc going forward

- Update **Last updated** with date and tool/model on every change.
- Update **Current state** with what's actually true now (not what was decided).
- Update **What's next** with the immediately-next slice. Keep it small.
- Move resolved decisions out of **Open decisions deferred** and into `docs/decisions/NNNN-*.md` ADRs.
- Add to **Blockers** the moment something blocks progress; remove when unblocked.

This doc is not a journal. It's a snapshot. If you want a journal, that's what git log is for.
