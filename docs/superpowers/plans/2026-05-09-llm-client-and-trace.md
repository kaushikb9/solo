# LLMClient + `llm_calls` Trace Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the single observable entry point for every LLM call in solo. After this slice, any caller reaches an LLM through `solo.llm.LLMClient`, and every call writes one row to the SQLite `llm_calls` trace table.

**Architecture:** Three modules — `trace.py` (table + record_call), `prompts.py` (load/render `.md` files), `llm.py` (`LLMClient` async class wrapping `AsyncOpenAI` pointed at OpenRouter). Caller passes the model per call (`SOLO_CLASSIFY_MODEL` / `SOLO_EXPAND_MODEL` env vars are read by callers, not by `LLMClient` itself). One trace row per call, written after completion (success or failure).

**Tech Stack:** Python 3.12, `openai>=1.0` (`AsyncOpenAI`), `pydantic>=2.0`, `sqlite3` stdlib, `pytest` + `pytest-asyncio`, `uv` for everything.

**Spec:** `docs/superpowers/specs/2026-05-09-llm-client-and-trace-design.md` — read this first.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/solo/trace.py` | `ensure_schema(conn)` creates `llm_calls` table + index; `record_call(conn, ...)` writes one row. |
| `src/solo/prompts.py` | `load(name)` reads `src/solo/prompts/<name>.md`; `render(name, **vars)` does `str.format` substitution. |
| `src/solo/llm.py` | `MODEL_PRICING` dict + `compute_cost()` helper + `LLMClient` async class with `chat()` and `structured()`. |
| `src/solo/prompts/` | Empty directory in this slice (touch `.gitkeep`). Real prompt files land in slice 3. |
| `src/solo/bot.py` | Modified to call `trace.ensure_schema(conn)` after `get_connection`. |
| `tests/test_trace.py` | Schema, record_call success row, status-check constraint, NULL cost allowed. |
| `tests/test_prompts.py` | `load` reads file, `render` substitutes vars, missing var raises, missing file raises. |
| `tests/test_llm.py` | `LLMClient.chat` and `.structured` with mocked `AsyncOpenAI` — success + error paths, trace row assertions. |
| `tests/test_llm_live.py` | Single skipif-gated live integration test against `minimax/minimax-m2.7`. |
| `README.md` | Add env-var section listing `OPENROUTER_API_KEY`, `SOLO_CLASSIFY_MODEL`. |
| `docs/concepts/llm-api-basics.md` | Concept primer (300–500 words). |
| `docs/concepts/observability-trace-table.md` | Concept primer (300–500 words). |
| `docs/decisions/0001-trace-write-timing.md` | ADR for single post-call write decision. |
| `docs/decisions/0002-llm-module-split.md` | ADR for the three-module split. |
| `docs/status.md` | Update to reflect slice 2 done, slice 3 next. |

---

### Task 1: `trace.ensure_schema` — failing test then minimal impl

**Files:**
- Create: `tests/test_trace.py`
- Create: `src/solo/trace.py`

- [ ] **Step 1: Write the failing schema tests**

Create `tests/test_trace.py`:

```python
import sqlite3

import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


class TestSchema:
    def test_llm_calls_table_exists(self, conn):
        from solo.trace import ensure_schema

        ensure_schema(conn)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_calls'"
        )
        assert cursor.fetchone() is not None

    def test_llm_calls_columns(self, conn):
        from solo.trace import ensure_schema

        ensure_schema(conn)
        cursor = conn.execute("PRAGMA table_info(llm_calls)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {
            "id",
            "ts",
            "model",
            "prompt_name",
            "prompt_text",
            "response_text",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "latency_ms",
            "status",
            "error",
        }

    def test_ensure_schema_is_idempotent(self, conn):
        from solo.trace import ensure_schema

        ensure_schema(conn)
        ensure_schema(conn)  # second call must not raise

    def test_index_on_ts_exists(self, conn):
        from solo.trace import ensure_schema

        ensure_schema(conn)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_llm_calls_ts'"
        )
        assert cursor.fetchone() is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solo.trace'`

- [ ] **Step 3: Implement `trace.ensure_schema`**

Create `src/solo/trace.py`:

```python
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_name TEXT,
    prompt_text TEXT NOT NULL,
    response_text TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    latency_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trace.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/trace.py tests/test_trace.py
git commit -m "feat(trace): add llm_calls schema and ensure_schema()"
```

---

### Task 2: `trace.record_call` — failing test then impl

**Files:**
- Modify: `tests/test_trace.py` (append)
- Modify: `src/solo/trace.py`

- [ ] **Step 1: Append failing tests for `record_call`**

Append to `tests/test_trace.py`:

