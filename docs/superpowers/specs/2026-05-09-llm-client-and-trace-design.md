# LLMClient + `llm_calls` Trace Table — Design Spec

**Date:** 2026-05-09
**Slice:** V0 slice 2 (per `docs/status.md` and `AGENTS.md` V0 scope)
**Status:** proposed (awaiting user approval)

---

## Goal

Provide the single, observable entry point for every LLM call in solo. After this slice, any caller in the codebase reaches an LLM through `solo.llm.LLMClient`, and every call automatically writes one row to the `llm_calls` SQLite trace table. No classifier, no commands, no eval harness in this slice — just the spine.

This slice is the foundation the next three slices (lazy classifier, `/top3` + `/log`, eval harness) all depend on.

---

## Non-goals (explicit out of scope)

- The classifier itself.
- Retry / backoff logic.
- Streaming responses.
- Prompt caching.
- The eval harness.
- A real prompt file (the `src/solo/prompts/` directory is created empty; the first prompt file lands in slice 3).
- A live Telegram code path that calls the LLM (slice 3 wires `/top3`).

If a request smells like one of the above, push back to a later slice.

---

## Architecture

Three small modules, each with one responsibility:

| Module | Responsibility |
|---|---|
| `src/solo/llm.py` | `LLMClient` async class — owns the OpenAI SDK call, token/cost accounting, calls into `trace.record_call`. |
| `src/solo/prompts.py` | `load(name)` and `render(name, **vars)` — read prompt `.md` files, do `str.format` substitution. |
| `src/solo/trace.py` | `record_call(...)` — writes one row to `llm_calls`. Owns the schema migration for that table. |
| `src/solo/prompts/` | Directory of prompt `.md` files. Empty in this slice; populated in slice 3. |

**Why the split** (overrides default YAGNI consolidation): explicit module boundaries are pedagogically valuable in a learning project, and the eval harness in slice 5 will load prompts directly without going through `LLMClient`. Drawing the line now avoids a later move.

The schema-creation function for `llm_calls` lives in `trace.py` (not `db.py`) because the table belongs to the trace module's domain. `db.py` continues to own the `entries` table only. Both schema-creation functions are idempotent (`CREATE TABLE IF NOT EXISTS`) and can be called in any order at startup.

---

## `LLMClient` interface

```python
class LLMClient:
    def __init__(
        self,
        api_key: str,
        db_path: Path,
    ): ...

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str,                       # required — caller decides which model
        prompt_name: str | None = None,
    ) -> str:
        """Raw chat call. Returns assistant text. Writes one trace row."""

    async def structured(
        self,
        prompt_name: str,
        schema: type[BaseModel],
        *,
        model: str,                       # required
        vars: dict | None = None,
    ) -> BaseModel:
        """Render prompt template, call API with response_format=schema, parse, return."""
```

- Async-only. Matches `python-telegram-bot` (which is async-only as of v20).
- Uses `openai.AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=...)`.
- `structured()` uses the OpenAI SDK's pydantic helper: `client.beta.chat.completions.parse(..., response_format=schema)` — returns a parsed pydantic instance directly.
- **No client-side default model.** Each caller is explicit about which model it wants. The classifier reads `SOLO_CLASSIFY_MODEL` from env and passes it; the expand path (V1) will read `SOLO_EXPAND_MODEL` and pass it. This keeps `LLMClient` purpose-agnostic and matches the existing per-purpose env-var setup in `.env.example`.
- `prompt_name` on `chat()` is metadata-only — used to tag the trace row. `chat()` does not load any file. `structured()` requires `prompt_name` and uses it for both loading and tagging.
- `vars` on `structured()` is passed through to `prompts.render` as `**(vars or {})`. `None` is equivalent to `{}`.
- **Error semantics:** on API failure both methods write the trace row (`status='error'`) and then re-raise the underlying exception. They never return a sentinel value or swallow errors. Capture is the only path in solo that swallows errors; LLM calls fail loud so callers (classifier, ranker) can decide what to do.
- **Timing:** `LLMClient` is responsible for generating `ts` (UTC ISO 8601 at call start) and `latency_ms` (monotonic clock around the API call). `trace.record_call` does not generate timestamps.

