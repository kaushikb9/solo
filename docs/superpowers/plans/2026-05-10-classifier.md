# Classifier (Slice 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `classify_pending(conn, llm, model)` — a never-raising, sequential, bounded-retry classifier that turns each unclassified `entries` row into `(kind, summary, priority)` written back to the row. Plus prompt file, schema migration, tests, ADR, concept primer, and status update.

**Architecture:** New `src/solo/classifier.py` exposes `ClassifyResult` (Pydantic) and `classify_pending`. Output stored as columns on `entries` (D4 in spec). DB migration is idempotent — runs inside `get_connection`. Failures bump `classification_attempts`; rows at `attempts ≥ 3` are skipped.

**Tech Stack:** Python 3.12, `pydantic`, `openai` SDK via OpenRouter (already wired in `LLMClient`), SQLite stdlib, `pytest` / `pytest-asyncio`, `uv`.

**Spec:** [`docs/superpowers/specs/2026-05-10-classifier-design.md`](../specs/2026-05-10-classifier-design.md)

---

## File Structure

| File | Purpose | New / Modified |
|---|---|---|
| `src/solo/db.py` | Schema + queries — extend `_SCHEMA`, add `_migrate_entries`, add `fetch_unclassified` / `apply_classification` / `record_classification_failure` | **Modified** |
| `src/solo/classifier.py` | `ClassifyResult` schema + `classify_pending` orchestrator | **New** |
| `src/solo/prompts/classifier.md` | Prompt with `{entry_text}` variable | **New** |
| `tests/test_db.py` | Extend with migration + new helper tests; update `test_entries_columns` for new columns | **Modified** |
| `tests/test_classifier.py` | Unit tests with fake LLM | **New** |
| `tests/test_classifier_live.py` | Gated live integration test (requires `OPENROUTER_API_KEY`) | **New** |
| `docs/concepts/structured-outputs.md` | Concept primer | **New** |
| `docs/decisions/0003-classifier-on-entries-vs-side-table.md` | ADR | **New** |
| `docs/architecture.md` | One-line: `classify.py` → `classifier.py` | **Modified** |
| `docs/status.md` | Mark slice 3 done; set next = slice 4 | **Modified** |

Each task below produces a self-contained, testable change. Commit after each task.

---

## Task 1: Extend `entries` schema + idempotent migration

**Files:**
- Modify: `src/solo/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Update the failing test for current columns**

The existing `test_entries_columns` test in `tests/test_db.py:25-36` enumerates the columns and will fail after we add new ones. Update it:

```python
    def test_entries_columns(self, conn):
        cursor = conn.execute("PRAGMA table_info(entries)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {
            "id",
            "raw_text",
            "telegram_chat_id",
            "telegram_message_id",
            "telegram_message_json",
            "created_at",
            "classified",
            "kind",
            "summary",
            "priority",
            "classification_attempts",
        }