```python
class TestRecordCall:
    def test_returns_row_id(self, conn):
        from solo.trace import ensure_schema, record_call

        ensure_schema(conn)
        row_id = record_call(
            conn,
            ts="2026-05-09T12:00:00Z",
            model="minimax/minimax-m2.7",
            prompt_name="classifier",
            prompt_text='[{"role":"user","content":"hi"}]',
            response_text="hello",
            input_tokens=5,
            output_tokens=2,
            cost_usd=0.0001,
            latency_ms=345,
            status="ok",
            error=None,
        )
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_inserted_row_is_readable(self, conn):
        from solo.trace import ensure_schema, record_call

        ensure_schema(conn)
        row_id = record_call(
            conn,
            ts="2026-05-09T12:00:00Z",
            model="minimax/minimax-m2.7",
            prompt_name="classifier",
            prompt_text='[{"role":"user","content":"hi"}]',
            response_text="hello",
            input_tokens=5,
            output_tokens=2,
            cost_usd=0.0001,
            latency_ms=345,
            status="ok",
            error=None,
        )
        row = conn.execute("SELECT * FROM llm_calls WHERE id = ?", (row_id,)).fetchone()
        assert row["model"] == "minimax/minimax-m2.7"
        assert row["status"] == "ok"
        assert row["response_text"] == "hello"
        assert row["error"] is None

    def test_error_row_has_null_response(self, conn):
        from solo.trace import ensure_schema, record_call

        ensure_schema(conn)
        record_call(
            conn,
            ts="2026-05-09T12:00:00Z",
            model="minimax/minimax-m2.7",
            prompt_name=None,
            prompt_text="[]",
            response_text=None,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            latency_ms=120,
            status="error",
            error="connection refused",
        )
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        assert row["status"] == "error"
        assert row["response_text"] is None
        assert row["cost_usd"] is None
        assert row["error"] == "connection refused"

    def test_invalid_status_rejected(self, conn):
        from solo.trace import ensure_schema, record_call

        ensure_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            record_call(
                conn,
                ts="2026-05-09T12:00:00Z",
                model="x",
                prompt_name=None,
                prompt_text="[]",
                response_text=None,
                input_tokens=None,
                output_tokens=None,
                cost_usd=None,
                latency_ms=1,
                status="weird",  # violates CHECK constraint
                error=None,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trace.py::TestRecordCall -v`
Expected: FAIL — `ImportError: cannot import name 'record_call'`

- [ ] **Step 3: Implement `record_call`**

Append to `src/solo/trace.py`:

```python
def record_call(
    conn: sqlite3.Connection,
    *,
    ts: str,
    model: str,
    prompt_name: str | None,
    prompt_text: str,
    response_text: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float | None,
    latency_ms: int,
    status: str,
    error: str | None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO llm_calls (
            ts, model, prompt_name, prompt_text, response_text,
            input_tokens, output_tokens, cost_usd, latency_ms, status, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts, model, prompt_name, prompt_text, response_text,
            input_tokens, output_tokens, cost_usd, latency_ms, status, error,
        ),
    )
    conn.commit()
    return cursor.lastrowid
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trace.py -v`
Expected: 8 passed (4 schema + 4 record_call).

- [ ] **Step 5: Commit**

```bash
git add src/solo/trace.py tests/test_trace.py
git commit -m "feat(trace): add record_call() to write llm_calls rows"
```

---

### Task 3: `prompts.load` and `prompts.render`

**Files:**
- Create: `tests/test_prompts.py`
- Create: `src/solo/prompts.py`
- Create: `src/solo/prompts/.gitkeep`

- [ ] **Step 1: Write failing tests**

Create `tests/test_prompts.py`:

```python
import pytest


@pytest.fixture
def fake_prompts_dir(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "classifier.md").write_text("Classify: {entry}")
    (prompts / "noargs.md").write_text("Just text, no vars")
    monkeypatch.setattr("solo.prompts.PROMPTS_DIR", prompts)
    return prompts


class TestLoad:
    def test_load_returns_file_contents(self, fake_prompts_dir):
        from solo.prompts import load

        assert load("classifier") == "Classify: {entry}"

    def test_load_missing_file_raises(self, fake_prompts_dir):
        from solo.prompts import load

        with pytest.raises(FileNotFoundError):
            load("nonexistent")


class TestRender:
    def test_render_substitutes_vars(self, fake_prompts_dir):
        from solo.prompts import render

        assert render("classifier", entry="learn rust") == "Classify: learn rust"

    def test_render_with_no_vars_works(self, fake_prompts_dir):
        from solo.prompts import render

        assert render("noargs") == "Just text, no vars"

    def test_render_missing_var_raises(self, fake_prompts_dir):
        from solo.prompts import render

        with pytest.raises(KeyError):
            render("classifier")  # template needs {entry}, none passed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solo.prompts'`

- [ ] **Step 3: Implement `prompts.py`**

Create `src/solo/prompts.py`:

```python
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text()


def render(name: str, **vars: object) -> str:
    return load(name).format(**vars)
```

Create `src/solo/prompts/.gitkeep` (empty file) to keep the directory in git:

```bash
mkdir -p src/solo/prompts && touch src/solo/prompts/.gitkeep
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/prompts.py src/solo/prompts/.gitkeep tests/test_prompts.py
git commit -m "feat(prompts): add load() and render() helpers"
```

---

