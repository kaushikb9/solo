# Slice 6 — Admin surface + visual refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship five new Telegram commands (`/list`, `/drop`, `/done`, `/redo`, `/help`), rename `/log` → `/all`, and replace `/top3` + `/all` output with a terse visual format (emoji markers, age, `@name` mentions, stale-item warnings).

**Architecture:** Additive schema bump (`done`, `mentions`) on the `entries` table via the existing per-column migration. Mentions extracted at insert time via regex (no LLM change). Pure formatters in `solo.commands` rewritten with `_age` and `_marker` helpers. New handlers wired into `bot.main()`.

**Tech Stack:** Python 3.12, `sqlite3` stdlib, `python-telegram-bot` `CommandHandler`, `pytest` + `pytest-asyncio`, `ruff`.

**Spec:** [`docs/superpowers/specs/2026-05-24-admin-surface-design.md`](../specs/2026-05-24-admin-surface-design.md)

---

## Task 1: `solo.mentions.extract`

**Files:**
- Create: `src/solo/mentions.py`
- Create: `tests/test_mentions.py`

- [ ] **Step 1: Write failing tests**

`tests/test_mentions.py`:

```python
def test_extract_empty_returns_empty_list():
    from solo.mentions import extract

    assert extract("") == []
    assert extract("no mentions here") == []


def test_extract_single_mention():
    from solo.mentions import extract

    assert extract("ping @alice about it") == ["alice"]


def test_extract_multiple_mentions_preserves_order():
    from solo.mentions import extract

    assert extract("loop @alice and @bob on this") == ["alice", "bob"]


def test_extract_dedupes_case_insensitively():
    from solo.mentions import extract

    assert extract("@Alice told @alice and @ALICE") == ["alice"]


def test_extract_handles_trailing_punctuation():
    from solo.mentions import extract

    assert extract("ping @alice, then @bob.") == ["alice", "bob"]


def test_extract_ignores_email_like_strings():
    from solo.mentions import extract

    # @ inside an email address shouldn't count — \w+ won't span the @ either way,
    # so kb@example.com yields ["example"] from the @example. Document that.
    # If kb wants emails ignored, that's a follow-up.
    assert extract("kb@example.com") == ["example"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_mentions.py -v`
Expected: `ModuleNotFoundError: No module named 'solo.mentions'`

- [ ] **Step 3: Implementation**

`src/solo/mentions.py`:

```python
"""Extract @-mentions from raw entry text.

Pure module. Used at insert_entry time to populate the `mentions` column,
which the /list and /top3 formatters render as a 👥 marker.
"""

import re

_MENTION_RE = re.compile(r"@(\w+)")


def extract(raw_text: str) -> list[str]:
    """Return @-mentions in first-appearance order, lower-cased, deduped."""
    seen: dict[str, None] = {}
    for m in _MENTION_RE.findall(raw_text):
        seen.setdefault(m.lower(), None)
    return list(seen)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_mentions.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/mentions.py tests/test_mentions.py
git commit -m "feat(mentions): extract @-mentions from raw entry text"
```

---

## Task 2: Schema bump — `done` + `mentions` columns + migration

**Files:**
- Modify: `src/solo/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Extend `tests/test_db.py` (the existing `TestSchema` and `TestMigration` classes). Update `test_entries_columns` to expect the two new columns, and add a migration test:

```python
# In TestSchema, replace test_entries_columns body:
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
        "done",
        "mentions",
    }


# In TestSchema, add new test:
def test_done_and_mentions_have_correct_defaults(self, conn):
    from solo.db import insert_entry

    row_id = insert_entry(conn, "plain thought", 1, 1, "{}")
    row = conn.execute(
        "SELECT done, mentions FROM entries WHERE id = ?", (row_id,)
    ).fetchone()
    assert row[0] == 0          # done defaults to 0
    assert row[1] is None       # mentions NULL when no @-names


# In TestMigration, extend the assertion in test_migration_adds_columns_to_old_db
# to include the new columns:
def test_migration_adds_columns_to_old_db(self, tmp_path):
    import sqlite3

    from solo.db import get_connection

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
        INSERT INTO entries (
            raw_text, telegram_chat_id,
            telegram_message_id, telegram_message_json
        ) VALUES ('legacy thought', 1, 1, '{}');
        """
    )
    old.commit()
    old.close()

    conn = get_connection(str(path))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
    assert {
        "kind", "summary", "priority", "classification_attempts",
        "done", "mentions",
    }.issubset(cols)

    row = conn.execute(
        "SELECT raw_text, classification_attempts, done, mentions FROM entries"
    ).fetchone()
    assert row[0] == "legacy thought"
    assert row[1] == 0
    assert row[2] == 0
    assert row[3] is None
    conn.close()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_db.py::TestSchema tests/test_db.py::TestMigration -v`
Expected: failures on column-set assertion, default value asserts.

- [ ] **Step 3: Update `_SCHEMA` and `_migrate_entries`**

In `src/solo/db.py`, replace the `_SCHEMA` constant and `_migrate_entries` body:

```python
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
    classification_attempts INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    mentions TEXT
);
"""


