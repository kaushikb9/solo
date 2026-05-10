# Observability via a trace table

## What problem this solves

LLM calls are expensive, slow, non-deterministic, and easy to silently regress. If you don't record what was sent and what came back, debugging a "why did this answer get worse?" question turns into archaeology. Logs in a file scroll away; ad-hoc prints disappear. You need a queryable record of every LLM call your system has ever made, in one place, in a format you can `SELECT … WHERE` against.

## The core idea

Write **one row per LLM call** to a structured table — call it `llm_calls`. The row captures four things:

1. **What you sent** — model, full message list, optional `prompt_name` tag.
2. **What came back** — full response text, token counts.
3. **What it cost you** — input tokens × input price + output tokens × output price.
4. **How it went** — `status` (`ok`/`error`), latency, error message if any.

That's it. No fancy tracer libraries, no spans, no OpenTelemetry — just rows. Because you control the schema, you can ask questions like:

- "What did the classifier think about entry 47 last Tuesday?" — `SELECT * FROM llm_calls WHERE prompt_name = 'classifier' AND ts < ...`
- "How much have I spent this week?" — `SELECT SUM(cost_usd) FROM llm_calls WHERE ts >= ...`
- "Which prompt has the worst tail latency?" — `SELECT prompt_name, MAX(latency_ms) FROM llm_calls GROUP BY prompt_name`
- "Am I getting more errors this month?" — `SELECT date(ts), COUNT(*) FROM llm_calls WHERE status = 'error' GROUP BY date(ts)`

Each one is a one-line SQL query. No dashboard required.

## How solo uses it

- `solo.trace.ensure_schema(conn)` (`src/solo/trace.py`) creates the `llm_calls` table at startup.
- `solo.trace.record_call(conn, ...)` writes one row.
- `solo.llm.LLMClient` calls `record_call` after every API hit — success or error. The whole API call is wrapped in `try/except`; the failure path still writes a row with `status='error'`, capturing why and how long before failure.
- Bypassing `LLMClient` (e.g., importing `openai` directly) loses the trace row. That's why `AGENTS.md` says: every LLM call goes through `LLMClient`. No exceptions.

## Common gotchas

- **Pre-call vs post-call write.** Solo writes the row *after* the call completes. Simpler (one INSERT per call). Trade-off: if the process crashes mid-call, no row exists. Acceptable when calls are short. If your calls are long-running (seconds) or your process dies often, switch to a pre-call INSERT (`status='pending'`) plus a post-call UPDATE.
- **Storing full prompts gets big.** A row with a 10KB prompt and 5KB response is 15KB. At 1000 calls/day, that's ~15MB/day. SQLite handles this fine for personal scale; if you ever reach millions of calls, partition by month or hash the prompt and store separately.
- **Cost is computed, not returned.** Providers don't usually return per-call USD cost. You maintain a `MODEL_PRICING` dict and multiply tokens × rate yourself. When prices change, you update the dict — old rows still reflect the cost-at-time-of-call (unless you re-derive).
- **Tracing your own code is half the value.** Tagging each call with a `prompt_name` lets you answer "all calls from the classifier" in SQL, which compounds as you add more callers (ranker, expand, review).

## Further reading

- "Run-as-row" pattern, used in OpenClaw and Hermes for similar reasons (see `docs/architecture.md` §3 for context on why solo borrows the *pattern* without the *runtime*).
- SQLite docs on `CHECK` constraints — used here to enforce `status IN ('ok', 'error')`.