```

- [ ] **Step 2: Add a fresh-DB defaults test (write before migrating)**

Append a new test in the `TestSchema` class in `tests/test_db.py`:

```python
    def test_new_classification_columns_have_correct_defaults(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(conn, "x", 1, 1, "{}")
        row = conn.execute(
            "SELECT kind, summary, priority, classification_attempts "
            "FROM entries WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert row[0] is None       # kind
        assert row[1] is None       # summary
        assert row[2] is None       # priority
        assert row[3] == 0          # classification_attempts
```

- [ ] **Step 3: Add an idempotent-migration test for an old DB**

Append to `tests/test_db.py` (top-level, outside `TestSchema`):

```python
class TestMigration:
    def test_migration_adds_columns_to_old_db(self, tmp_path):
        import sqlite3

        from solo.db import get_connection

        # Simulate a pre-slice-3 DB: only the original columns.
        path = tmp_path / "old.db"
        old = sqlite3.connect(str(path))
        old.executescript(
            """
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                telegram_chat_id INTEGER NOT NULL,
                telegram_message_id INTEGER NOT NULL,
                telegram_message_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                classified INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO entries (raw_text, telegram_chat_id, telegram_message_id, telegram_message_json)
            VALUES ('legacy thought', 1, 1, '{}');
            """
        )
        old.commit()
        old.close()

        # Open via get_connection — migration should run.
        conn = get_connection(str(path))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
        assert {"kind", "summary", "priority", "classification_attempts"}.issubset(cols)

        # Existing row preserved with default classification_attempts = 0.
        row = conn.execute(
            "SELECT raw_text, classification_attempts FROM entries"
        ).fetchone()
        assert row[0] == "legacy thought"
        assert row[1] == 0
        conn.close()

    def test_migration_is_idempotent(self, tmp_path):
        from solo.db import get_connection

        path = tmp_path / "x.db"
        get_connection(str(path)).close()
        # Second open must not raise (would fail with "duplicate column" without idempotence).
        get_connection(str(path)).close()
```

- [ ] **Step 4: Run the tests — confirm they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: `test_entries_columns`, `test_new_classification_columns_have_correct_defaults`, `TestMigration::test_migration_adds_columns_to_old_db` fail. `test_migration_is_idempotent` may pass (no migration logic yet, just `CREATE TABLE IF NOT EXISTS` is idempotent), but the column-set tests fail.

- [ ] **Step 5: Update `_SCHEMA` and add `_migrate_entries` in `src/solo/db.py`**

Replace the entire contents of `src/solo/db.py` with:

```python
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text TEXT NOT NULL,
    telegram_chat_id INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    telegram_message_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    classified INTEGER NOT NULL DEFAULT 0,
    kind TEXT,
    summary TEXT,
    priority TEXT,
    classification_attempts INTEGER NOT NULL DEFAULT 0
);
"""


def _migrate_entries(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
    additions = (
        ("kind",                    "ALTER TABLE entries ADD COLUMN kind TEXT"),
        ("summary",                 "ALTER TABLE entries ADD COLUMN summary TEXT"),
        ("priority",                "ALTER TABLE entries ADD COLUMN priority TEXT"),
        ("classification_attempts", "ALTER TABLE entries ADD COLUMN classification_attempts INTEGER NOT NULL DEFAULT 0"),
    )
    for col, ddl in additions:
        if col not in cols:
            conn.execute(ddl)
    conn.commit()


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate_entries(conn)
    return conn


def insert_entry(
    conn: sqlite3.Connection,
    raw_text: str,
    telegram_chat_id: int,
    telegram_message_id: int,
    telegram_message_json: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO entries (raw_text, telegram_chat_id, telegram_message_id, telegram_message_json)
        VALUES (?, ?, ?, ?)
        """,
        (raw_text, telegram_chat_id, telegram_message_id, telegram_message_json),
    )
    conn.commit()
    return cursor.lastrowid