---

## `prompts.py` interface

```python
PROMPTS_DIR = Path(__file__).parent / "prompts"

def load(name: str) -> str:
    """Read src/solo/prompts/<name>.md and return its contents."""

def render(name: str, **vars: object) -> str:
    """load(name) then str.format(**vars). KeyError propagates."""
```

- Single-pass `str.format` templating. No Jinja, no escaping, no partial templates.
- Missing variable in template → uncaught `KeyError`. Fail loud — silently swallowing template errors is how prompts rot.
- `load("classifier")` → reads `src/solo/prompts/classifier.md`. The `.md` extension is added by the loader; callers pass the bare name.
- File-not-found → `FileNotFoundError` propagates. No fallback.

---

## `trace.py` interface

```python
def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create llm_calls table + index if not exists. Idempotent."""

def record_call(
    conn: sqlite3.Connection,
    *,
    ts: str,
    model: str,
    prompt_name: str | None,
    prompt_text: str,           # json-encoded messages
    response_text: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float | None,
    latency_ms: int,
    status: str,                # "ok" | "error"
    error: str | None,
) -> int:
    """Insert one row. Returns row id."""
```

- Pure functions, no class, no global state. Take a `sqlite3.Connection` — matches `db.py`'s `insert_entry(conn, ...)` pattern.
- `db.get_connection(db_path)` creates schema for `entries`; `trace.ensure_schema(conn)` is called separately at startup to add the `llm_calls` table to the same DB. (Alternative — fold `ensure_schema` into `get_connection` — rejected to keep `db.py` decoupled from the trace module.)
- Caller (`LLMClient`) is responsible for assembling the row and managing the connection (opens one per call via `db.get_connection`); `trace.py` just persists it.

---

## `llm_calls` table schema

```sql
CREATE TABLE IF NOT EXISTS llm_calls (
  id            INTEGER PRIMARY KEY,
  ts            TEXT    NOT NULL,    -- ISO 8601 UTC
  model         TEXT    NOT NULL,
  prompt_name   TEXT,                -- NULL for raw chat calls
  prompt_text   TEXT    NOT NULL,    -- json-encoded messages array
  response_text TEXT,                -- NULL on error
  input_tokens  INTEGER,
  output_tokens INTEGER,
  cost_usd      REAL,                -- NULL if model not in pricing table
  latency_ms    INTEGER NOT NULL,
  status        TEXT    NOT NULL CHECK (status IN ('ok', 'error')),
  error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
```

### Write semantics

**One row per call, written *after* the call completes (success or failure).** The whole API call is wrapped in `try/except`; on success the row gets `status='ok'` and the response fields populated; on failure the row gets `status='error'`, `error=str(exc)`, response fields `NULL`, but `latency_ms` is still computed (time to failure).

No mid-call rows for V0. If a process crashes mid-call, the row is lost — acceptable trade-off because (a) calls are short, (b) the OpenRouter side has its own logs, (c) one INSERT per call keeps the code shape honest.

---

## Cost calculation

```python
# in llm.py — values verified at openrouter.ai/models when wiring; update on drift.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1m_tokens_usd, output_per_1m_tokens_usd)
    "minimax/minimax-m2.7":     (0.30, 1.20),
    "moonshotai/kimi-k2.5":     (0.44, 2.00),
    "moonshotai/kimi-k2.6":     (0.74, 3.49),
}

def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return None
    in_price, out_price = pricing
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price
```

- Unknown model → `cost_usd = NULL`. No crash, no warning. The trace row still lands; cost is recoverable later by joining against an updated pricing table.
- The pricing values are seed values; verify the actual rates on OpenRouter when wiring the classifier in slice 3 and update the dict.

---

## Configuration