def _migrate_entries(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
    additions = (
        ("kind", "ALTER TABLE entries ADD COLUMN kind TEXT"),
        ("summary", "ALTER TABLE entries ADD COLUMN summary TEXT"),
        ("priority", "ALTER TABLE entries ADD COLUMN priority TEXT"),
        (
            "classification_attempts",
            "ALTER TABLE entries ADD COLUMN classification_attempts INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "done",
            "ALTER TABLE entries ADD COLUMN done INTEGER NOT NULL DEFAULT 0",
        ),
        ("mentions", "ALTER TABLE entries ADD COLUMN mentions TEXT"),
    )
    for col, ddl in additions:
        if col not in cols:
            conn.execute(ddl)
    conn.commit()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_db.py::TestSchema tests/test_db.py::TestMigration -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "feat(db): add done + mentions columns to entries"
```

---

## Task 3: `insert_entry` populates `mentions`

**Files:**
- Modify: `src/solo/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_db.py` (in `TestInsertEntry`):

```python
    def test_insert_extracts_mentions(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(
            conn,
            raw_text="loop @alice and @bob on the doc",
            telegram_chat_id=1,
            telegram_message_id=1,
            telegram_message_json="{}",
        )
        row = conn.execute("SELECT mentions FROM entries WHERE id=?", (row_id,)).fetchone()
        assert row["mentions"] == "alice,bob"

    def test_insert_with_no_mentions_stores_null(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(
            conn,
            raw_text="plain thought, no names",
            telegram_chat_id=1,
            telegram_message_id=1,
            telegram_message_json="{}",
        )
        row = conn.execute("SELECT mentions FROM entries WHERE id=?", (row_id,)).fetchone()
        assert row["mentions"] is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_db.py::TestInsertEntry -v`
Expected: 2 failures on the new tests (mentions field will be NULL until insert_entry uses it).

- [ ] **Step 3: Update `insert_entry`**

Replace `insert_entry` in `src/solo/db.py`:

```python
def insert_entry(
    conn: sqlite3.Connection,
    raw_text: str,
    telegram_chat_id: int,
    telegram_message_id: int,
    telegram_message_json: str,
) -> int:
    from solo import mentions as _mentions  # local import to avoid cycles

    names = _mentions.extract(raw_text)
    cursor = conn.execute(
        """
        INSERT INTO entries (
            raw_text, telegram_chat_id, telegram_message_id,
            telegram_message_json, mentions
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            raw_text,
            telegram_chat_id,
            telegram_message_id,
            telegram_message_json,
            ",".join(names) if names else None,
        ),
    )
    conn.commit()
    return cursor.lastrowid
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: all green (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "feat(db): populate mentions on insert via regex extraction"
```

---

## Task 4: DB mutation helpers — `mark_done`, `delete_entry`, `reset_for_reclassification`, `fetch_active`

**Files:**
- Modify: `src/solo/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_db.py`:

```python
class TestMarkDone:
    def test_marks_existing_row_done(self, conn):
        from solo.db import insert_entry, mark_done

        rid = insert_entry(conn, "x", 1, 1, "{}")
        ok = mark_done(conn, rid)
        assert ok is True

        done = conn.execute("SELECT done FROM entries WHERE id=?", (rid,)).fetchone()[0]
        assert done == 1

    def test_returns_false_for_unknown_id(self, conn):
        from solo.db import mark_done

        assert mark_done(conn, 9999) is False


class TestDeleteEntry:
    def test_deletes_existing_row(self, conn):
        from solo.db import delete_entry, insert_entry

        rid = insert_entry(conn, "x", 1, 1, "{}")
        ok = delete_entry(conn, rid)
        assert ok is True

        row = conn.execute("SELECT id FROM entries WHERE id=?", (rid,)).fetchone()
        assert row is None

    def test_returns_false_for_unknown_id(self, conn):
        from solo.db import delete_entry

        assert delete_entry(conn, 9999) is False


class TestResetForReclassification:
    def test_clears_classification_fields(self, conn):
        from solo.db import apply_classification, insert_entry, reset_for_reclassification

        rid = insert_entry(conn, "x", 1, 1, "{}")
        apply_classification(conn, rid, "idea", "summary text", "high")

        ok = reset_for_reclassification(conn, rid)
        assert ok is True

        row = conn.execute(
            "SELECT classified, kind, summary, priority, classification_attempts "
            "FROM entries WHERE id=?",
            (rid,),
        ).fetchone()
        assert row[0] == 0
        assert row[1] is None
        assert row[2] is None
        assert row[3] is None
        assert row[4] == 0

    def test_returns_false_for_unknown_id(self, conn):
        from solo.db import reset_for_reclassification

        assert reset_for_reclassification(conn, 9999) is False


class TestFetchActive:
    def test_returns_all_classified_active_rows(self, conn):
        from solo.db import apply_classification, fetch_active, insert_entry, mark_done

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        c = insert_entry(conn, "c", 1, 3, "{}")
        apply_classification(conn, a, "idea", "a", "low")
        apply_classification(conn, b, "soft_task", "b", "high")
        apply_classification(conn, c, "note", "c", "low")
        mark_done(conn, b)

        rows = fetch_active(conn)
        ids = sorted(r["id"] for r in rows)
        assert ids == [a, c]

    def test_filters_by_kinds_when_given(self, conn):
        from solo.db import apply_classification, fetch_active, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        apply_classification(conn, a, "idea", "a", "low")
        apply_classification(conn, b, "note", "b", "low")

        rows = fetch_active(conn, kinds=["idea"])
        assert [r["id"] for r in rows] == [a]

    def test_includes_unclassified_when_no_kinds_filter(self, conn):
        from solo.db import fetch_active, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        rows = fetch_active(conn)
        ids = [r["id"] for r in rows]
        assert a in ids
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_db.py::TestMarkDone tests/test_db.py::TestDeleteEntry tests/test_db.py::TestResetForReclassification tests/test_db.py::TestFetchActive -v`
Expected: ImportError on each — none of these helpers exist yet.

- [ ] **Step 3: Add the helpers**

Append to `src/solo/db.py` (after `fetch_classified`):

```python
def fetch_active(
    conn: sqlite3.Connection,
    kinds: list[str] | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return active (done=0) entries, optionally filtered to kinds.

    When `kinds` is None, includes unclassified rows. When given, restricts
    to classified rows whose `kind` matches.
    """
    if kinds is None:
        cursor = conn.execute(
            "SELECT * FROM entries WHERE done = 0 "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )
    else:
        if not kinds:
            return []
        placeholders = ",".join("?" * len(kinds))
        cursor = conn.execute(
            f"SELECT * FROM entries WHERE done = 0 AND classified = 1 "
            f"AND kind IN ({placeholders}) "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (*kinds, limit),
        )
    return [dict(row) for row in cursor.fetchall()]


def mark_done(conn: sqlite3.Connection, entry_id: int) -> bool:
    """Set done=1. Returns True iff a row was updated."""
    cursor = conn.execute(
        "UPDATE entries SET done = 1 WHERE id = ?",
        (entry_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_entry(conn: sqlite3.Connection, entry_id: int) -> bool:
    """Hard delete. Returns True iff a row was deleted."""
    cursor = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    conn.commit()
    return cursor.rowcount > 0


def reset_for_reclassification(conn: sqlite3.Connection, entry_id: int) -> bool:
    """Zero kind/summary/priority/attempts/classified. Next classify_pending
    will re-run this row. Returns True iff a row was updated."""
    cursor = conn.execute(
        """
        UPDATE entries
        SET classified = 0,
            kind = NULL,
            summary = NULL,
            priority = NULL,
            classification_attempts = 0
        WHERE id = ?
        """,
        (entry_id,),
    )
    conn.commit()
    return cursor.rowcount > 0
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "feat(db): add mark_done, delete_entry, reset_for_reclassification, fetch_active"
```

---

## Task 5: `fetch_classified` filters `done=0`

**Files:**
- Modify: `src/solo/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_db.py` (in `TestFetchClassified`):

```python
    def test_excludes_done_rows(self, conn):
        from solo.db import apply_classification, fetch_classified, insert_entry, mark_done

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        apply_classification(conn, a, "idea", "a", "high")
        apply_classification(conn, b, "idea", "b", "high")
        mark_done(conn, a)

        rows = fetch_classified(conn, kinds=["idea"])
        assert [r["id"] for r in rows] == [b]
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_db.py::TestFetchClassified::test_excludes_done_rows -v`
Expected: failure — done row still included.

- [ ] **Step 3: Patch `fetch_classified`**

Replace the WHERE clause in `fetch_classified`:

```python
def fetch_classified(
    conn: sqlite3.Connection,
    kinds: list[str],
    limit: int = 200,
) -> list[dict]:
    """Return classified, not-done entries matching any of the given kinds,
    newest first. `kinds` is code-controlled (not user input), so building
    the IN-clause via string interpolation is safe."""
    if not kinds:
        return []
    placeholders = ",".join("?" * len(kinds))
    cursor = conn.execute(
        f"SELECT * FROM entries WHERE classified = 1 AND done = 0 "
        f"AND kind IN ({placeholders}) "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (*kinds, limit),
    )
    return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "feat(db): fetch_classified excludes done rows"
```

---

## Task 6: `_age` and `_marker` pure helpers

**Files:**
- Modify: `src/solo/commands.py`
- Modify: `tests/test_commands.py`

- [ ] **Step 1: Write failing tests**

In `tests/test_commands.py`, append a new test class (place it before the existing `TestFormatTop3`):

```python
from datetime import UTC, datetime


class TestAge:
    def test_just_now(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        assert _age("2026-05-24T09:30:00.000Z", now=now) == "just now"

    def test_days(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        assert _age("2026-05-20T10:00:00.000Z", now=now) == "4d"

    def test_just_under_two_weeks(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        assert _age("2026-05-12T10:00:00.000Z", now=now) == "12d"

    def test_weeks(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        # 21 days = 3w
        assert _age("2026-05-03T10:00:00.000Z", now=now) == "3w"

    def test_months(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        # 90 days = 3mo
        assert _age("2026-02-23T10:00:00.000Z", now=now) == "3mo"


class TestMarker:
    def test_none_returns_ideation(self):
        from solo.commands import _marker

        assert _marker(None) == "💡"

    def test_empty_string_returns_ideation(self):
        from solo.commands import _marker

        assert _marker("") == "💡"

    def test_single_mention(self):
        from solo.commands import _marker

        assert _marker("alice") == "👥 @alice"

    def test_multiple_mentions(self):
        from solo.commands import _marker

        assert _marker("alice,bob") == "👥 @alice @bob"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_commands.py::TestAge tests/test_commands.py::TestMarker -v`
Expected: ImportError on `_age` and `_marker`.

- [ ] **Step 3: Add the helpers**

Insert into `src/solo/commands.py` after the existing imports + before the `_allowed` function:

```python
from datetime import UTC, datetime


def _age(iso_ts: str, *, now: datetime | None = None) -> str:
    """Render the age of an ISO timestamp as 'just now', 'Nd', 'Nw', or 'Nmo'."""
    now = now or datetime.now(UTC)
    # SQLite emits "2026-05-24T10:00:00.000Z"; fromisoformat needs +00:00.
    created = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    days = (now - created).days
    if days <= 0:
        return "just now"
    if days < 14:
        return f"{days}d"
    if days < 60:
        return f"{days // 7}w"
    return f"{days // 30}mo"


def _marker(mentions_csv: str | None) -> str:
    """Render the entry marker: 👥 + names when mentions present, else 💡."""
    if not mentions_csv:
        return "💡"
    names = [f"@{n}" for n in mentions_csv.split(",") if n]
    return "👥 " + " ".join(names)
```

Also remove the old `_short_date` helper — nothing should reference it after this slice's format rewrite.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_commands.py::TestAge tests/test_commands.py::TestMarker -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): add _age and _marker pure formatters"
```

---

## Task 7: Rewrite `format_top3` (terse + emoji + aging section)

**Files:**
- Modify: `src/solo/commands.py`
- Modify: `tests/test_commands.py`

- [ ] **Step 1: Delete the old `TestFormatTop3`**

In `tests/test_commands.py`, remove the existing `class TestFormatTop3:` block entirely (the two tests `test_renders_three_items_with_priority_and_kind` and `test_empty_returns_nothing_to_rank_yet`). Also update the existing `TestHandleTop3` assertions (covered in Task 11) — leave them for now; the handler tests still pass strings into `format_top3`, but they check for substrings that will change. We'll fix them in Task 11.

- [ ] **Step 2: Write new failing tests**

Append to `tests/test_commands.py`:

```python
class TestFormatTop3:
    def _row(self, **overrides):
        base = {
            "id": 1,
            "kind": "idea",
            "priority": "med",
            "summary": "embeddings for dedup",
            "mentions": None,
            "created_at": "2026-05-23T10:00:00.000Z",
        }
        base.update(overrides)
        return base

    def test_empty_returns_nothing_to_rank_yet(self):
        from solo.commands import format_top3

        assert format_top3([], aging=[]) == "nothing to rank yet"

    def test_renders_three_terse_items_with_ideation_marker(self):
        from solo.commands import format_top3

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        top = [
            self._row(id=1, summary="positioning for new feature",
                     created_at="2026-05-23T10:00:00.000Z"),
            self._row(id=2, summary="embeddings for dedup",
                     created_at="2026-05-20T10:00:00.000Z"),
            self._row(id=3, summary="prompt caching paper",
                     created_at="2026-05-10T10:00:00.000Z"),
        ]
        out = format_top3(top, aging=[], now=now)
        assert "Top 3 for today:" in out
        assert "1️⃣ 💡 positioning for new feature (1d)" in out
        assert "2️⃣ 💡 embeddings for dedup (4d)" in out
        # 14d → renders as "2w" and gets the ⚠️
        assert "3️⃣ 💡 prompt caching paper (2w) ⚠️" in out

    def test_renders_mention_marker(self):
        from solo.commands import format_top3

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        top = [self._row(mentions="ashish", summary="1BHK reimbursement")]
        out = format_top3(top, aging=[], now=now)
        assert "1️⃣ 👥 @ashish 1BHK reimbursement" in out

    def test_includes_aging_section(self):
        from solo.commands import format_top3

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        top = [self._row(id=1, summary="t1", created_at="2026-05-23T10:00:00.000Z")]
        aging = [
            self._row(id=10, summary="mentoring plan",
                     created_at="2026-05-03T10:00:00.000Z"),
            self._row(id=11, summary="team morale", mentions="john",
                     created_at="2026-04-15T10:00:00.000Z"),
        ]
        out = format_top3(top, aging=aging, now=now)
        assert "⚠️ Also aging (>14d, not in top 3):" in out
        assert "💡 mentoring plan (3w)" in out
        assert "👥 @john team morale" in out

    def test_aging_section_caps_at_five_with_overflow_note(self):
        from solo.commands import format_top3

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        top = [self._row(id=1, summary="t1", created_at="2026-05-23T10:00:00.000Z")]
        aging = [
            self._row(id=10 + i, summary=f"stale {i}",
                     created_at="2026-04-15T10:00:00.000Z")
            for i in range(8)
        ]
        out = format_top3(top, aging=aging, now=now)
        # First 5 listed, then "(+3 more)"
        assert "(+3 more)" in out
```

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/test_commands.py::TestFormatTop3 -v`
Expected: 5 failures — `format_top3` doesn't accept `aging=` kwarg yet, output format mismatch.

- [ ] **Step 4: Rewrite `format_top3`**

Replace the existing `format_top3` in `src/solo/commands.py`:

```python
_NUMBER_EMOJI = ("1️⃣", "2️⃣", "3️⃣")
_STALE_AGE_DAYS = 14
_AGING_CAP = 5


def _is_stale(iso_ts: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    created = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (now - created).days > _STALE_AGE_DAYS


def format_top3(
    top: list[dict],
    *,
    aging: list[dict],
    now: datetime | None = None,
) -> str:
    if not top:
        return "nothing to rank yet"

    lines = ["Top 3 for today:", ""]
    for i, r in enumerate(top):
        if i >= len(_NUMBER_EMOJI):
            break
        marker = _marker(r.get("mentions"))
        age = _age(r["created_at"], now=now)
        stale = " ⚠️" if _is_stale(r["created_at"], now=now) else ""
        lines.append(
            f"{_NUMBER_EMOJI[i]} {marker} {r['summary']} ({age}){stale}"
        )

    if aging:
        lines.append("")
        lines.append("⚠️ Also aging (>14d, not in top 3):")
        shown = aging[:_AGING_CAP]
        for r in shown:
            marker = _marker(r.get("mentions"))
            age = _age(r["created_at"], now=now)
            lines.append(f"   • {marker} {r['summary']} ({age})")
        overflow = len(aging) - len(shown)
        if overflow > 0:
            lines.append(f"   (+{overflow} more)")

    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/test_commands.py::TestFormatTop3 -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): rewrite format_top3 with terse emoji + aging section"
```

---

## Task 8: `format_list` (active items, grouped, with IDs)

**Files:**
- Modify: `src/solo/commands.py`
- Modify: `tests/test_commands.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_commands.py`:

```python
class TestFormatList:
    def _row(self, **overrides):
        base = {
            "id": 1,
            "classified": 1,
            "kind": "idea",
            "priority": "med",
            "summary": "embeddings for dedup",
            "raw_text": "embeddings for dedup",
            "mentions": None,
            "created_at": "2026-05-23T10:00:00.000Z",
        }
        base.update(overrides)
        return base

    def test_empty_returns_nothing_active(self):
        from solo.commands import format_list

        assert format_list([]) == "nothing active"

    def test_groups_sections_in_fixed_order(self):
        from solo.commands import format_list

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        rows = [
            self._row(id=1, kind="note", summary="n1"),
            self._row(id=2, kind="idea", summary="i1"),
            self._row(id=3, kind="hard_task", summary="h1"),
            self._row(id=4, kind="soft_task", summary="s1"),
        ]
        out = format_list(rows, now=now)
        ideas_pos = out.find("💡 ideas")
        soft_pos = out.find("🌀 soft_tasks")
        hard_pos = out.find("🔨 hard_tasks")
        note_pos = out.find("📝 notes")
        assert ideas_pos < soft_pos < hard_pos < note_pos

    def test_includes_id_age_and_priority_per_row(self):
        from solo.commands import format_list

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        rows = [self._row(id=27, summary="figure out positioning",
                          priority="high",
                          created_at="2026-05-23T10:00:00.000Z")]
        out = format_list(rows, now=now)
        assert "· 27 💡 figure out positioning (1d) [high]" in out

    def test_renders_mention_marker(self):
        from solo.commands import format_list

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        rows = [self._row(id=28, kind="hard_task", mentions="ashish",
                          summary="APD docs for directs",
                          created_at="2026-05-23T10:00:00.000Z")]
        out = format_list(rows, now=now)
        assert "· 28 👥 @ashish APD docs for directs" in out

    def test_renders_unclassified_section(self):
        from solo.commands import format_list

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        rows = [self._row(
            id=30, classified=0, kind=None, summary=None, priority=None,
            raw_text="some thought captured but not classified yet",
            created_at="2026-05-24T09:55:00.000Z",
        )]
        out = format_list(rows, now=now)
        assert "⏳ unclassified" in out
        assert "· 30 some thought captured but not classified yet (just now)" in out

    def test_header_count_matches_total_rows(self):
        from solo.commands import format_list

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        rows = [self._row(id=i) for i in range(7)]
        out = format_list(rows, now=now)
        assert "Active (7):" in out

    def test_stale_warning_on_aging_rows(self):
        from solo.commands import format_list

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        rows = [self._row(id=1, summary="old idea",
                          created_at="2026-05-03T10:00:00.000Z")]
        out = format_list(rows, now=now)
        assert "(3w) [med] ⚠️" in out
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_commands.py::TestFormatList -v`
Expected: ImportError or test failures.

- [ ] **Step 3: Implement `format_list`**

Append to `src/solo/commands.py` (after `format_top3`):

```python
_LIST_KIND_ORDER = (
    ("idea", "💡 ideas"),
    ("soft_task", "🌀 soft_tasks"),
    ("hard_task", "🔨 hard_tasks"),
    ("note", "📝 notes"),
)
_UNCLASSIFIED_HEADER = "⏳ unclassified"


def _format_list_row(row: dict, *, now: datetime | None) -> str:
    age = _age(row["created_at"], now=now)
    stale = " ⚠️" if _is_stale(row["created_at"], now=now) else ""
    if row.get("classified"):
        marker = _marker(row.get("mentions"))
        summary = row["summary"]
        priority = row.get("priority") or ""
        return f"  · {row['id']} {marker} {summary} ({age}) [{priority}]{stale}"
    # Unclassified: render raw_text, no marker, no priority
    return f"  · {row['id']} {row['raw_text']} ({age}){stale}"


def format_list(rows: list[dict], *, now: datetime | None = None) -> str:
    if not rows:
        return "nothing active"

    buckets: dict[str | None, list[dict]] = {k: [] for k, _ in _LIST_KIND_ORDER}
    buckets[None] = []
    for row in rows:
        if row.get("classified") and row.get("kind") in buckets:
            buckets[row["kind"]].append(row)
        else:
            buckets[None].append(row)

    out: list[str] = [f"Active ({len(rows)}):"]
    for kind, header in _LIST_KIND_ORDER:
        items = buckets[kind]
        if not items:
            continue
        out.append("")
        out.append(header)
        for r in items:
            out.append(_format_list_row(r, now=now))
    if buckets[None]:
        out.append("")
        out.append(_UNCLASSIFIED_HEADER)
        for r in buckets[None]:
            out.append(_format_list_row(r, now=now))
    return "\n".join(out)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_commands.py::TestFormatList -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): add format_list (active items, grouped, with IDs)"
```

---

## Task 9: `format_all` (replaces `format_log`)

**Files:**
- Modify: `src/solo/commands.py`
- Modify: `tests/test_commands.py`

- [ ] **Step 1: Remove the old `TestFormatLog` and `format_log`**

In `tests/test_commands.py`, delete the entire `class TestFormatLog:` block.
In `src/solo/commands.py`, delete the `format_log` function.

- [ ] **Step 2: Write failing tests for `format_all`**

Append to `tests/test_commands.py`:

```python
class TestFormatAll:
    def _row(self, **overrides):
        base = {
            "id": 1,
            "classified": 1,
            "kind": "idea",
            "priority": "med",
            "summary": "an idea",
            "raw_text": "an idea",
            "mentions": None,
            "done": 0,
            "created_at": "2026-05-23T10:00:00.000Z",
        }
        base.update(overrides)
        return base

    def test_empty_returns_nothing_yet(self):
        from solo.commands import format_all

        assert format_all([]) == "nothing yet"

    def test_header_omits_done_count_when_zero(self):
        from solo.commands import format_all

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        out = format_all([self._row(id=1)], now=now)
        assert "All (1):" in out

    def test_header_shows_done_count_when_nonzero(self):
        from solo.commands import format_all

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        rows = [
            self._row(id=1),
            self._row(id=2, done=1, summary="finished"),
            self._row(id=3, done=1, summary="also finished"),
        ]
        out = format_all(rows, now=now)
        assert "All (3, 2 done):" in out

    def test_done_rows_render_with_check_prefix(self):
        from solo.commands import format_all

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        rows = [self._row(id=12, summary="Hofstadter on strange loops",
                          done=1, kind="note",
                          created_at="2026-04-26T10:00:00.000Z")]
        out = format_all(rows, now=now)
        assert "✅ 12 Hofstadter on strange loops [done 4w ago]" in out

    def test_done_rows_grouped_with_their_kind(self):
        from solo.commands import format_all

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        rows = [
            self._row(id=1, kind="idea", summary="active idea"),
            self._row(id=2, kind="idea", summary="done idea", done=1),
        ]
        out = format_all(rows, now=now)
        # Both appear under 💡 ideas, active first then done
        ideas_section = out.split("💡 ideas")[1].split("\n\n")[0]
        assert "· 1" in ideas_section
        assert "✅ 2" in ideas_section
```

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/test_commands.py::TestFormatAll -v`
Expected: ImportError on `format_all`.

- [ ] **Step 4: Implement `format_all`**

Append to `src/solo/commands.py`:

```python
def _format_all_row(row: dict, *, now: datetime | None) -> str:
    age = _age(row["created_at"], now=now)
    if row.get("done"):
        prefix = "✅"
        summary_or_raw = row.get("summary") or row.get("raw_text")
        return f"  {prefix} {row['id']} {summary_or_raw} [done {age} ago]"
    return _format_list_row(row, now=now)


def format_all(rows: list[dict], *, now: datetime | None = None) -> str:
    if not rows:
        return "nothing yet"

    done_count = sum(1 for r in rows if r.get("done"))
    if done_count:
        header = f"All ({len(rows)}, {done_count} done):"
    else:
        header = f"All ({len(rows)}):"

    buckets: dict[str | None, list[dict]] = {k: [] for k, _ in _LIST_KIND_ORDER}
    buckets[None] = []
    for row in rows:
        if row.get("classified") and row.get("kind") in buckets:
            buckets[row["kind"]].append(row)
        else:
            buckets[None].append(row)

    # Within each section, active rows first, then done rows.
    for kind in buckets:
        buckets[kind].sort(key=lambda r: (r.get("done", 0), -r["id"]))

    out: list[str] = [header]
    for kind, section_header in _LIST_KIND_ORDER:
        items = buckets[kind]
        if not items:
            continue
        out.append("")
        out.append(section_header)
        for r in items:
            out.append(_format_all_row(r, now=now))
    if buckets[None]:
        out.append("")
        out.append(_UNCLASSIFIED_HEADER)
        for r in buckets[None]:
            out.append(_format_all_row(r, now=now))
    return "\n".join(out)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/test_commands.py::TestFormatAll -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): replace format_log with format_all (includes done items)"
```

---

## Task 10: `handle_top3` updated for new format signature + aging fetch

**Files:**
- Modify: `src/solo/commands.py`
- Modify: `tests/test_commands.py`

`handle_top3` currently calls `format_top3(top)`. The new signature is `format_top3(top, *, aging, now)`. The handler needs to fetch the aging items.

- [ ] **Step 1: Update the existing `TestHandleTop3` tests**

In `tests/test_commands.py`, the assertions inside `TestHandleTop3` need to match the new format. Open the file and replace these expected-substring asserts:

In `test_drains_backlog_then_replies`, change:
```python
        assert "Top 3:" in msg._replied
        assert "[high · soft_task] positioning" in msg._replied
        assert "[medium · idea] explore embeddings" in msg._replied
```
to:
```python
        assert "Top 3 for today:" in msg._replied
        assert "1️⃣ 💡 positioning" in msg._replied
        assert "2️⃣ 💡 explore embeddings" in msg._replied
```

(Order in the reply may flip — high beats medium. Adjust if needed after running.)

- [ ] **Step 2: Update `handle_top3` to compute and pass aging**

Replace `handle_top3` in `src/solo/commands.py`:

```python
async def handle_top3(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    llm: SupportsStructured,
    model: str = DEFAULT_MODEL,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        await classify_pending(conn, llm, model=model)
        rows = db.fetch_classified(conn, kinds=["soft_task", "idea"])
        top = rank.top3(rows)
        top_ids = {r["id"] for r in top}
        aging = [
            r for r in rows
            if r["id"] not in top_ids and _is_stale(r["created_at"])
        ]
        await update.message.reply_text(format_top3(top, aging=aging))
    except Exception:
        logger.exception("/top3 failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text(_TOP3_FAILED)
        except Exception:
            logger.exception("/top3 fallback reply also failed")
```

- [ ] **Step 3: Run tests to verify pass**

Run: `uv run pytest tests/test_commands.py::TestHandleTop3 -v`
Expected: green. If a test fails on order/format mismatch, adjust the expected substring.

- [ ] **Step 4: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): handle_top3 surfaces aging items in reply"
```

---

## Task 11: `handle_list` + `handle_all` handlers (delete `handle_log`)

**Files:**
- Modify: `src/solo/commands.py`
- Modify: `tests/test_commands.py`

- [ ] **Step 1: Delete `handle_log` and its tests**

In `src/solo/commands.py`, remove the `handle_log` function (the body, the docstring, everything).
In `tests/test_commands.py`, remove the entire `class TestHandleLog:` block.

- [ ] **Step 2: Write failing tests**

Append to `tests/test_commands.py`:

```python
class TestHandleList:
    @pytest.mark.asyncio
    async def test_groups_active_items_by_kind(self, db_conn):
        from solo.commands import handle_list
        from solo.db import apply_classification, insert_entry

        a = insert_entry(db_conn, "i1", 1, 1, "{}")
        b = insert_entry(db_conn, "s1", 1, 2, "{}")
        apply_classification(db_conn, a, "idea", "i1", "high")
        apply_classification(db_conn, b, "soft_task", "s1", "low")

        msg = FakeMessage("/list")
        update = FakeUpdate(msg)
        await handle_list(update, FakeContext(), conn=db_conn)

        assert "Active (2):" in msg._replied
        assert "💡 ideas" in msg._replied
        assert "🌀 soft_tasks" in msg._replied
        assert "i1" in msg._replied
        assert "s1" in msg._replied

    @pytest.mark.asyncio
    async def test_excludes_done_rows(self, db_conn):
        from solo.commands import handle_list
        from solo.db import apply_classification, insert_entry, mark_done

        a = insert_entry(db_conn, "active", 1, 1, "{}")
        b = insert_entry(db_conn, "finished", 1, 2, "{}")
        apply_classification(db_conn, a, "idea", "active", "low")
        apply_classification(db_conn, b, "idea", "finished", "low")
        mark_done(db_conn, b)

        msg = FakeMessage("/list")
        update = FakeUpdate(msg)
        await handle_list(update, FakeContext(), conn=db_conn)

        assert "Active (1):" in msg._replied
        assert "active" in msg._replied
        assert "finished" not in msg._replied

    @pytest.mark.asyncio
    async def test_empty_returns_nothing_active(self, db_conn):
        from solo.commands import handle_list

        msg = FakeMessage("/list")
        update = FakeUpdate(msg)
        await handle_list(update, FakeContext(), conn=db_conn)
        assert msg._replied == "nothing active"

    @pytest.mark.asyncio
    async def test_rejects_disallowed_chat(self, db_conn):
        from solo.commands import handle_list

        msg = FakeMessage("/list", chat_id=666)
        update = FakeUpdate(msg)
        await handle_list(update, FakeContext(), conn=db_conn, allowed_chats={123})
        assert msg._replied is None


class TestHandleAll:
    @pytest.mark.asyncio
    async def test_includes_done_rows(self, db_conn):
        from solo.commands import handle_all
        from solo.db import apply_classification, insert_entry, mark_done

        a = insert_entry(db_conn, "active idea", 1, 1, "{}")
        b = insert_entry(db_conn, "done idea", 1, 2, "{}")
        apply_classification(db_conn, a, "idea", "active idea", "low")
        apply_classification(db_conn, b, "idea", "done idea", "low")
        mark_done(db_conn, b)

        msg = FakeMessage("/all")
        update = FakeUpdate(msg)
        await handle_all(update, FakeContext(), conn=db_conn)

        assert "All (2, 1 done):" in msg._replied
        assert "active idea" in msg._replied
        assert "done idea" in msg._replied
        assert "✅" in msg._replied

    @pytest.mark.asyncio
    async def test_empty_returns_nothing_yet(self, db_conn):
        from solo.commands import handle_all

        msg = FakeMessage("/all")
        update = FakeUpdate(msg)
        await handle_all(update, FakeContext(), conn=db_conn)
        assert msg._replied == "nothing yet"

    @pytest.mark.asyncio
    async def test_rejects_disallowed_chat(self, db_conn):
        from solo.commands import handle_all

        msg = FakeMessage("/all", chat_id=666)
        update = FakeUpdate(msg)
        await handle_all(update, FakeContext(), conn=db_conn, allowed_chats={123})
        assert msg._replied is None
```

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/test_commands.py::TestHandleList tests/test_commands.py::TestHandleAll -v`
Expected: failures — `handle_list` and `handle_all` don't exist.

- [ ] **Step 4: Implement the handlers**

Append to `src/solo/commands.py`:

```python
_LIST_LIMIT = 200  # generous; /list and /all both subject to Telegram's 4096-char reply cap.
_LIST_FAILED = "sorry, /list failed — check logs"
_ALL_FAILED = "sorry, /all failed — check logs"


async def handle_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        rows = db.fetch_active(conn, limit=_LIST_LIMIT)
        await update.message.reply_text(format_list(rows))
    except Exception:
        logger.exception("/list failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text(_LIST_FAILED)
        except Exception:
            logger.exception("/list fallback reply also failed")


async def handle_all(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        cursor = conn.execute(
            "SELECT * FROM entries ORDER BY created_at DESC, id DESC LIMIT ?",
            (_LIST_LIMIT,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        await update.message.reply_text(format_all(rows))
    except Exception:
        logger.exception("/all failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text(_ALL_FAILED)
        except Exception:
            logger.exception("/all fallback reply also failed")
```

- [ ] **Step 5: Run tests to verify pass**

Run: `uv run pytest tests/test_commands.py::TestHandleList tests/test_commands.py::TestHandleAll -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): replace /log handler with /list and /all"
```

---

## Task 12: `handle_drop` + `handle_done` (id-list write commands)

**Files:**
- Modify: `src/solo/commands.py`
- Modify: `tests/test_commands.py`

These two have nearly identical arg-parsing shape; ship them together.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_commands.py`. Note: `python-telegram-bot` populates `context.args` from the message text; the existing `FakeContext` doesn't. We extend it:

```python
class FakeContextWithArgs:
    def __init__(self, args):
        self.args = list(args)


class TestHandleDrop:
    @pytest.mark.asyncio
    async def test_deletes_one_id(self, db_conn):
        from solo.commands import handle_drop
        from solo.db import insert_entry

        rid = insert_entry(db_conn, "kill me", 1, 1, "{}")
        msg = FakeMessage(f"/drop {rid}")
        update = FakeUpdate(msg)
        await handle_drop(update, FakeContextWithArgs([str(rid)]), conn=db_conn)

        assert msg._replied == f"dropped 1: {rid}"
        row = db_conn.execute("SELECT id FROM entries WHERE id=?", (rid,)).fetchone()
        assert row is None

    @pytest.mark.asyncio
    async def test_deletes_multiple_ids(self, db_conn):
        from solo.commands import handle_drop
        from solo.db import insert_entry

        a = insert_entry(db_conn, "a", 1, 1, "{}")
        b = insert_entry(db_conn, "b", 1, 2, "{}")
        msg = FakeMessage(f"/drop {a} {b}")
        update = FakeUpdate(msg)
        await handle_drop(update, FakeContextWithArgs([str(a), str(b)]), conn=db_conn)

        assert msg._replied == f"dropped 2: {a}, {b}"

    @pytest.mark.asyncio
    async def test_no_args_returns_usage(self, db_conn):
        from solo.commands import handle_drop

        msg = FakeMessage("/drop")
        update = FakeUpdate(msg)
        await handle_drop(update, FakeContextWithArgs([]), conn=db_conn)
        assert msg._replied == "usage: /drop <id> [<id>...]"

    @pytest.mark.asyncio
    async def test_unknown_id_reports_no_op(self, db_conn):
        from solo.commands import handle_drop

        msg = FakeMessage("/drop 99999")
        update = FakeUpdate(msg)
        await handle_drop(update, FakeContextWithArgs(["99999"]), conn=db_conn)
        assert msg._replied == "nothing dropped (ids not found: 99999)"

    @pytest.mark.asyncio
    async def test_non_int_args_are_skipped(self, db_conn):
        from solo.commands import handle_drop
        from solo.db import insert_entry

        rid = insert_entry(db_conn, "x", 1, 1, "{}")
        msg = FakeMessage(f"/drop {rid} bogus")
        update = FakeUpdate(msg)
        await handle_drop(update, FakeContextWithArgs([str(rid), "bogus"]), conn=db_conn)
        assert msg._replied == f"dropped 1: {rid}"


class TestHandleDone:
    @pytest.mark.asyncio
    async def test_marks_one_id_done(self, db_conn):
        from solo.commands import handle_done
        from solo.db import insert_entry

        rid = insert_entry(db_conn, "x", 1, 1, "{}")
        msg = FakeMessage(f"/done {rid}")
        update = FakeUpdate(msg)
        await handle_done(update, FakeContextWithArgs([str(rid)]), conn=db_conn)

        assert msg._replied == f"done 1: {rid}"
        d = db_conn.execute("SELECT done FROM entries WHERE id=?", (rid,)).fetchone()[0]
        assert d == 1

    @pytest.mark.asyncio
    async def test_no_args_returns_usage(self, db_conn):
        from solo.commands import handle_done

        msg = FakeMessage("/done")
        update = FakeUpdate(msg)
        await handle_done(update, FakeContextWithArgs([]), conn=db_conn)
        assert msg._replied == "usage: /done <id> [<id>...]"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_commands.py::TestHandleDrop tests/test_commands.py::TestHandleDone -v`
Expected: ImportError or handler-missing errors.

- [ ] **Step 3: Implement the handlers**

Append to `src/solo/commands.py`:

```python
def _parse_int_args(args: list[str]) -> tuple[list[int], list[str]]:
    """Returns (valid_ids, skipped_args)."""
    valid: list[int] = []
    skipped: list[str] = []
    for a in args:
        try:
            valid.append(int(a))
        except ValueError:
            skipped.append(a)
    return valid, skipped


async def handle_drop(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        ids, skipped = _parse_int_args(getattr(context, "args", None) or [])
        if skipped:
            logger.warning("/drop ignored non-int args: %s", skipped)
        if not ids:
            await update.message.reply_text("usage: /drop <id> [<id>...]")
            return

        dropped: list[int] = []
        not_found: list[int] = []
        for entry_id in ids:
            if db.delete_entry(conn, entry_id):
                dropped.append(entry_id)
            else:
                not_found.append(entry_id)

        if dropped:
            await update.message.reply_text(
                f"dropped {len(dropped)}: " + ", ".join(str(i) for i in dropped)
            )
        else:
            await update.message.reply_text(
                "nothing dropped (ids not found: "
                + ", ".join(str(i) for i in not_found)
                + ")"
            )
    except Exception:
        logger.exception("/drop failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text("sorry, /drop failed — check logs")
        except Exception:
            logger.exception("/drop fallback reply also failed")


async def handle_done(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        ids, skipped = _parse_int_args(getattr(context, "args", None) or [])
        if skipped:
            logger.warning("/done ignored non-int args: %s", skipped)
        if not ids:
            await update.message.reply_text("usage: /done <id> [<id>...]")
            return

        marked: list[int] = []
        not_found: list[int] = []
        for entry_id in ids:
            if db.mark_done(conn, entry_id):
                marked.append(entry_id)
            else:
                not_found.append(entry_id)

        if marked:
            await update.message.reply_text(
                f"done {len(marked)}: " + ", ".join(str(i) for i in marked)
            )
        else:
            await update.message.reply_text(
                "nothing changed (ids not found: "
                + ", ".join(str(i) for i in not_found)
                + ")"
            )
    except Exception:
        logger.exception("/done failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text("sorry, /done failed — check logs")
        except Exception:
            logger.exception("/done fallback reply also failed")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_commands.py::TestHandleDrop tests/test_commands.py::TestHandleDone -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): add /drop (hard delete) and /done handlers"
```

---

## Task 13: `handle_redo`

**Files:**
- Modify: `src/solo/commands.py`
- Modify: `tests/test_commands.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_commands.py`:

```python
class TestHandleRedo:
    @pytest.mark.asyncio
    async def test_resets_classified_row_for_reclassification(self, db_conn):
        from solo.commands import handle_redo
        from solo.db import apply_classification, insert_entry

        rid = insert_entry(db_conn, "x", 1, 1, "{}")
        apply_classification(db_conn, rid, "idea", "wrong summary", "high")

        msg = FakeMessage(f"/redo {rid}")
        update = FakeUpdate(msg)
        await handle_redo(update, FakeContextWithArgs([str(rid)]), conn=db_conn)

        assert msg._replied == f"requeued {rid} for next /top3"
        row = db_conn.execute(
            "SELECT classified, kind, summary, priority FROM entries WHERE id=?",
            (rid,),
        ).fetchone()
        assert row[0] == 0
        assert row[1] is None
        assert row[2] is None
        assert row[3] is None

    @pytest.mark.asyncio
    async def test_no_args_returns_usage(self, db_conn):
        from solo.commands import handle_redo

        msg = FakeMessage("/redo")
        update = FakeUpdate(msg)
        await handle_redo(update, FakeContextWithArgs([]), conn=db_conn)
        assert msg._replied == "usage: /redo <id>"

    @pytest.mark.asyncio
    async def test_multiple_args_returns_usage(self, db_conn):
        from solo.commands import handle_redo

        msg = FakeMessage("/redo 1 2")
        update = FakeUpdate(msg)
        await handle_redo(update, FakeContextWithArgs(["1", "2"]), conn=db_conn)
        assert msg._replied == "usage: /redo <id>"

    @pytest.mark.asyncio
    async def test_unknown_id_replies_not_found(self, db_conn):
        from solo.commands import handle_redo

        msg = FakeMessage("/redo 9999")
        update = FakeUpdate(msg)
        await handle_redo(update, FakeContextWithArgs(["9999"]), conn=db_conn)
        assert msg._replied == "id 9999 not found"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_commands.py::TestHandleRedo -v`
Expected: failures.

- [ ] **Step 3: Implement the handler**

Append to `src/solo/commands.py`:

```python
async def handle_redo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        args = getattr(context, "args", None) or []
        if len(args) != 1:
            await update.message.reply_text("usage: /redo <id>")
            return
        try:
            entry_id = int(args[0])
        except ValueError:
            await update.message.reply_text("usage: /redo <id>")
            return

        if db.reset_for_reclassification(conn, entry_id):
            await update.message.reply_text(
                f"requeued {entry_id} for next /top3"
            )
        else:
            await update.message.reply_text(f"id {entry_id} not found")
    except Exception:
        logger.exception("/redo failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text("sorry, /redo failed — check logs")
        except Exception:
            logger.exception("/redo fallback reply also failed")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_commands.py::TestHandleRedo -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): add /redo handler for re-classification"
```

---

## Task 14: `handle_help`

**Files:**
- Modify: `src/solo/commands.py`
- Modify: `tests/test_commands.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_commands.py`:

```python
class TestHandleHelp:
    @pytest.mark.asyncio
    async def test_replies_with_help_text(self, db_conn):
        from solo.commands import handle_help

        msg = FakeMessage("/help")
        update = FakeUpdate(msg)
        await handle_help(update, FakeContext())

        assert msg._replied is not None
        for cmd in ("/top3", "/list", "/all", "/drop", "/done", "/redo", "/help"):
            assert cmd in msg._replied
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_commands.py::TestHandleHelp -v`
Expected: ImportError.

- [ ] **Step 3: Implement the handler**

Append to `src/solo/commands.py`:

```python
_HELP_TEXT = (
    "Commands:\n"
    "/top3  — your top 3 right now\n"
    "/list  — all active items, with IDs\n"
    "/all   — everything (active + done)\n"
    "/drop <id> [<id>...]  — hard delete\n"
    "/done <id> [<id>...]  — mark done\n"
    "/redo <id>            — re-classify\n"
    "/help  — this message"
)


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.message.reply_text(_HELP_TEXT)
    except Exception:
        logger.exception("/help failed")
```

- [ ] **Step 4: Run test to verify pass**

Run: `uv run pytest tests/test_commands.py::TestHandleHelp -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): add /help handler"
```

---

## Task 15: Wire the new commands into `bot.main()`

**Files:**
- Modify: `src/solo/bot.py`

Remove the `/log` registration. Add `/list`, `/all`, `/drop`, `/done`, `/redo`, `/help`.

- [ ] **Step 1: Update `bot.py`**

Replace the imports and handler registration block in `src/solo/bot.py`. Open the file; the import line and `main()` registration section both change.

Imports — replace `from solo.commands import handle_log, handle_top3` with:

```python
from solo.commands import (
    handle_all,
    handle_done,
    handle_drop,
    handle_help,
    handle_list,
    handle_redo,
    handle_top3,
)
```

In `main()`, replace the closures + `add_handler` block:

```python
    async def _capture(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_message(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _top3(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_top3(
            update, ctx, conn=conn, llm=llm, model=model,
            allowed_chats=allowed_chats,
        )

    async def _list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_list(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _all(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_all(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _drop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_drop(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_done(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _redo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_redo(update, ctx, conn=conn, allowed_chats=allowed_chats)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _capture))
    app.add_handler(CommandHandler("top3", _top3))
    app.add_handler(CommandHandler("list", _list))
    app.add_handler(CommandHandler("all", _all))
    app.add_handler(CommandHandler("drop", _drop))
    app.add_handler(CommandHandler("done", _done))
    app.add_handler(CommandHandler("redo", _redo))
    app.add_handler(CommandHandler("help", handle_help))
```

- [ ] **Step 2: Verify slice-1 tests still pass**

Run: `uv run pytest tests/test_bot.py -v`
Expected: all green.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -v 2>&1 | tail -10`
Expected: all green (no regression).

- [ ] **Step 4: Commit**

```bash
git add src/solo/bot.py
git commit -m "feat(bot): register /list /all /drop /done /redo /help; remove /log"
```

---

## Task 16: ADR-0007 + ADR-0008

**Files:**
- Create: `docs/decisions/0007-drop-is-hard-delete.md`
- Create: `docs/decisions/0008-mention-extraction-is-regex.md`
- Modify: `docs/decisions/README.md`

- [ ] **Step 1: Write ADR-0007**

`docs/decisions/0007-drop-is-hard-delete.md`:

```markdown
# 0007 — `/drop` is a hard delete; `/done` is the soft-state half

**Status:** accepted
**Date:** 2026-05-24

## Context

V0.1 introduces mutation commands. Two reasonable shapes for "remove from active view":

1. **Hard delete on `/drop`; soft `done` flag on `/done`.** Two states the user explicitly chooses between. Smaller schema (one boolean).
2. **Soft `status` column with values `active | done | dropped`.** Symmetric three-state lifecycle; misclicks recoverable.

## Decision

Shape 1. `/drop` is a hard `DELETE FROM entries`. `/done` sets `done = 1` and the row stays in `/all`.

The user explicitly chose hard delete during brainstorming, after seeing both options laid out.

## Consequences

**Easier:**
- Schema is one boolean (`done`) instead of a three-valued enum.
- The user's mental model is binary: "useful → keep; noise → delete forever."
- `/all` stays focused on "things I actually captured" rather than including a `dropped` graveyard.

**Harder:**
- Misclicks on `/drop` are unrecoverable. There is no `/undrop`.
- An entry deleted by `/drop` does not appear in `llm_calls` — wait, it does: trace rows are independent. So cost/eval history survives even when entries don't.
- If the user later wants "things I considered but dropped," they'd need a schema change (and historical data is gone).

## Alternatives considered

- **Soft `status` column** — rejected per D1 in the slice-6 spec. Reconsider if the user starts wanting an `/undrop`.
- **Two-stage drop (`/drop` → "are you sure?" → `/confirm`)** — rejected as Telegram-UX clutter. The user is the only person who can use the bot anyway (allow-list).
```

- [ ] **Step 2: Write ADR-0008**

`docs/decisions/0008-mention-extraction-is-regex.md`:

```markdown
# 0008 — `@name` extraction is a regex at insert time, not an LLM-inferred field

**Status:** accepted
**Date:** 2026-05-24

## Context

V0.1 surfaces a `👥 @name` marker in `/top3` and `/list`. Three ways to source the data:

1. **LLM-inferred field on `ClassifyResult`** — add `source: self | external` or similar; the model reads context and tags. Magical, requires schema bump on entries + prompt update + eval relabeling.
2. **Regex at insert time** — extract `@\w+` from `raw_text`, store as CSV in a `mentions` column.
3. **Hybrid** — regex for the @name path, LLM-inferred for the "external request without a name" path.

## Decision

Shape 2 only. `solo.mentions.extract` runs at `insert_entry` time and writes a CSV to `mentions`. The classifier is unchanged. No LLM cost added.

The LLM-inferred external-ask slot (rendered as 🔔) is **reserved visually** in the format but not implemented in this slice. Re-litigate if nameless asks become a real pattern.

## Consequences

**Easier:**
- Zero new LLM cost; zero classifier prompt churn; zero eval relabeling.
- Deterministic and instant — the marker appears on the row immediately, before the classifier has run.
- The data path is independent of the classifier: a row with no kind/summary still has the right marker.

**Harder:**
- Entries that imply a person without explicitly @-naming them (e.g. "boss wants the deck by Friday") get the default 💡 marker. The user has to type `@boss` themselves to surface the marker.
- Convention drift: if the user starts using `#tag` or `+person`, this slice silently ignores it.
- Existing rows (captured before this slice) have NULL `mentions` — they render as 💡 forever unless re-inserted.

## Alternatives considered

- **LLM-inferred `source` field** — rejected for V0.1; deferred. Reconsider after a week of real use shows whether nameless asks are common enough to justify the cost.
- **Hybrid** — rejected; adds complexity now for unclear payoff. Easier to add the LLM path later on top of the regex path than the reverse.
```

- [ ] **Step 3: Update ADR index**

In `docs/decisions/README.md`, append:

```markdown
- [0007 — `/drop` is a hard delete; `/done` is the soft-state half](0007-drop-is-hard-delete.md)
- [0008 — `@name` extraction is a regex at insert time, not an LLM-inferred field](0008-mention-extraction-is-regex.md)
```

- [ ] **Step 4: Commit**

```bash
git add docs/decisions/0007-drop-is-hard-delete.md docs/decisions/0008-mention-extraction-is-regex.md docs/decisions/README.md
git commit -m "docs(decisions): ADR-0007 (drop=hard) and ADR-0008 (mentions=regex)"
```

---

## Task 17: HTML walkthrough + status.md

**Files:**
- Modify: `docs/walkthrough.html`
- Modify: `docs/status.md`

- [ ] **Step 1: Update walkthrough.html**

In `docs/walkthrough.html`:

1. Nav-bar: add a new line for "Slice 6 — Admin surface" between slice 5 and the abstractions section. Bump abstractions/concepts/decisions/status section numbers by 1.
2. Top meta pills: change `V0 complete — all 5 slices shipped` to `V0.1 complete — admin surface + visual refresh`; keep `V1 surface (/expand) next`.
3. Add a new slice 6 card (green/done) with:
   - The new `/top3` sample output (terse + emoji + aging).
   - A short list of new commands.
   - Links to ADR-0007 and ADR-0008 and the spec.
4. Update Abstractions grid: add a `solo.mentions` card.
5. Update ADRs grid: add cards for 0007 and 0008.
6. Update Status section bullets: add slice 6 as done; keep V1 as next.
7. Bump "Last regen" date to 2026-05-24.

- [ ] **Step 2: Update status.md**

Rewrite `docs/status.md` so:
- `Last updated` = `2026-05-24 — by Claude Code (Opus 4.7)`.
- `Current state` reflects V0.1 done: admin surface (list/all/drop/done/redo/help), `done` + `mentions` columns, terse visual format.
- `Done in slice 6` lists: `src/solo/mentions.py`, `db` helpers (mark_done, delete_entry, reset_for_reclassification, fetch_active, fetch_classified filter), `commands` rewrite + new handlers, ADR-0007 + ADR-0008.
- `What's next` numbered list: marks slice 6 done with strikethrough; V1 (`/expand`) remains the next item.
- `Pending manual verification` adds: full sweep of new commands against a live Telegram chat.

- [ ] **Step 3: Sanity-check the walkthrough**

Run: `open docs/walkthrough.html`
Expected: slice 6 card green, abstractions + ADR grids include the new entries, status section shows V0.1 complete.

- [ ] **Step 4: Commit**

```bash
git add docs/walkthrough.html docs/status.md
git commit -m "docs: flip slice 6 to done; refresh walkthrough + status"
```

---

## Task 18: Verification cycle + push

**Files:** none

- [ ] **Step 1: Full pytest**

Run: `uv run pytest 2>&1 | tail -10`
Expected: all green (count up by ~25 from the new tests across mentions, db helpers, formatters, handlers).

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`
Expected: clean.

- [ ] **Step 3: Format-check slice-6 files**

Run:
```bash
uv run ruff format --check src/solo/mentions.py src/solo/commands.py src/solo/db.py src/solo/bot.py tests/test_mentions.py tests/test_commands.py tests/test_db.py
```

If only slice-6 files diverge, format them: `uv run ruff format <those files>` and commit as a `style:` commit. If the diff also touches slice-2 files (e.g. record_call's tuple), exclude those — stay in scope.

- [ ] **Step 4: Push**

Run: `git push origin main`
Expected: clean push.

- [ ] **Step 5: Run both reviewers**

`solo-reviewer` agent + generic code-reviewer agent on the range `0fc91f1..HEAD`. Address any blockers; re-run pytest after fixes; re-push.

---

## Spec coverage check

| Spec section | Tasks |
|---|---|
| §3 schema bump (`done`, `mentions`) | Task 2 |
| §4 `/top3` (existing, refreshed) | Tasks 7, 10 |
| §4 `/list` | Tasks 8, 11 |
| §4 `/all` (rename) | Tasks 9, 11 |
| §4 `/drop` | Task 12 |
| §4 `/done` | Task 12 |
| §4 `/redo` | Task 13 |
| §4 `/help` | Task 14 |
| §5 visual format (top3 terse + aging) | Task 7 |
| §5 visual format (list + all + sections) | Tasks 8, 9 |
| §5 `_age`, `_marker`, `_is_stale` helpers | Task 6 (+ 7 for `_is_stale`) |
| §6 `solo.mentions` module | Task 1 |
| §6 `insert_entry` mentions population | Task 3 |
| §6 DB helpers | Tasks 4, 5 |
| §6 bot wiring | Task 15 |
| §7 error handling (try/except wrappers, fallback replies) | Tasks 11–14 |
| §8 test plan | Tasks 1–14 |
| §9 ADR-0007 + ADR-0008 | Task 16 |
| §9 walkthrough + status updates | Task 17 |

No gaps.
