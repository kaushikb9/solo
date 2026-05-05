# Solo — Claude's Solution

Companion to `requirements.md`. Records the architectural direction, tech stack, hosting choice, and the patterns worth borrowing from production agent frameworks.

---

## 1. Architectural approach: deterministic spine + small agent surface

Reject the binary of "agent framework" vs "minimal pipeline." 90% of this system is deterministic; the remaining 10% (open-ended thinking) earns a real agent loop.

| Capability | Implementation | Agent reasoning? |
|---|---|---|
| Capture | Telegram bot writes raw entries to SQLite (or Turso) | No |
| Classify, summarize | Single-shot LLM call, structured output | No |
| Dedup | Embedding similarity + threshold | No |
| `top3` ranking | Heuristic + single LLM scoring pass | No |
| `log` | Direct SQL query, grouped output | No |
| `commit` to Reminders | Deterministic transition (Mac-side, see §8) | No |
| **`expand`** (interactive thinking) | Hand-rolled tool-use loop (~100 lines) | **Yes** |
| **`review`** (pattern hunting) | Hand-rolled tool-use loop over corpus | **Yes** |

The agent isn't orchestrating the system — it's a reasoning surface for two specific commands.

## 2. Frameworks: skip the runtime, borrow the patterns

Skip OpenClaw / Hermes / Pi as a runtime dependency. They're production agent frameworks designed for problems solo doesn't have (multi-tenant fleets, dynamic tool loading, planner-executor splits, long-running job queues).

But they encode patterns worth borrowing:

**Borrow at V0 (cheap, high leverage):**
- **Structured trace table.** Every LLM call gets a row — `(id, run_id, model, prompt_hash, input_tokens, output_tokens, latency_ms, cost_usd, created_at)`. ~20 lines, pays back forever in cost visibility and debugging.
- **Prompts as files.** `src/solo/prompts/classify.md` loaded at runtime. Diffable, versionable, swappable per model.
- **Eval harness for the classifier.** `evals/classify.jsonl` with ~30 hand-labeled entries + `scripts/eval.py` reporting accuracy. Single biggest quality win — turns "is this prompt better" from vibes into a number.

**Borrow at V1 (when `expand`/`review` exist):**
- **Runs and steps as DB rows.** `agent_runs(id, command, status, ...)`, `agent_steps(id, run_id, type, content, ...)`. Single biggest debugging win.
- **Tool decorator with Pydantic.** ~30-line homemade `@tool` decorator that generates JSON schema from type hints.
- **Iteration + token budgets.** `max_iterations=10`, `max_tokens=50_000` per run. Cheap insurance against runaway loops.

**Don't borrow:**
- Multi-agent orchestration / planner-executor splits — wrong shape
- DAG workflow engines — your loops are linear
- Dynamic tool loading — you'll have ~5 tools forever
- Long-running job queues — Telegram already gives you async pacing

## 3. Why hand-roll the agent loop instead of using a framework

Pedagogical: stated goal is to become effective at AI engineering and agentic systems. Frameworks hide the interesting parts (loop, tool dispatch, context management). Owning the loop teaches what frameworks abstract.

Practical: V0 has no agent loop at all — adopting a framework now pays complexity cost for features you don't use. By the time V1 (`expand`/`review`) needs a loop, you'll know exactly what shape it should take. Migrating *to* a framework later is cheaper than migrating off one.

## 4. Model-agnostic via OpenRouter

LLM access goes through **OpenRouter**: single API key, OpenAI-compatible endpoint, every major model behind one bill.

| Aspect | Decision |
|---|---|
| Default model | MiniMax M2.7 for classification, Kimi K2.6 for `expand`/`review` |
| Swap model | Change a string in env vars |
| Auth | OpenRouter API key |
| Markup | ~5% over direct provider — accepted for the simplicity |
| Tradeoff | Lose Anthropic SDK extras (Claude Agent SDK, prompt caching helpers). For this project's shape, fine — agent loop is hand-rolled anyway |

A thin `LLMClient` interface (~30 lines) wraps OpenRouter with one method per use case (`classify`, `summarize`, `score`, `expand_step`).