def get_recent_entries(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    cursor = conn.execute(
        "SELECT * FROM entries ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 6: Run the tests — confirm green**

Run: `uv run pytest tests/test_db.py -v`
Expected: all `TestSchema`, `TestInsertEntry`, `TestGetRecentEntries`, `TestMigration` tests pass.

- [ ] **Step 7: Lint**

Run: `uv run ruff check src/solo/db.py tests/test_db.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(db): extend entries schema with classification columns

Add kind, summary, priority, classification_attempts. Idempotent
migration via _migrate_entries handles existing pre-slice-3 DBs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: DB query helpers (`fetch_unclassified`, `apply_classification`, `record_classification_failure`)

**Files:**
- Modify: `src/solo/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
class TestFetchUnclassified:
    def test_returns_only_unclassified_rows(self, conn):
        from solo.db import fetch_unclassified, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        conn.execute("UPDATE entries SET classified=1 WHERE id=?", (a,))
        conn.commit()

        rows = fetch_unclassified(conn)
        ids = [r["id"] for r in rows]
        assert ids == [b]

    def test_skips_rows_at_max_attempts(self, conn):
        from solo.db import fetch_unclassified, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        conn.execute("UPDATE entries SET classification_attempts=3 WHERE id=?", (a,))
        conn.commit()

        rows = fetch_unclassified(conn, max_attempts=3)
        assert [r["id"] for r in rows] == [b]

    def test_orders_by_created_at_ascending(self, conn):
        from solo.db import fetch_unclassified, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        # Force a known-later created_at on b so the ordering assertion is robust.
        b = insert_entry(conn, "b", 1, 2, "{}")
        conn.execute(
            "UPDATE entries SET created_at='2030-01-01T00:00:00.000Z' WHERE id=?",
            (b,),
        )
        conn.commit()

        rows = fetch_unclassified(conn)
        assert [r["id"] for r in rows] == [a, b]

    def test_limit_caps_results(self, conn):
        from solo.db import fetch_unclassified, insert_entry

        for i in range(5):
            insert_entry(conn, f"t{i}", 1, i, "{}")
        rows = fetch_unclassified(conn, limit=2)
        assert len(rows) == 2


class TestApplyClassification:
    def test_writes_fields_and_flips_classified(self, conn):
        from solo.db import apply_classification, insert_entry

        rid = insert_entry(conn, "x", 1, 1, "{}")
        apply_classification(conn, rid, "idea", "explore X", "high")

        row = conn.execute("SELECT * FROM entries WHERE id=?", (rid,)).fetchone()
        assert row["kind"] == "idea"
        assert row["summary"] == "explore X"
        assert row["priority"] == "high"
        assert row["classified"] == 1

    def test_truncates_long_summary(self, conn):
        from solo.db import apply_classification, insert_entry

        rid = insert_entry(conn, "x", 1, 1, "{}")
        long_summary = "a" * 200
        apply_classification(conn, rid, "note", long_summary, "low")

        stored = conn.execute(
            "SELECT summary FROM entries WHERE id=?", (rid,)
        ).fetchone()[0]
        assert len(stored) == 120

    def test_noop_for_already_classified_row(self, conn):
        from solo.db import apply_classification, insert_entry

        rid = insert_entry(conn, "x", 1, 1, "{}")
        apply_classification(conn, rid, "idea", "first", "high")
        apply_classification(conn, rid, "note", "second", "low")

        row = conn.execute("SELECT * FROM entries WHERE id=?", (rid,)).fetchone()
        assert row["kind"] == "idea"
        assert row["summary"] == "first"
        assert row["priority"] == "high"


class TestRecordClassificationFailure:
    def test_increments_attempts(self, conn):
        from solo.db import insert_entry, record_classification_failure

        rid = insert_entry(conn, "x", 1, 1, "{}")
        record_classification_failure(conn, rid)
        record_classification_failure(conn, rid)

        attempts = conn.execute(
            "SELECT classification_attempts FROM entries WHERE id=?", (rid,)
        ).fetchone()[0]
        assert attempts == 2

    def test_does_not_set_classified(self, conn):
        from solo.db import insert_entry, record_classification_failure

        rid = insert_entry(conn, "x", 1, 1, "{}")
        record_classification_failure(conn, rid)
        classified = conn.execute(
            "SELECT classified FROM entries WHERE id=?", (rid,)
        ).fetchone()[0]
        assert classified == 0
```

- [ ] **Step 2: Run the tests — confirm they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: 9 failures with `ImportError: cannot import name 'fetch_unclassified' from 'solo.db'` (and similarly for the other two helpers).

- [ ] **Step 3: Implement the three helpers**

Append to `src/solo/db.py`:

```python
def fetch_unclassified(
    conn: sqlite3.Connection,
    limit: int = 50,
    max_attempts: int = 3,
) -> list[dict]:
    cursor = conn.execute(
        """
        SELECT * FROM entries
        WHERE classified = 0 AND classification_attempts < ?
        ORDER BY created_at ASC, id ASC
        LIMIT ?
        """,
        (max_attempts, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


def apply_classification(
    conn: sqlite3.Connection,
    entry_id: int,
    kind: str,
    summary: str,
    priority: str,
) -> None:
    truncated = summary[:120]
    conn.execute(
        """
        UPDATE entries
        SET kind = ?, summary = ?, priority = ?, classified = 1
        WHERE id = ? AND classified = 0
        """,
        (kind, truncated, priority, entry_id),
    )
    conn.commit()


def record_classification_failure(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute(
        "UPDATE entries SET classification_attempts = classification_attempts + 1 WHERE id = ?",
        (entry_id,),
    )
    conn.commit()
```

- [ ] **Step 4: Run the tests — confirm green**

Run: `uv run pytest tests/test_db.py -v`
Expected: all green.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/solo/db.py tests/test_db.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "$(cat <<'EOF'
feat(db): add classifier query helpers

fetch_unclassified, apply_classification (truncates summary to 120
chars, no-op on already-classified rows), record_classification_failure.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Classifier prompt file

**Files:**
- Create: `src/solo/prompts/classifier.md`

- [ ] **Step 1: Write the prompt**

Create `src/solo/prompts/classifier.md`:

```markdown
You classify a single thought captured in a personal thinking log.
Output JSON matching the schema. Choose the closest fit; do not invent categories.

Categories (kind):
- idea       — a thought, hypothesis, or open question to explore
- soft_task  — vague work needing thinking before doing (e.g., "figure out X")
- hard_task  — concrete, executable, fits in Apple Reminders
- note       — observation, fact, snippet to remember; no action implied

Priority:
- high   — important and time-sensitive, or pulls strongly on attention
- medium — worth surfacing this week
- low    — fine to leave; reference value only

summary: one short line (≤ 120 chars) capturing the essence in the user's voice.

Entry:
{entry_text}
```

- [ ] **Step 2: Sanity-check render**

Run:

```bash
uv run python -c "from solo.prompts import render; print(render('classifier', entry_text='learn rust'))"
```

Expected: prints the rendered prompt with `learn rust` substituted at the bottom.

- [ ] **Step 3: Commit**

```bash
git add src/solo/prompts/classifier.md
git commit -m "$(cat <<'EOF'
feat(prompts): add classifier prompt

Encodes the four kinds (idea/soft_task/hard_task/note) and three
priority levels with explicit anchors.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `ClassifyResult` schema

**Files:**
- Create: `src/solo/classifier.py`
- Test: `tests/test_classifier.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_classifier.py`:

```python
import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    from solo.db import get_connection

    conn = get_connection(str(db_path))
    yield conn
    conn.close()


class TestClassifyResultSchema:
    def test_valid_payload(self):
        from solo.classifier import ClassifyResult

        r = ClassifyResult(kind="idea", summary="explore X", priority="high")
        assert r.kind == "idea"

    def test_invalid_kind_rejected(self):
        from pydantic import ValidationError

        from solo.classifier import ClassifyResult

        with pytest.raises(ValidationError):
            ClassifyResult(kind="bogus", summary="x", priority="high")

    def test_invalid_priority_rejected(self):
        from pydantic import ValidationError

        from solo.classifier import ClassifyResult

        with pytest.raises(ValidationError):
            ClassifyResult(kind="idea", summary="x", priority="urgent")
```

- [ ] **Step 2: Run the tests — confirm they fail**

Run: `uv run pytest tests/test_classifier.py -v`
Expected: ImportError — `solo.classifier` does not exist.

- [ ] **Step 3: Create `src/solo/classifier.py` with the schema only**

```python
"""Classifier — turns a raw entry into (kind, summary, priority).

All LLM calls go through solo.llm.LLMClient. classify_pending never raises;
failures bump classification_attempts and are picked up by the next call
until max_attempts is reached.
"""

from typing import Literal

from pydantic import BaseModel


class ClassifyResult(BaseModel):
    kind: Literal["idea", "soft_task", "hard_task", "note"]
    summary: str
    priority: Literal["low", "medium", "high"]
```

- [ ] **Step 4: Run the tests — confirm green**

Run: `uv run pytest tests/test_classifier.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/solo/classifier.py tests/test_classifier.py
git commit -m "$(cat <<'EOF'
feat(classifier): add ClassifyResult schema

Pydantic Literal types lock kind and priority to the documented enums.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `classify_pending` — happy path

**Files:**
- Modify: `src/solo/classifier.py`
- Test: `tests/test_classifier.py`

- [ ] **Step 1: Add fake-LLM fixture and happy-path tests**

Append to `tests/test_classifier.py`:

```python
class FakeLLM:
    """Duck-typed stand-in for LLMClient. Returns scripted results or raises."""

    def __init__(self, *, results=None, errors=None):
        self.results = list(results or [])
        self.errors = list(errors or [])
        self.calls = []

    async def structured(self, prompt_name, schema, *, model, vars):
        self.calls.append({"prompt": prompt_name, "model": model, "vars": vars})
        if self.errors and self.errors[0] is not None:
            err = self.errors.pop(0)
            self.results.pop(0) if self.results else None
            raise err
        if self.errors:
            self.errors.pop(0)
        return self.results.pop(0)


class TestClassifyPendingHappyPath:
    @pytest.mark.asyncio
    async def test_empty_backlog_returns_zero(self, conn):
        from solo.classifier import classify_pending

        llm = FakeLLM()
        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 0
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_three_rows_all_classified(self, conn):
        from solo.classifier import ClassifyResult, classify_pending
        from solo.db import insert_entry

        ids = [
            insert_entry(conn, "learn rust", 1, 1, "{}"),
            insert_entry(conn, "buy milk", 1, 2, "{}"),
            insert_entry(conn, "team morale", 1, 3, "{}"),
        ]
        llm = FakeLLM(
            results=[
                ClassifyResult(kind="idea",      summary="learn rust",   priority="medium"),
                ClassifyResult(kind="hard_task", summary="buy milk",     priority="low"),
                ClassifyResult(kind="soft_task", summary="team morale",  priority="high"),
            ]
        )

        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 3

        rows = {
            r["id"]: r
            for r in (
                dict(x)
                for x in conn.execute(
                    "SELECT * FROM entries WHERE id IN (?,?,?)", ids
                ).fetchall()
            )
        }
        assert rows[ids[0]]["kind"] == "idea"
        assert rows[ids[1]]["kind"] == "hard_task"
        assert rows[ids[2]]["kind"] == "soft_task"
        assert all(r["classified"] == 1 for r in rows.values())

        # Each call passed entry_text in vars and used the configured model.
        assert [c["model"] for c in llm.calls] == ["minimax/minimax-m2.7"] * 3
        assert [c["prompt"] for c in llm.calls] == ["classifier"] * 3
        assert {c["vars"]["entry_text"] for c in llm.calls} == {
            "learn rust", "buy milk", "team morale",
        }

    @pytest.mark.asyncio
    async def test_limit_respected(self, conn):
        from solo.classifier import ClassifyResult, classify_pending
        from solo.db import insert_entry

        for i in range(10):
            insert_entry(conn, f"t{i}", 1, i, "{}")

        llm = FakeLLM(
            results=[
                ClassifyResult(kind="note", summary=f"t{i}", priority="low")
                for i in range(3)
            ]
        )
        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7", limit=3)
        assert n == 3
        assert len(llm.calls) == 3
```

- [ ] **Step 2: Run the tests — confirm they fail**

Run: `uv run pytest tests/test_classifier.py -v`
Expected: ImportError — `classify_pending` is not yet defined.

- [ ] **Step 3: Implement `classify_pending` (happy path; failure handling next task)**

Append to `src/solo/classifier.py`:

```python
import logging
import sqlite3
from typing import Protocol

from solo import db

logger = logging.getLogger(__name__)


class _SupportsStructured(Protocol):
    async def structured(self, prompt_name, schema, *, model, vars): ...


async def classify_pending(
    conn: sqlite3.Connection,
    llm: _SupportsStructured,
    *,
    model: str,
    limit: int = 50,
    max_attempts: int = 3,
) -> int:
    """Classify pending entries. Sequential. Idempotent. Never raises.

    Returns the number of rows successfully classified in this call.
    """
    rows = db.fetch_unclassified(conn, limit=limit, max_attempts=max_attempts)
    success = 0
    for row in rows:
        result = await llm.structured(
            "classifier",
            ClassifyResult,
            model=model,
            vars={"entry_text": row["raw_text"]},
        )
        db.apply_classification(conn, row["id"], result.kind, result.summary, result.priority)
        success += 1
    return success
```

Note: this version does NOT yet handle errors. The next task adds the `try`/`except` branch and tests for it.

- [ ] **Step 4: Run the tests — confirm green**

Run: `uv run pytest tests/test_classifier.py -v`
Expected: all tests pass.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/solo/classifier.py tests/test_classifier.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/solo/classifier.py tests/test_classifier.py
git commit -m "$(cat <<'EOF'
feat(classifier): classify_pending happy path

Sequential pass over fetch_unclassified rows; calls LLMClient.structured
and writes back via apply_classification.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `classify_pending` — failure handling + bounded retries

**Files:**
- Modify: `src/solo/classifier.py`
- Test: `tests/test_classifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_classifier.py`:

```python
class TestClassifyPendingFailures:
    @pytest.mark.asyncio
    async def test_single_failure_increments_attempts(self, conn):
        from solo.classifier import classify_pending
        from solo.db import insert_entry

        rid = insert_entry(conn, "broken", 1, 1, "{}")
        llm = FakeLLM(errors=[RuntimeError("boom")])

        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 0

        row = conn.execute("SELECT * FROM entries WHERE id=?", (rid,)).fetchone()
        assert row["classification_attempts"] == 1
        assert row["classified"] == 0

    @pytest.mark.asyncio
    async def test_classify_pending_never_raises(self, conn):
        from solo.classifier import classify_pending
        from solo.db import insert_entry

        insert_entry(conn, "broken", 1, 1, "{}")
        llm = FakeLLM(errors=[RuntimeError("boom")])

        # Must not propagate.
        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 0

    @pytest.mark.asyncio
    async def test_mixed_batch(self, conn):
        from solo.classifier import ClassifyResult, classify_pending
        from solo.db import insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        c = insert_entry(conn, "c", 1, 3, "{}")

        # FakeLLM consumes results+errors in lockstep: result OR error per call.
        llm = FakeLLM(
            results=[
                ClassifyResult(kind="idea", summary="a", priority="low"),
                None,  # placeholder consumed when error fires
                ClassifyResult(kind="note", summary="c", priority="low"),
            ],
            errors=[None, RuntimeError("boom"), None],
        )

        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 2

        rows = {
            r["id"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM entries WHERE id IN (?,?,?)", (a, b, c)
            ).fetchall()
        }
        assert rows[a]["classified"] == 1
        assert rows[b]["classified"] == 0
        assert rows[b]["classification_attempts"] == 1
        assert rows[c]["classified"] == 1

    @pytest.mark.asyncio
    async def test_row_at_max_attempts_is_skipped(self, conn):
        from solo.classifier import classify_pending
        from solo.db import insert_entry

        rid = insert_entry(conn, "stuck", 1, 1, "{}")
        conn.execute(
            "UPDATE entries SET classification_attempts = 3 WHERE id = ?", (rid,)
        )
        conn.commit()

        llm = FakeLLM()
        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 0
        assert llm.calls == []  # row never reached the LLM
```

The `FakeLLM` defined in Task 5 already supports an `errors` list interleaved with `results`. The mixed-batch test relies on that lockstep behavior.

- [ ] **Step 2: Run the tests — confirm they fail**

Run: `uv run pytest tests/test_classifier.py -v`
Expected: failure tests fail because `classify_pending` currently lets exceptions propagate.

- [ ] **Step 3: Add try/except around the LLM call**

Edit `src/solo/classifier.py` — replace the body of the `for row in rows:` loop:

```python
    for row in rows:
        try:
            result = await llm.structured(
                "classifier",
                ClassifyResult,
                model=model,
                vars={"entry_text": row["raw_text"]},
            )
        except Exception as exc:
            logger.warning(
                "classify failed for entry %s: %s", row["id"], exc
            )
            db.record_classification_failure(conn, row["id"])
            continue
        db.apply_classification(
            conn, row["id"], result.kind, result.summary, result.priority
        )
        success += 1
```

- [ ] **Step 4: Run the tests — confirm green**

Run: `uv run pytest tests/test_classifier.py -v`
Expected: all green.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/solo/classifier.py tests/test_classifier.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/solo/classifier.py tests/test_classifier.py
git commit -m "$(cat <<'EOF'
feat(classifier): bounded-retry failure handling

LLM/parse failures bump classification_attempts via
record_classification_failure and continue. classify_pending
never raises; rows at attempts >= max_attempts are skipped by
fetch_unclassified.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Live integration test (gated)

**Files:**
- Create: `tests/test_classifier_live.py`

- [ ] **Step 1: Create the gated test**

Create `tests/test_classifier_live.py`:

```python
"""Live classifier integration test — hits a real OpenRouter model.

Skipped unless OPENROUTER_API_KEY is set.
Run manually: OPENROUTER_API_KEY=... uv run pytest tests/test_classifier_live.py -v
"""

import os

import pytest

LIVE = os.getenv("OPENROUTER_API_KEY")
pytestmark = pytest.mark.skipif(not LIVE, reason="OPENROUTER_API_KEY not set")

VALID_KINDS = {"idea", "soft_task", "hard_task", "note"}
VALID_PRIORITIES = {"low", "medium", "high"}


@pytest.mark.asyncio
async def test_classify_one_real_entry(tmp_path):
    from solo.classifier import classify_pending
    from solo.db import get_connection, insert_entry

    db_path = tmp_path / "live.db"
    conn = get_connection(str(db_path))
    rid = insert_entry(
        conn,
        raw_text="figure out a better hiring loop for senior engineers",
        telegram_chat_id=1,
        telegram_message_id=1,
        telegram_message_json="{}",
    )

    from solo.llm import LLMClient

    client = LLMClient(api_key=LIVE, db_path=db_path)
    n = await classify_pending(conn, client, model="minimax/minimax-m2.7")
    assert n == 1

    row = conn.execute("SELECT * FROM entries WHERE id=?", (rid,)).fetchone()
    assert row["kind"] in VALID_KINDS
    assert row["priority"] in VALID_PRIORITIES
    assert row["summary"] is not None and len(row["summary"]) <= 120
    assert row["classified"] == 1
    conn.close()
```

- [ ] **Step 2: Confirm skip behavior locally**

Run (without the env var): `uv run pytest tests/test_classifier_live.py -v`
Expected: 1 skipped.

- [ ] **Step 3: Lint**

Run: `uv run ruff check tests/test_classifier_live.py`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_classifier_live.py
git commit -m "$(cat <<'EOF'
test(classifier): add gated live integration test

Hits a real OpenRouter model with one entry; skipped unless
OPENROUTER_API_KEY is set. Resolves slice-2's open question
about response_format reliability across non-OpenAI backends.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Run live test manually (optional, requires API key)**

Run: `OPENROUTER_API_KEY=… uv run pytest tests/test_classifier_live.py -v`
Expected: 1 passed. If structured output fails on a backend, this is where we'd see it.

---

## Task 8: Concept primer — `docs/concepts/structured-outputs.md`

**Files:**
- Create: `docs/concepts/structured-outputs.md`

- [ ] **Step 1: Write the primer**

Create `docs/concepts/structured-outputs.md`:

````markdown
# Structured outputs

## What problem this solves

LLMs produce free-form text. When you want a *machine-readable* answer — a category label, a score, a list of fields — free-form text is a tax: you parse it, the parser breaks on a comma, you regex harder, you give up. Structured outputs make the model emit JSON that already conforms to a schema you define, so you skip the parsing fight entirely.

## The core idea

You declare a schema (in solo: a Pydantic `BaseModel`). You hand it to the SDK as `response_format`. The provider does two things: (1) injects schema-aware instructions into the prompt, and (2) constrains decoding so the output is valid JSON for that schema. You get back a typed object, not a string. If the schema says `priority: Literal["low", "medium", "high"]`, the model literally cannot return `"urgent"` — the provider rejects tokens that would make the JSON invalid.

```python
class ClassifyResult(BaseModel):
    kind: Literal["idea", "soft_task", "hard_task", "note"]
    summary: str
    priority: Literal["low", "medium", "high"]

result = await client.structured("classifier", ClassifyResult, model=..., vars=...)
# result is a ClassifyResult — type-checked, validated.
```

This is structurally different from "tell the LLM to output JSON and hope." It also subsumes a lot of what frameworks call *tool use* — a tool call is just a structured output with a name and arguments.

## How solo uses it

`LLMClient.structured` (`src/solo/llm.py:103`) wraps `client.beta.chat.completions.parse`, which is the OpenAI SDK's typed-response endpoint. The classifier (`src/solo/classifier.py`) defines `ClassifyResult` and calls `structured("classifier", ClassifyResult, …)`. No JSON parsing in solo's code.

## Common gotchas

- **Provider drift.** OpenRouter brokers many backends. Some implement structured outputs natively, some emulate them. solo's `tests/test_classifier_live.py` exists partly to catch this — if a backend silently degrades to "JSON-ish text," the test will surface it.
- **Schema-prompt mismatch.** Your prompt and your schema both convey expected behavior. Keep them in sync — don't list four categories in the prompt and three in the `Literal`.
- **Refusals look like errors.** When the model refuses or fails to fit the schema, the SDK raises. Wrap accordingly. solo's `LLMClient` writes an `error` row to `llm_calls` and re-raises; `classify_pending` then catches and bumps the retry counter.
- **Cost.** Structured outputs constrain decoding; this can slow generation slightly but rarely costs more tokens than equivalent free-form prompting.

## Further reading

- OpenAI docs: <https://platform.openai.com/docs/guides/structured-outputs>
- OpenRouter docs: <https://openrouter.ai/docs/structured-outputs>
- Pydantic `Literal` types: <https://docs.pydantic.dev/latest/concepts/types/>
````

- [ ] **Step 2: Commit**

```bash
git add docs/concepts/structured-outputs.md
git commit -m "$(cat <<'EOF'
docs(concepts): add structured-outputs primer

Concept primer paired with slice 3 classifier shipping.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: ADR — `docs/decisions/0003-classifier-on-entries-vs-side-table.md`

**Files:**
- Create: `docs/decisions/0003-classifier-on-entries-vs-side-table.md`

- [ ] **Step 1: Write the ADR**

Create the file:

```markdown
# 0003 — Store classifier output on `entries`, not a side table

- **Status:** accepted
- **Date:** 2026-05-10

## Context

Slice 3 introduces a classifier producing `(kind, summary, priority)` per entry. Two storage options:

1. Add columns to `entries`: `kind`, `summary`, `priority`, `classification_attempts`.
2. Separate `classifications` table with a foreign key back to `entries`, supporting multiple rows per entry (history of re-classifications, model drift studies, etc.).

V0 has no use case for re-classification history. `/top3` and `/log` (slices 4 and 5) read one classification per entry. The entries are personal, low-volume (~5–30/day), and the classifier output rides alongside the raw text.

## Decision

Add `kind`, `summary`, `priority`, and `classification_attempts` directly as columns on `entries`. Migration is idempotent — runs in `get_connection`. `classify_pending` (`src/solo/classifier.py`) writes via `apply_classification` (`src/solo/db.py`) which sets the columns and flips `classified=1` in the same `UPDATE`.

## Consequences

**Easier:**
- One row read for `/top3` and `/log` — no joins.
- Schema fits the V0 mental model: an entry *is* a classified thought.
- Migration is one `ALTER TABLE` per column; no cross-table backfill.

**Harder:**
- Re-classification overwrites. If we want history (e.g., to compare classifier prompts over time), we'd need a side table or a new `classification_history` log.
- Schema evolution: every new classifier field is another `ALTER TABLE`.

**Revisit when:** we want to keep history of multiple classifier runs over the same entry, or the classifier produces array-shaped output (tags, multi-label).

## Alternatives considered

- **Separate `classifications` table.** Cleaner separation, supports history. Rejected for V0: no consumer of history yet, more joins, more boilerplate. (`docs/superpowers/specs/2026-05-10-classifier-design.md` D4 captures the tradeoff.)
- **JSON column on `entries`.** Schema-flexible. Rejected: loses SQL queryability — `/top3` ranking and `/log` grouping become awkward.
```

- [ ] **Step 2: Commit**

```bash
git add docs/decisions/0003-classifier-on-entries-vs-side-table.md
git commit -m "$(cat <<'EOF'
docs(decisions): ADR-0003 classifier output on entries

Records D4 from the slice-3 spec with the revisit trigger
(re-classification history).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Architecture nit + status update

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

- [ ] **Step 1: Update `architecture.md`**

In `docs/architecture.md` §10 (file structure block, around line 142), replace the line:

```
    classify.py         # Classification + summarization (single-shot)
```

with:

```
    classifier.py       # Classification + summarization (single-shot)
```

- [ ] **Step 2: Update `docs/status.md`**

Replace the **Last updated**, **Current state**, and **What's next** sections with:

```markdown
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
```

Leave **Open decisions deferred to implementation**, **Blockers**, and **How to use this doc going forward** unchanged — except remove the resolved item:

> Whether OpenRouter's `response_format=BaseModel` works reliably across the Minimax/Kimi backends (flagged risk in slice-2 spec). Live integration test will tell us.

(Resolved by `tests/test_classifier_live.py`. Add a one-line note under **Open decisions deferred** if the live test fails on any backend during manual verification — but don't pre-write that note.)

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md docs/status.md
git commit -m "$(cat <<'EOF'
docs: mark slice 3 done; rename classify.py -> classifier.py

Architecture file structure now matches the codebase. Status flips
to slice 4 (top3 + log) as next.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Final verification cycle

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (live test skipped unless API key set).

- [ ] **Step 2: Lint everything touched in this slice**

Run: `uv run ruff check .`
Expected: clean.

- [ ] **Step 3: Format check**

Run: `uv run ruff format --check .`
Expected: clean.

- [ ] **Step 4: Manual live integration test (opt-in)**

If `OPENROUTER_API_KEY` is available locally, run:

```bash
OPENROUTER_API_KEY=… uv run pytest tests/test_classifier_live.py -v
```

Expected: 1 passed. If it fails, the spec's open question about OpenRouter backend reliability is now answered — record findings in `docs/status.md` under **Open decisions deferred**.

- [ ] **Step 5: Both reviewers (per AGENTS.md)**

After all tasks above are complete and verified, run:
- the generic `code-reviewer` agent
- the `solo-reviewer` agent (in `.claude/agents/solo-reviewer.md`)

Expected: both clean. Address feedback before claiming slice 3 done.

- [ ] **Step 6: Push (only if user asks)**

```bash
git log --oneline origin/main..HEAD
```

Review the commit list with the user before any push.

---

## Spec coverage check (self-review)

Spec requirement → task that implements it:

- D1 schema fields → Task 4 (`ClassifyResult`)
- D2 kind enum → Task 4 (`Literal[...]`)
- D3 priority enum → Task 4 (`Literal[...]`)
- D4 columns on entries → Task 1 (schema + migration)
- D5 bounded retries → Task 6 (failure handling) + Task 1 (column) + Task 2 (`fetch_unclassified` filter)
- D6 sequential → Task 5/6 (single `for` loop, no `gather`)
- D7 module name → Task 4 (file name); Task 10 (architecture nit)
- Schema migration idempotent → Task 1 Step 5 (`_migrate_entries`); test in Task 1 Step 3
- DB query helpers → Task 2
- Prompt file → Task 3
- `classify_pending` happy path → Task 5
- `classify_pending` failure handling → Task 6
- Live integration test → Task 7
- Concept primer → Task 8
- ADR → Task 9
- Architecture nit + status → Task 10
- Verification cycle → Task 11

All spec items have a task. No placeholders, no "TBD", no "similar to Task N" — every task carries the code or commands the implementer needs.