| Env var | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | Loaded via `os.environ`. `LLMClient.__init__` raises if `api_key=""`. |
| `SOLO_CLASSIFY_MODEL` | yes (read by future classifier, not by `LLMClient` itself) | Default `minimax/minimax-m2.7` per `.env.example`. The slice 3 classifier will read this and pass it to `LLMClient.structured(model=...)`. |
| `SOLO_EXPAND_MODEL` | not in V0 | Documented for forward-compat. Used by V1 `expand`. |
| `SOLO_DB_PATH` | yes (already in use) | Same DB as `entries`. |

`LLMClient` itself reads only `OPENROUTER_API_KEY` (passed in via `__init__`). Model env vars belong to the callers.

`.env` continues to be loaded by `python-dotenv` at process start (already wired in slice 1).

---

## Testing strategy

Three test files:

| File | Coverage |
|---|---|
| `tests/test_llm.py` | `LLMClient.chat` and `.structured` with **mocked `AsyncOpenAI`**. Asserts: messages sent, model used, trace row written with correct fields, pydantic parsing on `structured`, error path writes `status='error'` row. |
| `tests/test_prompts.py` | `load` reads correct file, `render` substitutes vars, missing var raises `KeyError`, missing file raises `FileNotFoundError`. Uses `tmp_path` and monkeypatches `PROMPTS_DIR`. |
| `tests/test_trace.py` | `ensure_schema` is idempotent, `record_call` writes a row and returns its id, `cost_usd=NULL` is allowed, status check constraint rejects bad values. |

**Live integration test**: `tests/test_llm_live.py`, decorated `@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), ...)`. Hits `minimax/minimax-m2.7` (cheapest seeded model) with a one-token prompt, asserts a real row lands with `status='ok'`, non-null `input_tokens`/`output_tokens`, and `cost_usd > 0`. Skipped in CI by default; run manually when wiring.

**Total target:** ~20 new tests. Existing 14 stay green.

---

## What lands at end of slice

- `src/solo/llm.py`, `src/solo/prompts.py`, `src/solo/trace.py`, empty `src/solo/prompts/` directory
- `tests/test_llm.py`, `tests/test_prompts.py`, `tests/test_trace.py`, `tests/test_llm_live.py`
- `llm_calls` table created on startup (call `trace.ensure_schema` from `__main__.py`)
- `MODEL_PRICING` seeded with the three OpenRouter models in `.env.example` (Minimax M2.7, Kimi K2.5, K2.6)
- `OPENROUTER_API_KEY`, `SOLO_CLASSIFY_MODEL`, `SOLO_EXPAND_MODEL` documented in `README.md` (already present in `.env.example`)
- `docs/concepts/llm-api-basics.md` written (per the documentation ritual in `AGENTS.md`)
- `docs/concepts/observability-trace-table.md` written
- `docs/decisions/0001-trace-table-write-timing.md` ADR (single post-call write decision)
- `docs/decisions/0002-llm-module-split.md` ADR (the three-module split decision)
- `docs/status.md` updated

---

## Open decisions deferred to implementation

- Verify the three Minimax/Kimi pricing rows against openrouter.ai/models at wiring time — `.env.example` comments are the current source of truth.
- Whether `MODEL_PRICING` lives in `llm.py` or its own `pricing.py` — defer until pricing logic gets non-trivial (e.g., per-region rates, prompt caching discounts). Three rows in one dict is fine.

---

## Risks

- **OpenRouter SDK behavior on `response_format` with pydantic.** OpenAI's `.beta.chat.completions.parse()` works against OpenAI directly; OpenRouter routes to many providers and `response_format=BaseModel` may or may not be supported per-provider. Mitigation: live integration test will catch this immediately. Fallback if it fails: drop to JSON mode + manual `pydantic.TypeAdapter` parse.
- **Async + sqlite3.** `sqlite3` is sync; calling it from an async function blocks the event loop briefly. Acceptable at solo's scale (one user, one bot). If it ever matters, swap to `aiosqlite`.