### Task 4: `compute_cost` helper in `llm.py`

**Files:**
- Create: `tests/test_llm.py`
- Create: `src/solo/llm.py`

- [ ] **Step 1: Write failing test for cost calculation**

Create `tests/test_llm.py`:

```python
import pytest


class TestComputeCost:
    def test_known_model_returns_cost(self):
        from solo.llm import compute_cost

        # minimax/minimax-m2.7: $0.30 / $1.20 per M tokens
        # 1000 input + 500 output = 0.0003 + 0.0006 = 0.0009
        cost = compute_cost("minimax/minimax-m2.7", 1000, 500)
        assert cost == pytest.approx(0.0009)

    def test_unknown_model_returns_none(self):
        from solo.llm import compute_cost

        assert compute_cost("does/not-exist", 1000, 500) is None

    def test_zero_tokens_zero_cost(self):
        from solo.llm import compute_cost

        assert compute_cost("minimax/minimax-m2.7", 0, 0) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm.py::TestComputeCost -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solo.llm'`

- [ ] **Step 3: Implement `llm.py` skeleton with `compute_cost`**

Create `src/solo/llm.py`:

```python
"""LLMClient — single observable entry point for every LLM call in solo.

All LLM calls go through this module. Every call writes one row to the
llm_calls trace table.
"""

# Verified at openrouter.ai/models — update on drift.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1m_tokens_usd, output_per_1m_tokens_usd)
    "minimax/minimax-m2.7":  (0.30, 1.20),
    "moonshotai/kimi-k2.5":  (0.44, 2.00),
    "moonshotai/kimi-k2.6":  (0.74, 3.49),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return None
    in_price, out_price = pricing
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm.py::TestComputeCost -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/llm.py tests/test_llm.py
git commit -m "feat(llm): add MODEL_PRICING and compute_cost() helper"
```

---

### Task 5: `LLMClient.chat` — success path

**Files:**
- Modify: `tests/test_llm.py` (append)
- Modify: `src/solo/llm.py`

- [ ] **Step 1: Append failing tests for `chat` success path**

Append to `tests/test_llm.py`:

```python
import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    conn = sqlite3.connect(str(path))
    from solo.trace import ensure_schema

    ensure_schema(conn)
    conn.close()
    return path


def _mock_chat_response(content: str, input_tokens: int = 5, output_tokens: int = 2):
    """Build a mock object shaped like openai's ChatCompletion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage.prompt_tokens = input_tokens
    response.usage.completion_tokens = output_tokens
    return response


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_returns_assistant_text(self, db_path, monkeypatch):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_create = AsyncMock(return_value=_mock_chat_response("hello back"))
        monkeypatch.setattr(client._client.chat.completions, "create", mock_create)

        result = await client.chat(
            [{"role": "user", "content": "hi"}],
            model="minimax/minimax-m2.7",
        )
        assert result == "hello back"

    @pytest.mark.asyncio
    async def test_chat_writes_trace_row(self, db_path, monkeypatch):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_create = AsyncMock(return_value=_mock_chat_response("hello back", 10, 4))
        monkeypatch.setattr(client._client.chat.completions, "create", mock_create)

        await client.chat(
            [{"role": "user", "content": "hi"}],
            model="minimax/minimax-m2.7",
            prompt_name="ad-hoc",
        )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        conn.close()

        assert row["model"] == "minimax/minimax-m2.7"
        assert row["prompt_name"] == "ad-hoc"
        assert row["status"] == "ok"
        assert row["response_text"] == "hello back"
        assert row["input_tokens"] == 10
        assert row["output_tokens"] == 4
        assert row["cost_usd"] == pytest.approx(10 / 1_000_000 * 0.30 + 4 / 1_000_000 * 1.20)
        assert row["latency_ms"] >= 0
        assert json.loads(row["prompt_text"]) == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_chat_passes_correct_messages_to_sdk(self, db_path, monkeypatch):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_create = AsyncMock(return_value=_mock_chat_response("ok"))
        monkeypatch.setattr(client._client.chat.completions, "create", mock_create)

        msgs = [{"role": "user", "content": "hello"}]
        await client.chat(msgs, model="minimax/minimax-m2.7")

        mock_create.assert_awaited_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["messages"] == msgs
        assert kwargs["model"] == "minimax/minimax-m2.7"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm.py::TestChat -v`
Expected: FAIL — `ImportError: cannot import name 'LLMClient'`

- [ ] **Step 3: Implement `LLMClient.chat`**

Append to `src/solo/llm.py`:

```python
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import BaseModel

from solo import trace
from solo.db import get_connection


class LLMClient:
    def __init__(self, api_key: str, db_path: Path):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        self._db_path = Path(db_path)
        self._client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        prompt_name: str | None = None,
    ) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        prompt_text = json.dumps(messages)
        start = time.monotonic()

        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
            )
        except Exception as exc:
            self._write_trace(
                ts=ts,
                model=model,
                prompt_name=prompt_name,
                prompt_text=prompt_text,
                response_text=None,
                input_tokens=None,
                output_tokens=None,
                cost_usd=None,
                latency_ms=int((time.monotonic() - start) * 1000),
                status="error",
                error=str(exc),
            )
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content or ""
        in_tok = response.usage.prompt_tokens
        out_tok = response.usage.completion_tokens

        self._write_trace(
            ts=ts,
            model=model,
            prompt_name=prompt_name,
            prompt_text=prompt_text,
            response_text=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=compute_cost(model, in_tok, out_tok),
            latency_ms=latency_ms,
            status="ok",
            error=None,
        )
        return content

    def _write_trace(self, **row) -> None:
        conn = get_connection(str(self._db_path))
        try:
            trace.record_call(conn, **row)
        finally:
            conn.close()
```

Note: `db.get_connection` runs the `entries` schema. We rely on `trace.ensure_schema` having been called separately (the bot startup wires this in Task 9). For tests, the `db_path` fixture pre-creates the schema.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm.py -v`
Expected: 6 passed (3 cost + 3 chat).

- [ ] **Step 5: Commit**

```bash
git add src/solo/llm.py tests/test_llm.py
git commit -m "feat(llm): add LLMClient.chat() with trace row writes"
```

---

### Task 6: `LLMClient.chat` — error path writes trace row

**Files:**
- Modify: `tests/test_llm.py` (append)

- [ ] **Step 1: Append failing test for the error path**

Append to `tests/test_llm.py`:

```python
class TestChatErrors:
    @pytest.mark.asyncio
    async def test_chat_writes_error_row_and_reraises(self, db_path, monkeypatch):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_create = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(client._client.chat.completions, "create", mock_create)

        with pytest.raises(RuntimeError, match="boom"):
            await client.chat(
                [{"role": "user", "content": "hi"}],
                model="minimax/minimax-m2.7",
            )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        conn.close()

        assert row["status"] == "error"
        assert row["error"] == "boom"
        assert row["response_text"] is None
        assert row["cost_usd"] is None
        assert row["input_tokens"] is None
        assert row["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_init_rejects_empty_api_key(self, db_path):
        from solo.llm import LLMClient

        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            LLMClient(api_key="", db_path=db_path)
```

- [ ] **Step 2: Run tests to verify they pass without code changes**

The error path was already implemented in Task 5. Run:

`uv run pytest tests/test_llm.py::TestChatErrors -v`
Expected: 2 passed.

If they fail, fix `LLMClient.chat`'s `try/except` block until they pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_llm.py
git commit -m "test(llm): assert chat() writes error row and reraises"
```

---

### Task 7: `LLMClient.structured` — success path

**Files:**
- Modify: `tests/test_llm.py` (append)
- Modify: `src/solo/llm.py`

- [ ] **Step 1: Append failing tests for `structured`**

Append to `tests/test_llm.py`:

```python
from pydantic import BaseModel


class _ClassifyResult(BaseModel):
    category: str
    urgency: int


def _mock_parse_response(parsed_obj, input_tokens: int = 8, output_tokens: int = 5):
    """Build a mock shaped like client.beta.chat.completions.parse() response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed_obj
    response.choices[0].message.content = parsed_obj.model_dump_json()
    response.usage.prompt_tokens = input_tokens
    response.usage.completion_tokens = output_tokens
    return response


class TestStructured:
    @pytest.fixture
    def fake_prompts_dir(self, tmp_path, monkeypatch):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "classifier.md").write_text("Classify: {entry}")
        monkeypatch.setattr("solo.prompts.PROMPTS_DIR", prompts)
        return prompts

    @pytest.mark.asyncio
    async def test_structured_returns_parsed_pydantic(
        self, db_path, fake_prompts_dir, monkeypatch
    ):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        expected = _ClassifyResult(category="learning", urgency=2)
        mock_parse = AsyncMock(return_value=_mock_parse_response(expected))
        monkeypatch.setattr(client._client.beta.chat.completions, "parse", mock_parse)

        result = await client.structured(
            "classifier",
            schema=_ClassifyResult,
            model="minimax/minimax-m2.7",
            vars={"entry": "learn rust"},
        )
        assert result == expected

    @pytest.mark.asyncio
    async def test_structured_writes_trace_row_with_prompt_name(
        self, db_path, fake_prompts_dir, monkeypatch
    ):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        expected = _ClassifyResult(category="x", urgency=1)
        mock_parse = AsyncMock(return_value=_mock_parse_response(expected))
        monkeypatch.setattr(client._client.beta.chat.completions, "parse", mock_parse)

        await client.structured(
            "classifier",
            schema=_ClassifyResult,
            model="minimax/minimax-m2.7",
            vars={"entry": "learn rust"},
        )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        conn.close()

        assert row["prompt_name"] == "classifier"
        assert row["status"] == "ok"
        # prompt_text contains the rendered template wrapped in messages array
        msgs = json.loads(row["prompt_text"])
        assert any("learn rust" in m["content"] for m in msgs)

    @pytest.mark.asyncio
    async def test_structured_passes_response_format_to_sdk(
        self, db_path, fake_prompts_dir, monkeypatch
    ):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        expected = _ClassifyResult(category="x", urgency=1)
        mock_parse = AsyncMock(return_value=_mock_parse_response(expected))
        monkeypatch.setattr(client._client.beta.chat.completions, "parse", mock_parse)

        await client.structured(
            "classifier",
            schema=_ClassifyResult,
            model="minimax/minimax-m2.7",
            vars={"entry": "x"},
        )
        kwargs = mock_parse.call_args.kwargs
        assert kwargs["response_format"] is _ClassifyResult
        assert kwargs["model"] == "minimax/minimax-m2.7"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm.py::TestStructured -v`
Expected: FAIL — `AttributeError` or `AttributeError: 'LLMClient' object has no attribute 'structured'`

- [ ] **Step 3: Implement `LLMClient.structured`**

Append to `LLMClient` in `src/solo/llm.py`:

```python
    async def structured(
        self,
        prompt_name: str,
        schema: type[BaseModel],
        *,
        model: str,
        vars: dict | None = None,
    ) -> BaseModel:
        from solo import prompts

        rendered = prompts.render(prompt_name, **(vars or {}))
        messages = [{"role": "user", "content": rendered}]
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        prompt_text = json.dumps(messages)
        start = time.monotonic()

        try:
            response = await self._client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=schema,
            )
        except Exception as exc:
            self._write_trace(
                ts=ts,
                model=model,
                prompt_name=prompt_name,
                prompt_text=prompt_text,
                response_text=None,
                input_tokens=None,
                output_tokens=None,
                cost_usd=None,
                latency_ms=int((time.monotonic() - start) * 1000),
                status="error",
                error=str(exc),
            )
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        parsed = response.choices[0].message.parsed
        in_tok = response.usage.prompt_tokens
        out_tok = response.usage.completion_tokens

        self._write_trace(
            ts=ts,
            model=model,
            prompt_name=prompt_name,
            prompt_text=prompt_text,
            response_text=response.choices[0].message.content or "",
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=compute_cost(model, in_tok, out_tok),
            latency_ms=latency_ms,
            status="ok",
            error=None,
        )
        return parsed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/llm.py tests/test_llm.py
git commit -m "feat(llm): add LLMClient.structured() for pydantic-typed calls"
```

---

### Task 8: `LLMClient.structured` — error path

**Files:**
- Modify: `tests/test_llm.py` (append)

- [ ] **Step 1: Append error-path test**

Append to `tests/test_llm.py`:

```python
class TestStructuredErrors:
    @pytest.fixture
    def fake_prompts_dir(self, tmp_path, monkeypatch):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "classifier.md").write_text("Classify: {entry}")
        monkeypatch.setattr("solo.prompts.PROMPTS_DIR", prompts)
        return prompts

    @pytest.mark.asyncio
    async def test_structured_writes_error_row_and_reraises(
        self, db_path, fake_prompts_dir, monkeypatch
    ):
        from solo.llm import LLMClient

        client = LLMClient(api_key="test-key", db_path=db_path)
        mock_parse = AsyncMock(side_effect=RuntimeError("schema mismatch"))
        monkeypatch.setattr(client._client.beta.chat.completions, "parse", mock_parse)

        with pytest.raises(RuntimeError, match="schema mismatch"):
            await client.structured(
                "classifier",
                schema=_ClassifyResult,
                model="minimax/minimax-m2.7",
                vars={"entry": "x"},
            )

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        conn.close()
        assert row["status"] == "error"
        assert row["error"] == "schema mismatch"
        assert row["prompt_name"] == "classifier"
```

- [ ] **Step 2: Run test (should already pass — error path was implemented in Task 7)**

Run: `uv run pytest tests/test_llm.py::TestStructuredErrors -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_llm.py
git commit -m "test(llm): assert structured() writes error row and reraises"
```

---

### Task 9: Wire `trace.ensure_schema` into bot startup

**Files:**
- Modify: `src/solo/bot.py:48-69` (the `main()` function)

- [ ] **Step 1: Read current `main()` to confirm location**

Run: `uv run python -c "from solo.bot import main; print('ok')"`
Expected: `ok` (sanity check that bot module still imports).

- [ ] **Step 2: Modify `main()` to call `trace.ensure_schema`**

Edit `src/solo/bot.py`. Find the existing import line:

```python
from solo.db import get_connection, insert_entry
```

Add below it:

```python
from solo.trace import ensure_schema
```

Find this section in `main()`:

```python
    conn = get_connection(db_path)

    app = ApplicationBuilder().token(token).build()
```

Change to:

```python
    conn = get_connection(db_path)
    ensure_schema(conn)

    app = ApplicationBuilder().token(token).build()
```

- [ ] **Step 3: Verify bot still imports**

Run: `uv run python -c "from solo.bot import main; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Run all tests to confirm nothing broke**

Run: `uv run pytest -v`
Expected: all previous tests still passing (14 from slice 1 + 25 new from this slice = 39 passed).

- [ ] **Step 5: Commit**

```bash
git add src/solo/bot.py
git commit -m "feat(bot): ensure llm_calls table exists on startup"
```

---

### Task 10: Live integration test (skipif-gated)

**Files:**
- Create: `tests/test_llm_live.py`

- [ ] **Step 1: Write the live test**

Create `tests/test_llm_live.py`:

```python
"""Live integration test — hits a real OpenRouter model.

Skipped unless OPENROUTER_API_KEY is set in the environment.
Run manually with: OPENROUTER_API_KEY=... uv run pytest tests/test_llm_live.py -v
"""

import os
import sqlite3

import pytest

LIVE = os.getenv("OPENROUTER_API_KEY")
pytestmark = pytest.mark.skipif(not LIVE, reason="OPENROUTER_API_KEY not set")


@pytest.mark.asyncio
async def test_chat_against_real_openrouter(tmp_path):
    from solo.llm import LLMClient
    from solo.trace import ensure_schema

    db_path = tmp_path / "live.db"
    conn = sqlite3.connect(str(db_path))
    ensure_schema(conn)
    conn.close()

    client = LLMClient(api_key=LIVE, db_path=db_path)
    result = await client.chat(
        [{"role": "user", "content": "Reply with the single word: ok"}],
        model="minimax/minimax-m2.7",
    )

    assert isinstance(result, str)
    assert len(result) > 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM llm_calls").fetchone()
    conn.close()

    assert row["status"] == "ok"
    assert row["model"] == "minimax/minimax-m2.7"
    assert row["input_tokens"] is not None and row["input_tokens"] > 0
    assert row["output_tokens"] is not None and row["output_tokens"] > 0
    assert row["cost_usd"] is not None and row["cost_usd"] > 0
    assert row["latency_ms"] > 0
```

- [ ] **Step 2: Verify it skips by default**

Run: `uv run pytest tests/test_llm_live.py -v`
Expected: `1 skipped` (because `OPENROUTER_API_KEY` is not set in the shell).

- [ ] **Step 3: Manual smoke (optional but recommended before commit)**

If you have an OpenRouter key, run:

```bash
OPENROUTER_API_KEY=sk-or-... uv run pytest tests/test_llm_live.py -v
```

Expected: `1 passed`. If it fails on `response_format` or any provider quirk, that's the spec's flagged risk — drop to a JSON-mode fallback in `structured()` (out of scope here; capture as a follow-up).

- [ ] **Step 4: Commit**

```bash
git add tests/test_llm_live.py
git commit -m "test(llm): add skipif-gated live integration test against OpenRouter"
```

---

### Task 11: Document new env vars in `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add an Environment section**

Find this section in `README.md`:

```markdown
## Local dev

```bash
uv sync                              # install deps
cp .env.example .env                 # fill in secrets
uv run python -m solo.bot            # start bot (long polling)
uv run pytest                        # tests
uv run python scripts/eval.py        # classifier eval
```
```

Add a new section immediately below it:

```markdown
## Environment

Copy `.env.example` to `.env` and fill in:

| Var | Required | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | From @BotFather. |
| `SOLO_ALLOWED_CHATS` | yes | Comma-separated Telegram chat IDs allowed to talk to the bot. Get yours from @userinfobot. |
| `OPENROUTER_API_KEY` | yes (slice 2 onward) | From [openrouter.ai/keys](https://openrouter.ai/keys). One key, many models. |
| `SOLO_CLASSIFY_MODEL` | yes (slice 3 onward) | Model used by the lazy classifier. Default `minimax/minimax-m2.7`. |
| `SOLO_EXPAND_MODEL` | not in V0 | Model for V1 `expand`/`review`. Default `moonshotai/kimi-k2.6`. |
| `SOLO_DB_PATH` | yes | Path to the SQLite file. Default `./data/solo.db`. |

`OPENROUTER_API_KEY` is the only model-API credential — solo routes everything through OpenRouter.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): add Environment section listing all env vars"
```

---

### Task 12: Concept primer — `llm-api-basics.md`

**Files:**
- Create: `docs/concepts/llm-api-basics.md`

- [ ] **Step 1: Write the primer**

Create `docs/concepts/llm-api-basics.md`:

```markdown
# LLM API basics

## What problem this solves

You want a piece of software to ask a language model a question and use the answer. The LLM lives on someone else's servers (OpenAI, Anthropic, Google, OpenRouter). You need a way to send a structured request and get back a structured response — reliably, observably, and without hand-rolling HTTP for every call.

## The core idea

An LLM API call is a **stateless HTTP POST** with three things in the body:

1. **A model identifier** — e.g. `minimax/minimax-m2.7`. The provider routes your request to the right weights.
2. **A list of messages** — each tagged with a `role` (`system`, `user`, or `assistant`). The model reads the list top-to-bottom and predicts the next assistant message.
3. **Knobs** — temperature (randomness), max tokens (cap on output length), `response_format` (force JSON shape), tools (functions the model can call).

You get back: the assistant's reply, plus accounting metadata (`prompt_tokens`, `completion_tokens`, model used). You pay per token in and per token out, at different rates.

**Stateless** is the key word. The model does not remember previous calls. If you want a multi-turn conversation, you send the entire history every time. This is why prompts and conversations grow expensive — you re-pay for the same context on every turn.

## How solo uses it

- `solo.llm.LLMClient` (`src/solo/llm.py`) wraps `openai.AsyncOpenAI` pointed at OpenRouter's base URL. Every call routes through this one class.
- `LLMClient.chat(messages, model=...)` — raw multi-message call.
- `LLMClient.structured(prompt_name, schema, model=...)` — loads a `.md` prompt, sends it, parses the response into a pydantic class. This is what the classifier uses.
- We use **OpenRouter** as a single endpoint that proxies to many providers — one API key, many models. Lets us swap `minimax/minimax-m2.7` → `moonshotai/kimi-k2.6` by changing one env var.

## Common gotchas

- **Stateless means you re-pay for context.** A 10-turn chat with a 5KB system prompt sends that prompt 10 times. Prompt caching (a separate concept) is how you avoid this on long histories.
- **Model IDs change.** `gpt-5-mini` today might be deprecated next quarter. Pin in env vars, not in code.
- **Token counts are not character counts.** Roughly 4 characters per token in English; varies by tokenizer. Always read the actual `usage` field, never estimate.
- **Errors are silent in shape but loud in body.** A 200 response can still contain `{"error": ...}` in the body for some providers. The OpenAI SDK normalizes most of this, but inspect `response.choices[0].message.content` defensively when wiring a new provider.

## Further reading

- OpenAI's chat completions reference: https://platform.openai.com/docs/api-reference/chat
- OpenRouter model catalogue: https://openrouter.ai/models
```

- [ ] **Step 2: Commit**

```bash
git add docs/concepts/llm-api-basics.md
git commit -m "docs(concepts): add llm-api-basics primer"
```

---

### Task 13: Concept primer — `observability-trace-table.md`

**Files:**
- Create: `docs/concepts/observability-trace-table.md`

- [ ] **Step 1: Write the primer**

Create `docs/concepts/observability-trace-table.md`:

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add docs/concepts/observability-trace-table.md
git commit -m "docs(concepts): add observability-trace-table primer"
```

---

### Task 14: ADRs — trace write timing + module split

**Files:**
- Create: `docs/decisions/0001-trace-write-timing.md`
- Create: `docs/decisions/0002-llm-module-split.md`

- [ ] **Step 1: Write ADR 0001 (trace write timing)**

Create `docs/decisions/0001-trace-write-timing.md`:

```markdown
# 0001 — Single post-call write to `llm_calls`

**Status:** accepted
**Date:** 2026-05-09

## Context

Every LLM call must write a row to `llm_calls` for observability. Two reasonable patterns:

1. **Post-call only.** One INSERT after the API call returns (or errors). One row per call.
2. **Pre-call + update.** INSERT a `status='pending'` row at the start, UPDATE on completion. Two writes per call. Survives mid-call process crashes (the row is visible while the call is in flight).

V0 has very short calls (a few hundred ms), low call volume (one user), and no production-grade need to debug crash-mid-call scenarios.

## Decision

Single post-call write. The whole API call is wrapped in `try/except`; both success and failure paths write exactly one row.

## Consequences

**Easier:**
- One INSERT per call, less code, fewer failure modes.
- The row is "complete" when read — no `pending` rows to filter out.

**Harder:**
- A process crash mid-call leaves no record of the call. OpenRouter's logs (or local stderr) are the only trace.
- Long-running calls (e.g. multi-minute streaming) won't appear in queries until they complete.

## Alternatives considered

- **Pre-call + update** — rejected for V0 because crash visibility is not a current pain point and the 2x write cost (in code complexity) outweighs the benefit at this scale.
- **Append-only event stream** (one row per state transition) — rejected as overengineered for a single-user system.

Revisit if/when calls reliably take >5s or process crashes start hiding work.
```

- [ ] **Step 2: Write ADR 0002 (module split)**

Create `docs/decisions/0002-llm-module-split.md`:

```markdown
# 0002 — Three-module split: `llm.py` / `prompts.py` / `trace.py`

**Status:** accepted
**Date:** 2026-05-09

## Context

The slice-2 design needs three things: an LLM client, a prompt loader, and a trace-row writer. They're all small (~50–150 lines each). Two reasonable shapes:

1. **One module** (`llm.py`) doing all three. Smaller surface area, fewer files. Default YAGNI choice.
2. **Three modules**, one per responsibility. Larger surface, clearer boundaries.

This is a learning project — pedagogical clarity matters. A future eval harness (slice 5) will load prompts directly without going through `LLMClient`, so `prompts.py` will get a second consumer regardless.

## Decision

Three modules:

- `src/solo/trace.py` — `ensure_schema(conn)`, `record_call(conn, ...)`
- `src/solo/prompts.py` — `load(name)`, `render(name, **vars)`
- `src/solo/llm.py` — `LLMClient`, `MODEL_PRICING`, `compute_cost`

Each module has one job and a small interface. `LLMClient` composes the other two.

## Consequences

**Easier:**
- Each file is short and focused; explicit boundaries make the architecture readable.
- Eval harness in slice 5 can `from solo.prompts import load` without dragging in OpenAI deps.
- Tests are colocated with responsibility (`test_trace.py`, `test_prompts.py`, `test_llm.py`).

**Harder:**
- Three files instead of one. Marginally more navigation cost.
- A change that crosses two modules (e.g. adding a new field that flows from prompt → trace row) touches more files.

## Alternatives considered

- **One file** — rejected because the eval-harness consumer makes the prompts-loader split inevitable, and tracing is intrinsically separable from API calls.
- **Two files** (`llm.py` + `trace.py`, with prompts inlined in llm.py) — rejected for the same reason; `prompts.py` will be wanted standalone.
```

- [ ] **Step 3: Commit both ADRs together**

```bash
git add docs/decisions/0001-trace-write-timing.md docs/decisions/0002-llm-module-split.md
git commit -m "docs(decisions): add ADR-0001 trace write timing + ADR-0002 module split"
```

---

### Task 15: Update `docs/status.md`

**Files:**
- Modify: `docs/status.md`

- [ ] **Step 1: Update the status doc**

Replace these sections in `docs/status.md`:

Replace the `## Last updated` line with:
```markdown
**2026-05-09** — by Claude Code (Opus 4.7).
```

Replace the entire `## Current state` section with:
```markdown
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
```

Replace the `## What's next` section with:
```markdown
## What's next

Per `AGENTS.md` V0 scope, in order:

1. ~~Telegram capture → SQLite~~ — done (slice 1)
2. ~~`LLMClient` (OpenRouter) + `llm_calls` trace table~~ — done (slice 2)
3. **Lazy classifier.** Write `src/solo/prompts/classifier.md`, write `src/solo/classifier.py` that calls `LLMClient.structured("classifier", ClassifyResult, model=os.environ["SOLO_CLASSIFY_MODEL"], vars=...)`. Triggered when `/top3` is invoked: classify any unclassified rows first.
4. **`/top3` and `/log` commands.**
5. **Classifier eval harness** (`evals/classify.jsonl` + `scripts/eval.py`).
```

Replace the `## Open decisions deferred to implementation` section with:
```markdown
## Open decisions deferred to implementation

- Verify `MODEL_PRICING` rates against openrouter.ai/models when wiring real classifier calls.
- Whether OpenRouter's `response_format=BaseModel` works reliably across the Minimax/Kimi backends (flagged risk in slice-2 spec). Live integration test will tell us.
- Schema specifics for the classifier: column types, indexes, FTS for `/log` search.
- Apple Reminders bridge approach (V2 — out of V0 scope).
```

- [ ] **Step 2: Commit**

```bash
git add docs/status.md
git commit -m "docs(status): mark slice 2 complete, set slice 3 (classifier) as next"
```

---

### Task 16: Final verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: 39 passed, 1 skipped (the live test).

- [ ] **Step 2: Run linter**

Run: `uv run ruff check .`
Expected: `All checks passed!` (or zero errors).

- [ ] **Step 3: Verify the bot module still imports cleanly**

Run: `uv run python -c "from solo.bot import main; from solo.llm import LLMClient; from solo.trace import ensure_schema, record_call; from solo.prompts import load, render; print('all imports ok')"`
Expected: `all imports ok`.

- [ ] **Step 4: Verify schema is created on a fresh DB**

Run:
```bash
rm -f /tmp/solo-verify.db && uv run python -c "
import sqlite3
from solo.db import get_connection
from solo.trace import ensure_schema

conn = get_connection('/tmp/solo-verify.db')
ensure_schema(conn)
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]
print('tables:', tables)
assert 'entries' in tables and 'llm_calls' in tables
print('ok')
"
```
Expected: `tables: ['entries', 'llm_calls']` then `ok`.

- [ ] **Step 5: Verify git status is clean**

Run: `git status`
Expected: `nothing to commit, working tree clean`.

- [ ] **Step 6: Optionally run live integration test**

If you have `OPENROUTER_API_KEY`:

Run: `OPENROUTER_API_KEY=sk-or-... uv run pytest tests/test_llm_live.py -v`
Expected: `1 passed`. If `response_format` fails on Minimax/Kimi, capture as a follow-up issue and switch the live test to JSON-mode.

---

## Done criteria

- All 39 unit tests pass; live test skips by default.
- `uv run ruff check .` is clean.
- `solo.llm.LLMClient` is the only path to OpenRouter; importing `openai` outside `src/solo/llm.py` is grep-disallowed (verify: `grep -rn "import openai" src/ tests/ | grep -v "src/solo/llm.py"` returns empty).
- `docs/concepts/` has 2 primers; `docs/decisions/` has 2 ADRs; `docs/status.md` reflects slice 2 complete.
- `README.md` documents the environment variables.
- The bot starts cleanly and creates both tables (`entries`, `llm_calls`) on first run.