**Note on Claude OAuth:** Initially considered but dropped. Third-party apps using Claude OAuth bill against "extra usage" per-token, not the Pro/Max plan allowance. So OAuth offers a slightly nicer auth flow but no cost benefit over a plain API key.

## 5. Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| Package manager | `uv` |
| Telegram | `python-telegram-bot` with **long polling** (no webhook, no public URL) |
| Database | SQLite stdlib (V0) → Turso/libSQL when CLI surface is added |
| LLM | `openai` SDK pointed at OpenRouter |
| Structured outputs | `pydantic` |
| Embeddings (when dedup is needed) | Voyage API or `sentence-transformers` local |
| Linting | `ruff` |

No web framework. No ORM. No task queue. The bot is the only running process.

## 6. Hosting — Railway, with Turso to unlock multi-surface later

**Primary recommendation: Railway** ($5/mo Hobby plan).
- GitHub push → auto deploy
- Persistent volume for SQLite at `/data`
- Always-on, no cold starts
- Two env vars: `OPENROUTER_API_KEY` + `TELEGRAM_BOT_TOKEN`
- Long polling means no webhook / public URL / SSL config
- Zero OS maintenance

**Alternatives:**
- **Cloudflare Workers** — free, but requires TypeScript rewrite or Python beta + D1. Stack simplicity loss > $5/mo savings.
- **Fly.io** — ~$0–3/mo with 256MB VM + 1GB volume. Same Python+SQLite stack. Slightly more knobs than Railway.
- **Mac mini at home** — $0 but home network downtime is your problem.

## 7. DB choice: SQLite-on-volume vs Turso

**V0: SQLite stdlib + Railway volume.** Simplest, zero-config.

**When to switch to Turso (libSQL):** the moment you want a Mac CLI or any second surface. Turso is hosted SQLite over the wire with a generous free tier (9 GB, 1B row reads/mo). Both Railway bot and Mac CLI connect to the same DB via URL+token. Same SQL, drop-in via the `libsql` package.

This also weakens Railway's volume advantage and makes Cloudflare Workers a more honest alternative — though the TypeScript rewrite friction remains.

## 8. Apple Reminders bridge

`commit <id>` writes to Apple Reminders via `osascript` — only works when running on a Mac. Two options:

1. **Defer to V2.** Telegram-only V0/V1; commit lives on roadmap.
2. **Mac-side companion process.** A small launchd job on your Mac polls Turso for `pending_commits` rows and writes to Reminders. Out of V0 scope but architecturally clean.

## 9. V0 scope (smallest viable loop)

1. SQLite schema + Telegram bot writing raw entries on every message
2. Lazy classifier — runs on unclassified rows when `/top3` is invoked
3. `/top3` and `/log` commands inside Telegram
4. Structured trace table for every LLM call
5. Prompts as files in `src/solo/prompts/`
6. Eval harness for the classifier (`evals/classify.jsonl` + `scripts/eval.py`)

Nothing else. No `expand`, `review`, or `commit`. If `/top3` isn't trustworthy after a week, the rest doesn't matter.

## 10. File structure

```
solo/
  pyproject.toml
  README.md
  src/solo/
    __init__.py
    bot.py              # Telegram long-polling loop, command dispatch
    db.py               # SQLite/libSQL schema + queries
    llm.py              # LLMClient (OpenRouter)
    classify.py         # Classification + summarization (single-shot)
    rank.py             # top3 ranking logic
    commands.py         # /top3, /log handlers
    trace.py            # llm_calls trace table writes
    prompts/
      classify.md
      score.md
    agents/             # V1
      expand.py
      review.py
  evals/
    classify.jsonl
  scripts/
    eval.py
  data/
    solo.db          # mounted volume in prod (V0); replaced by Turso later
  railway.json
```

## 11. Open questions to revisit after V0

- Embedding choice for dedup (Voyage API vs local model)
- When to migrate SQLite → Turso (trigger: first request for a non-Telegram surface)
- Whether `expand` should run in Telegram or a richer surface (CLI, web view) — likely Telegram is enough
- Mac bridge for Reminders (V2)
