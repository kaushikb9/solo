# Domain flex for `/top` — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `domain` axis (`work` / `life` / `either`) to entries so `/top` can flex by time-of-week (work focus on weekdays, life focus Fri eve + Sat/Sun) with a manual `/top work|life|all` override.

**Architecture:** Hybrid signal — `#work`/`#life` tags parsed at capture time (parallel to mentions), classifier infers `domain` for untagged rows, `apply_classification` preserves tag-set values via `COALESCE(domain, ?)`. `/top` resolves a mode from args or local time, applies a pure filter in `rank.py`, and renders a lens-aware header. No backfill — pre-feature NULL rows surface as `either`.

**Tech Stack:** Python 3.12, SQLite stdlib, Pydantic, pytest, ruff, `python-telegram-bot`, `zoneinfo` (stdlib).

**Spec:** `docs/superpowers/specs/2026-05-26-domain-flex-design.md`.

---

## File structure

### New files
| Path | Responsibility |
|---|---|
| `src/solo/tags.py` | Pure: extract `#work`/`#life` from raw text. First match wins, case-insensitive. |
| `src/solo/timeflex.py` | Pure: `auto_mode(now_local)` returns `'work'` or `'life'` based on Fri-eve + weekend rule. |
| `tests/test_tags.py` | Unit tests for `tags.extract`. |
| `tests/test_timeflex.py` | Unit tests for `auto_mode`. |
| `docs/decisions/0009-domain-axis.md` | ADR for D1–D8 from the spec. |

### Modified files
| Path | Change |
|---|---|
| `src/solo/db.py` | `_SCHEMA` adds `domain TEXT`; `_migrate_entries` adds idempotent column add; `insert_entry` writes `domain` from `tags.extract`; `apply_classification` gains `domain` param and uses `COALESCE`. |
| `src/solo/classifier.py` | `ClassifyResult` gains `domain` field; `classify_pending` passes `result.domain` into `apply_classification`. |
| `src/solo/prompts/classifier.md` | Adds the domain section. |
| `src/solo/rank.py` | Adds `filter_by_mode(rows, mode)`; `top()` unchanged. |
| `src/solo/commands.py` | `handle_top` parses args + computes mode + applies filter; `format_top` gains `mode` + `auto`; `_HELP_TEXT` updated; new `_TOP_USAGE` constant. |
| `tests/test_db.py` | Tests for `domain` migration + `apply_classification` COALESCE behavior. |
| `tests/test_classifier.py` | Tests `ClassifyResult` accepts `domain`; `classify_pending` writes domain through; tag wins over LLM. |
| `tests/test_rank.py` | Tests for `filter_by_mode`. |
| `tests/test_commands.py` | Tests for `handle_top` mode resolution + `format_top` headers. |
| `tests/test_prompts.py` | Smoke test that `classifier.md` mentions the domain options. |
| `.env.example` | Add `SOLO_TIMEZONE=Asia/Kolkata`. |
| `README.md` | Mention env var + updated `/top` description. |
| `AGENTS.md` | One-liner on the `domain` axis. |
| `docs/status.md` | Updated `/top` description in "Commands available". |
| `docs/architecture.md` | Updated `/top` description in §1 and §9. |

---

## Task 1: `tags.py` module

**Files:**
- Create: `src/solo/tags.py`
- Test: `tests/test_tags.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tags.py


def test_extract_returns_none_when_no_tag():
    from solo.tags import extract

    assert extract("") is None
    assert extract("just a thought") is None
    assert extract("#worker is not a tag") is None  # \b boundary
    assert extract("ping @alice") is None


def test_extract_work_tag():
    from solo.tags import extract

    assert extract("ship the redesign #work") == "work"
    assert extract("#work ship the redesign") == "work"


def test_extract_life_tag():
    from solo.tags import extract

    assert extract("dentist on tuesday #life") == "life"


def test_extract_is_case_insensitive():
    from solo.tags import extract

    assert extract("#WORK things") == "work"
    assert extract("#Life balance") == "life"


def test_extract_first_match_wins_on_conflict():
    from solo.tags import extract

    assert extract("#work no actually #life") == "work"
    assert extract("#life no actually #work") == "life"


def test_extract_word_boundary():
    # #worker, #lifestyle should NOT match — \b boundary after the keyword.
    from solo.tags import extract

    assert extract("#worker bee") is None
    assert extract("#lifestyle blog") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tags.py -v`
Expected: 6 failures with `ModuleNotFoundError: No module named 'solo.tags'`.

- [ ] **Step 3: Implement `tags.py`**

```python
# src/solo/tags.py
"""Extract a domain tag (#work / #life) from raw entry text.

Pure module. Used at insert_entry time to populate the `domain` column
when the user has tagged their thought explicitly. The classifier
infers domain for untagged entries.
"""

import re

_TAG_RE = re.compile(r"(?i)#(work|life)\b")


def extract(raw_text: str) -> str | None:
    """Return 'work' or 'life' on first match, else None.

    Case-insensitive. First match wins on conflict.
    """
    m = _TAG_RE.search(raw_text)
    return m.group(1).lower() if m else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tags.py -v`
Expected: all 6 pass.

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/solo/tags.py tests/test_tags.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/solo/tags.py tests/test_tags.py
git commit -m "feat(tags): extract #work / #life from raw text"
```

---

## Task 2: Add `domain` column to `entries`

**Files:**
- Modify: `src/solo/db.py` (`_SCHEMA`, `_migrate_entries`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing migration tests**

Append to `tests/test_db.py`:

```python
def test_domain_column_present_on_fresh_db(tmp_path):
    from solo.db import get_connection

    conn = get_connection(str(tmp_path / "fresh.db"))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
    assert "domain" in cols
    conn.close()


def test_domain_migration_is_idempotent(tmp_path):
    """Pre-domain DBs get the column added on first open; subsequent
    opens are no-ops."""
    import sqlite3

    db_path = tmp_path / "legacy.db"
    # Build a legacy schema without `domain`.
    legacy = sqlite3.connect(str(db_path))
    legacy.executescript(
        """
        CREATE TABLE entries (
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
    )
    legacy.execute(
        "INSERT INTO entries (raw_text, telegram_chat_id, telegram_message_id, "
        "telegram_message_json) VALUES (?, ?, ?, ?)",
        ("legacy row", 1, 1, "{}"),
    )
    legacy.commit()
    legacy.close()

    from solo.db import get_connection

    # First open: column added.
    conn = get_connection(str(db_path))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
    assert "domain" in cols
    # Legacy row's domain is NULL.
    row = conn.execute("SELECT domain FROM entries WHERE raw_text = 'legacy row'").fetchone()
    assert row[0] is None
    conn.close()

    # Second open: no-op (no exception raised).
    conn2 = get_connection(str(db_path))
    conn2.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py::test_domain_column_present_on_fresh_db tests/test_db.py::test_domain_migration_is_idempotent -v`
Expected: both fail with `AssertionError: assert 'domain' in {...}`.

- [ ] **Step 3: Add column to `_SCHEMA`**

In `src/solo/db.py`, the `_SCHEMA` string ends with:

```python
    mentions TEXT
);
"""
```

Change to:

```python
    mentions TEXT,
    domain TEXT
);
"""
```

- [ ] **Step 4: Add migration entry in `_migrate_entries`**

In the `additions` tuple inside `_migrate_entries`, append:

```python
        ("domain", "ALTER TABLE entries ADD COLUMN domain TEXT"),
```

The full tuple becomes:

```python
    additions = (
        ("kind", "ALTER TABLE entries ADD COLUMN kind TEXT"),
        ("summary", "ALTER TABLE entries ADD COLUMN summary TEXT"),
        ("priority", "ALTER TABLE entries ADD COLUMN priority TEXT"),
        (
            "classification_attempts",
            "ALTER TABLE entries ADD COLUMN classification_attempts INTEGER NOT NULL DEFAULT 0",
        ),
        ("done", "ALTER TABLE entries ADD COLUMN done INTEGER NOT NULL DEFAULT 0"),
        ("mentions", "ALTER TABLE entries ADD COLUMN mentions TEXT"),
        ("domain", "ALTER TABLE entries ADD COLUMN domain TEXT"),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: all existing tests + the two new ones pass.

- [ ] **Step 6: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "feat(db): add domain column to entries (idempotent migration)"
```

---

## Task 3: `insert_entry` writes domain from tag

**Files:**
- Modify: `src/solo/db.py` (`insert_entry`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

`tests/test_db.py` already provides a `conn` fixture (not `db_conn`). Use it.

Append to `tests/test_db.py`:

```python
def test_insert_entry_writes_domain_from_work_tag(conn):
    from solo.db import insert_entry

    rid = insert_entry(conn, "ship #work redesign", 1, 1, "{}")
    row = conn.execute("SELECT domain FROM entries WHERE id = ?", (rid,)).fetchone()
    assert row["domain"] == "work"


def test_insert_entry_writes_domain_from_life_tag(conn):
    from solo.db import insert_entry

    rid = insert_entry(conn, "dentist #life", 1, 1, "{}")
    row = conn.execute("SELECT domain FROM entries WHERE id = ?", (rid,)).fetchone()
    assert row["domain"] == "life"


def test_insert_entry_leaves_domain_null_when_no_tag(conn):
    from solo.db import insert_entry

    rid = insert_entry(conn, "just a thought", 1, 1, "{}")
    row = conn.execute("SELECT domain FROM entries WHERE id = ?", (rid,)).fetchone()
    assert row["domain"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py::test_insert_entry_writes_domain_from_work_tag -v`
Expected: failure — `row["domain"] is None`, not `"work"`.

- [ ] **Step 3: Update `insert_entry`**

In `src/solo/db.py`, replace the current `insert_entry` body:

```python
def insert_entry(
    conn: sqlite3.Connection,
    raw_text: str,
    telegram_chat_id: int,
    telegram_message_id: int,
    telegram_message_json: str,
) -> int:
    from solo import mentions as _mentions  # local import to avoid cycles
    from solo import tags as _tags

    names = _mentions.extract(raw_text)
    domain = _tags.extract(raw_text)
    cursor = conn.execute(
        """
        INSERT INTO entries (
            raw_text, telegram_chat_id, telegram_message_id,
            telegram_message_json, mentions, domain
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            raw_text,
            telegram_chat_id,
            telegram_message_id,
            telegram_message_json,
            ",".join(names) if names else None,
            domain,
        ),
    )
    conn.commit()
    return cursor.lastrowid
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: all tests pass (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "feat(db): insert_entry sets domain from #work / #life tag"
```

---

## Task 4: `apply_classification` writes domain via COALESCE

**Files:**
- Modify: `src/solo/db.py` (`apply_classification`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_db.py` (use the existing `conn` fixture):

```python
def test_apply_classification_writes_domain_when_null(conn):
    from solo.db import apply_classification, insert_entry

    rid = insert_entry(conn, "untagged thought", 1, 1, "{}")
    apply_classification(conn, rid, "idea", "summary", "high", domain="work")
    row = conn.execute("SELECT domain FROM entries WHERE id = ?", (rid,)).fetchone()
    assert row["domain"] == "work"


def test_apply_classification_preserves_tag_set_domain(conn):
    """Tag wins: when capture-time tag pre-populated `domain`, the LLM's
    inferred domain must not overwrite it."""
    from solo.db import apply_classification, insert_entry

    rid = insert_entry(conn, "ship #work redesign", 1, 1, "{}")
    # capture-time tag → domain='work' already in the row
    apply_classification(conn, rid, "idea", "redesign", "high", domain="life")
    row = conn.execute("SELECT domain FROM entries WHERE id = ?", (rid,)).fetchone()
    assert row["domain"] == "work"  # tag wins


def test_apply_classification_returns_false_on_already_classified(conn):
    """Existing guard: apply_classification is a no-op on already-classified rows."""
    from solo.db import apply_classification, insert_entry

    rid = insert_entry(conn, "thought", 1, 1, "{}")
    assert apply_classification(conn, rid, "idea", "s", "high", domain="work") is True
    assert apply_classification(conn, rid, "idea", "s", "high", domain="life") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py::test_apply_classification_writes_domain_when_null -v`
Expected: failure — `TypeError: apply_classification() got an unexpected keyword argument 'domain'`.

- [ ] **Step 3: Update `apply_classification`**

In `src/solo/db.py`, replace the function:

```python
def apply_classification(
    conn: sqlite3.Connection,
    entry_id: int,
    kind: str,
    summary: str,
    priority: str,
    *,
    domain: str | None = None,
) -> bool:
    """Returns True iff a row was actually written (i.e. row was unclassified).

    `domain` is written via COALESCE so a tag-set value at capture time
    (preset domain) is preserved; the LLM-inferred domain only lands when
    the existing row value is NULL.
    """
    truncated = summary[:120]
    cursor = conn.execute(
        """
        UPDATE entries
           SET kind = ?,
               summary = ?,
               priority = ?,
               classified = 1,
               domain = COALESCE(domain, ?)
         WHERE id = ? AND classified = 0
        """,
        (kind, truncated, priority, domain, entry_id),
    )
    conn.commit()
    return cursor.rowcount > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: all tests pass (including the 3 new ones).

Run also: `uv run pytest tests/test_classifier.py tests/test_commands.py -q`
Expected: any existing tests that call `apply_classification` positionally still work (the `domain` parameter is keyword-only with a default of `None`).

- [ ] **Step 5: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "feat(db): apply_classification writes domain via COALESCE (tag wins)"
```

---

## Task 5: `ClassifyResult` gains `domain` + classifier passes it through

**Files:**
- Modify: `src/solo/classifier.py`
- Test: `tests/test_classifier.py`

- [ ] **Step 1: Write failing tests**

`tests/test_classifier.py` already provides a `conn` fixture (not `db_conn`) and a `FakeLLM` class with `results=` and `errors=` kwargs. Use those — do not redefine.

Append to `tests/test_classifier.py` (inside the file at top-level, after the existing tests):

```python
class TestClassifyResultDomain:
    def test_accepts_all_three_domain_values(self):
        from solo.classifier import ClassifyResult

        for d in ("work", "life", "either"):
            r = ClassifyResult(kind="idea", summary="s", priority="low", domain=d)
            assert r.domain == d

    def test_rejects_invalid_domain(self):
        from pydantic import ValidationError

        from solo.classifier import ClassifyResult

        with pytest.raises(ValidationError):
            ClassifyResult(kind="idea", summary="s", priority="low", domain="bogus")

    def test_missing_domain_rejected(self):
        from pydantic import ValidationError

        from solo.classifier import ClassifyResult

        with pytest.raises(ValidationError):
            ClassifyResult(kind="idea", summary="s", priority="low")


class TestClassifyPendingDomainFlow:
    @pytest.mark.asyncio
    async def test_writes_llm_domain_when_untagged(self, conn):
        from solo.classifier import ClassifyResult, classify_pending
        from solo.db import insert_entry

        rid = insert_entry(conn, "untagged", 1, 1, "{}")
        llm = FakeLLM(
            results=[
                ClassifyResult(kind="idea", summary="s", priority="medium", domain="work")
            ]
        )
        await classify_pending(conn, llm, model="x")

        row = conn.execute("SELECT domain FROM entries WHERE id = ?", (rid,)).fetchone()
        assert row["domain"] == "work"

    @pytest.mark.asyncio
    async def test_preserves_tag_set_domain(self, conn):
        """#work tag at capture → LLM-returned 'life' is ignored. Tag wins."""
        from solo.classifier import ClassifyResult, classify_pending
        from solo.db import insert_entry

        rid = insert_entry(conn, "ship #work redesign", 1, 1, "{}")
        llm = FakeLLM(
            results=[
                ClassifyResult(kind="idea", summary="s", priority="medium", domain="life")
            ]
        )
        await classify_pending(conn, llm, model="x")

        row = conn.execute("SELECT domain FROM entries WHERE id = ?", (rid,)).fetchone()
        assert row["domain"] == "work"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_classifier.py::test_classify_result_accepts_domain_values -v`
Expected: failure — `ValidationError: domain field required` or similar.

- [ ] **Step 3: Update `ClassifyResult` + `classify_pending`**

In `src/solo/classifier.py`, replace `ClassifyResult`:

```python
class ClassifyResult(BaseModel):
    kind: Literal["idea", "soft_task", "hard_task", "note"]
    summary: str = Field(min_length=1, max_length=200)
    priority: Literal["low", "medium", "high"]
    domain: Literal["work", "life", "either"]
```

And update the `apply_classification` call inside `classify_pending`:

```python
        wrote = db.apply_classification(
            conn, row["id"], result.kind, result.summary, result.priority,
            domain=result.domain,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_classifier.py -v`
Expected: all tests pass (new + existing). Existing tests that build `ClassifyResult` without `domain` will fail — update them to include `domain="either"`. Any pre-existing test that constructs `ClassifyResult(...)` needs a `domain=` argument added.

- [ ] **Step 5: Update existing `ClassifyResult(...)` constructions**

Run: `grep -rn "ClassifyResult(" tests/ src/solo/ --include="*.py"`

Expected matches (these are the tests that will fail with `ValidationError: domain field required` once Task 5 Step 3 lands):

- `tests/test_classifier.py` — `TestClassifyResultSchema::test_valid_payload`, `TestClassifyResultSchema::test_invalid_kind_rejected`, `TestClassifyResultSchema::test_invalid_priority_rejected`, `TestClassifyResultSchema::test_empty_summary_rejected`, `TestClassifyPendingHappyPath::test_three_rows_all_classified`, `TestClassifyPendingHappyPath::test_limit_respected`, plus any other places. The `test_invalid_*` cases already expect a `ValidationError` — leaving them without `domain` keeps that intent, but be explicit by adding `domain="either"` to the cases that should otherwise be valid.
- `tests/test_commands.py` — `TestHandleTop::test_drains_backlog_then_replies` builds two `ClassifyResult(...)` instances.

For each, add `domain="either"` (or a domain that matches the test's intent — e.g., the `test_drains_backlog_then_replies` rows can stay `"either"` since the test asserts presence in the reply, not domain filtering).

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -q`
Expected: all pass (159+ tests).

- [ ] **Step 7: Commit**

```bash
git add src/solo/classifier.py tests/
git commit -m "feat(classifier): emit domain in ClassifyResult; pass through to db"
```

---

## Task 6: Classifier prompt update

**Files:**
- Modify: `src/solo/prompts/classifier.md`
- Test: `tests/test_prompts.py` (smoke check)

- [ ] **Step 1: Write a failing smoke test**

Append to `tests/test_prompts.py` (or create the file with the import skeleton if it doesn't exist — `ls tests/` confirmed it does):

```python
def test_classifier_prompt_documents_domain_options():
    from pathlib import Path

    src = Path("src/solo/prompts/classifier.md").read_text()
    # Make sure the LLM can see all three options + the rule.
    for keyword in ("domain", "work", "life", "either"):
        assert keyword in src.lower(), f"prompt missing keyword: {keyword}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prompts.py::test_classifier_prompt_documents_domain_options -v`
Expected: failure — `"domain"` not in the prompt.

- [ ] **Step 3: Update `src/solo/prompts/classifier.md`**

Replace the file contents with:

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

Domain:
- work    — clearly belongs to a work / professional lens
- life    — clearly outside work (family, health, hobbies, errands, personal projects)
- either  — could matter in both, or doesn't lean

summary: one short line (≤ 120 chars) capturing the essence in the user's voice.

Entry:
{entry_text}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prompts.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/solo/prompts/classifier.md tests/test_prompts.py
git commit -m "feat(prompt): add domain section to classifier prompt"
```

---

## Task 7: `rank.filter_by_mode`

**Files:**
- Modify: `src/solo/rank.py`
- Test: `tests/test_rank.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_rank.py`:

```python
def test_filter_by_mode_all_returns_input_unchanged():
    from solo.rank import filter_by_mode

    rows = [
        {"id": 1, "domain": "work"},
        {"id": 2, "domain": "life"},
        {"id": 3, "domain": "either"},
        {"id": 4, "domain": None},
    ]
    assert filter_by_mode(rows, "all") == rows


def test_filter_by_mode_work_excludes_life():
    from solo.rank import filter_by_mode

    rows = [
        {"id": 1, "domain": "work"},
        {"id": 2, "domain": "life"},
        {"id": 3, "domain": "either"},
        {"id": 4, "domain": None},
    ]
    out = filter_by_mode(rows, "work")
    assert [r["id"] for r in out] == [1, 3, 4]


def test_filter_by_mode_life_excludes_work():
    from solo.rank import filter_by_mode

    rows = [
        {"id": 1, "domain": "work"},
        {"id": 2, "domain": "life"},
        {"id": 3, "domain": "either"},
        {"id": 4, "domain": None},
    ]
    out = filter_by_mode(rows, "life")
    assert [r["id"] for r in out] == [2, 3, 4]


def test_filter_by_mode_missing_domain_key_is_treated_as_either():
    """Defensive — rows from older code paths may lack the key entirely."""
    from solo.rank import filter_by_mode

    rows = [{"id": 1}]  # no `domain` key at all
    assert filter_by_mode(rows, "work") == rows
    assert filter_by_mode(rows, "life") == rows
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rank.py -v`
Expected: `ImportError: cannot import name 'filter_by_mode'`.

- [ ] **Step 3: Add `filter_by_mode`**

Append to `src/solo/rank.py`:

```python
_LENS_KEEP = {
    "work": {"work", "either", None},
    "life": {"life", "either", None},
}


def filter_by_mode(rows: list[dict], mode: str) -> list[dict]:
    """Filter classified entries by domain lens.

    - 'all'  → return rows unchanged
    - 'work' → keep domain in {'work', 'either', None}
    - 'life' → keep domain in {'life', 'either', None}

    NULL / missing `domain` is bucketed with 'either' so pre-feature
    rows surface in both lenses.
    """
    if mode == "all":
        return rows
    keep = _LENS_KEEP[mode]
    return [r for r in rows if r.get("domain") in keep]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rank.py -v`
Expected: all 10 tests pass (6 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/solo/rank.py tests/test_rank.py
git commit -m "feat(rank): add filter_by_mode for work/life/all lens"
```

---

## Task 8: `timeflex.auto_mode` helper

**Files:**
- Create: `src/solo/timeflex.py`
- Test: `tests/test_timeflex.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_timeflex.py

from datetime import datetime


def test_monday_morning_is_work():
    from solo.timeflex import auto_mode

    # 2026-05-25 is a Monday.
    assert auto_mode(datetime(2026, 5, 25, 10, 0)) == "work"


def test_friday_before_six_pm_is_work():
    from solo.timeflex import auto_mode

    # 2026-05-29 is a Friday.
    assert auto_mode(datetime(2026, 5, 29, 17, 59)) == "work"


def test_friday_at_six_pm_is_life():
    from solo.timeflex import auto_mode

    assert auto_mode(datetime(2026, 5, 29, 18, 0)) == "life"


def test_friday_evening_is_life():
    from solo.timeflex import auto_mode

    assert auto_mode(datetime(2026, 5, 29, 22, 30)) == "life"


def test_saturday_is_life():
    from solo.timeflex import auto_mode

    # 2026-05-30 is a Saturday.
    assert auto_mode(datetime(2026, 5, 30, 3, 0)) == "life"
    assert auto_mode(datetime(2026, 5, 30, 14, 0)) == "life"


def test_sunday_is_life_all_day():
    from solo.timeflex import auto_mode

    # 2026-05-31 is a Sunday.
    assert auto_mode(datetime(2026, 5, 31, 0, 0)) == "life"
    assert auto_mode(datetime(2026, 5, 31, 23, 59)) == "life"


def test_now_local_reads_solo_timezone_env(monkeypatch):
    from solo.timeflex import now_local

    monkeypatch.setenv("SOLO_TIMEZONE", "America/Los_Angeles")
    now = now_local()
    # Just check tzinfo is set and matches the env var.
    assert now.tzinfo is not None
    assert "Los_Angeles" in str(now.tzinfo)


def test_now_local_default_is_asia_kolkata(monkeypatch):
    from solo.timeflex import now_local

    monkeypatch.delenv("SOLO_TIMEZONE", raising=False)
    now = now_local()
    assert "Kolkata" in str(now.tzinfo)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_timeflex.py -v`
Expected: all fail with `ModuleNotFoundError: No module named 'solo.timeflex'`.

- [ ] **Step 3: Implement `timeflex.py`**

```python
# src/solo/timeflex.py
"""Weekday/weekend resolver for /top auto-mode.

Pure module (except `now_local`, which reads the SOLO_TIMEZONE env var).

Weekend rule: Friday at or after 18:00 local, all of Saturday, all of
Sunday. Everything else is a weekday → work focus.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6
_EVENING_CUTOFF_HOUR = 18  # 6pm

_DEFAULT_TZ = "Asia/Kolkata"


def auto_mode(now: datetime) -> str:
    """Return 'work' or 'life' from a local-time datetime.

    Caller is responsible for passing a TZ-aware or otherwise local datetime.
    We only read `weekday()` and `hour`.
    """
    wd = now.weekday()
    if wd == _FRIDAY and now.hour >= _EVENING_CUTOFF_HOUR:
        return "life"
    if wd in (_SATURDAY, _SUNDAY):
        return "life"
    return "work"


def now_local() -> datetime:
    """Current datetime in SOLO_TIMEZONE (default Asia/Kolkata)."""
    tz_name = os.environ.get("SOLO_TIMEZONE", _DEFAULT_TZ)
    return datetime.now(ZoneInfo(tz_name))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_timeflex.py -v`
Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/solo/timeflex.py tests/test_timeflex.py
git commit -m "feat(timeflex): auto_mode resolves work/life from local time"
```

---

## Task 9: `handle_top` mode resolution + filter; `format_top` headers; usage

**Files:**
- Modify: `src/solo/commands.py`
- Test: `tests/test_commands.py`

This is the integration task — it wires Tasks 7 and 8 into the user-facing `/top` flow.

- [ ] **Step 1: Write failing tests for `handle_top` arg parsing**

Append to `tests/test_commands.py` inside `class TestHandleTop:` (just before `class TestHandleList`):

```python
    @pytest.mark.asyncio
    async def test_invalid_arg_replies_usage(self, db_conn):
        from solo.commands import handle_top

        msg = FakeMessage("/top bogus")
        update = FakeUpdate(msg)
        await handle_top(update, FakeContextWithArgs(["bogus"]), conn=db_conn, llm=FakeLLM())

        assert msg._replied == "usage: /top [work|life|all]"

    @pytest.mark.asyncio
    async def test_too_many_args_replies_usage(self, db_conn):
        from solo.commands import handle_top

        msg = FakeMessage("/top work life")
        update = FakeUpdate(msg)
        await handle_top(
            update, FakeContextWithArgs(["work", "life"]), conn=db_conn, llm=FakeLLM()
        )

        assert msg._replied == "usage: /top [work|life|all]"

    @pytest.mark.asyncio
    async def test_arg_is_case_insensitive(self, db_conn):
        from solo.commands import handle_top
        from solo.db import apply_classification, insert_entry

        a = insert_entry(db_conn, "x", 1, 1, "{}")
        apply_classification(db_conn, a, "idea", "x", "high", domain="work")

        msg = FakeMessage("/top WORK")
        update = FakeUpdate(msg)
        await handle_top(update, FakeContextWithArgs(["WORK"]), conn=db_conn, llm=FakeLLM())

        assert msg._replied is not None
        assert "manual" in msg._replied  # header reflects override

    @pytest.mark.asyncio
    async def test_explicit_all_skips_filter(self, db_conn):
        from solo.commands import handle_top
        from solo.db import apply_classification, insert_entry

        a = insert_entry(db_conn, "w", 1, 1, "{}")
        b = insert_entry(db_conn, "l", 1, 2, "{}")
        apply_classification(db_conn, a, "idea", "w", "high", domain="work")
        apply_classification(db_conn, b, "idea", "l", "high", domain="life")

        msg = FakeMessage("/top all")
        update = FakeUpdate(msg)
        await handle_top(update, FakeContextWithArgs(["all"]), conn=db_conn, llm=FakeLLM())

        assert "w" in msg._replied
        assert "l" in msg._replied
        assert "everything" in msg._replied

    @pytest.mark.asyncio
    async def test_explicit_life_filters_out_work(self, db_conn):
        from solo.commands import handle_top
        from solo.db import apply_classification, insert_entry

        w = insert_entry(db_conn, "work_only", 1, 1, "{}")
        lf = insert_entry(db_conn, "life_only", 1, 2, "{}")
        apply_classification(db_conn, w, "idea", "work_only", "high", domain="work")
        apply_classification(db_conn, lf, "idea", "life_only", "high", domain="life")

        msg = FakeMessage("/top life")
        update = FakeUpdate(msg)
        await handle_top(update, FakeContextWithArgs(["life"]), conn=db_conn, llm=FakeLLM())

        assert "life_only" in msg._replied
        assert "work_only" not in msg._replied

    @pytest.mark.asyncio
    async def test_auto_mode_filters_by_resolved_lens(self, db_conn, monkeypatch):
        """No arg → resolves auto_mode → applies filter. Pinned to a Monday
        so we know the lens is `work`."""
        from datetime import datetime

        from solo.commands import handle_top
        from solo.db import apply_classification, insert_entry

        w = insert_entry(db_conn, "work_only", 1, 1, "{}")
        lf = insert_entry(db_conn, "life_only", 1, 2, "{}")
        apply_classification(db_conn, w, "idea", "work_only", "high", domain="work")
        apply_classification(db_conn, lf, "idea", "life_only", "high", domain="life")

        # Pin "now" to Monday 10:00 in any TZ.
        from solo import timeflex

        monkeypatch.setattr(timeflex, "now_local", lambda: datetime(2026, 5, 25, 10, 0))

        msg = FakeMessage("/top")
        update = FakeUpdate(msg)
        await handle_top(update, FakeContextWithArgs([]), conn=db_conn, llm=FakeLLM())

        assert "work_only" in msg._replied
        assert "life_only" not in msg._replied
        assert "work focus" in msg._replied
```

Also append, inside `TestFormatTop` (or wherever `format_top` is tested today):

```python
    def test_format_top_header_work_auto(self):
        from solo.commands import format_top

        out = format_top([], aging=[], mode="work", auto=True)
        assert out.startswith("nothing to rank yet (work focus)") or "work focus" in out

    def test_format_top_header_life_auto(self):
        from solo.commands import format_top

        out = format_top([], aging=[], mode="life", auto=True)
        assert "life focus" in out

    def test_format_top_header_manual_work(self):
        from solo.commands import format_top

        out = format_top([], aging=[], mode="work", auto=False)
        assert "work, manual" in out

    def test_format_top_header_all(self):
        from solo.commands import format_top

        out = format_top([], aging=[], mode="all", auto=False)
        assert "everything" in out

    def test_format_top_with_items_includes_header(self):
        from solo.commands import format_top

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        top = [self._row(id=1, summary="ship it", created_at="2026-05-23T10:00:00.000Z")]
        out = format_top(top, aging=[], mode="work", auto=True, now=now)
        assert "(work focus)" in out
        assert "1️⃣ 💡 ship it" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_commands.py::TestHandleTop -v`
Expected: new tests fail; existing tests in `TestHandleTop` may also fail because `handle_top` doesn't yet accept `context.args` resolution. That's fine — Step 4 will get them all passing.

- [ ] **Step 3: Update `handle_top`, `format_top`, and add `_TOP_USAGE`**

In `src/solo/commands.py`:

(a) Add the usage constant near the existing `_TOP_FAILED`:

```python
_TOP_USAGE = "usage: /top [work|life|all]"
```

(b) Add a private mode-resolver:

```python
_VALID_MODES = {"work", "life", "all"}


def _resolve_mode(args: list[str] | None) -> tuple[str | None, bool]:
    """Return (mode, auto).

    - No args            → (auto_mode(now_local()), True)
    - Single valid arg   → (lower-cased arg, False)
    - Anything else      → (None, False) — caller must reply usage.
    """
    from solo.timeflex import auto_mode, now_local

    if not args:
        return auto_mode(now_local()), True
    if len(args) == 1 and args[0].lower() in _VALID_MODES:
        return args[0].lower(), False
    return None, False
```

(c) Replace `handle_top`:

```python
async def handle_top(
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
    args = getattr(context, "args", None) or []
    mode, auto = _resolve_mode(args)
    if mode is None:
        await update.message.reply_text(_TOP_USAGE)
        return
    try:
        await classify_pending(conn, llm, model=model)
        rows = db.fetch_classified(conn, kinds=["soft_task", "idea"])
        filtered = rank.filter_by_mode(rows, mode)
        top = rank.top(filtered)
        top_ids = {r["id"] for r in top}
        aging = [
            r for r in filtered
            if r["id"] not in top_ids and _is_stale(r["created_at"])
        ]
        await update.message.reply_text(
            format_top(top, aging=aging, mode=mode, auto=auto)
        )
    except Exception:
        logger.exception("/top failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text(_TOP_FAILED)
        except Exception:
            logger.exception("/top fallback reply also failed")
```

(d) Replace `format_top`:

```python
def _header_label(mode: str, auto: bool) -> str:
    """Return the parenthetical for the header / empty message."""
    if mode == "all":
        return "everything"
    if auto:
        return f"{mode} focus"
    return f"{mode}, manual"


def format_top(
    top: list[dict],
    *,
    aging: list[dict],
    mode: str,
    auto: bool,
    now: datetime | None = None,
) -> str:
    label = _header_label(mode, auto)
    if not top:
        return f"nothing to rank yet ({label})"

    lines = [f"Top for today ({label}):", ""]
    for i, r in enumerate(top):
        if i >= len(_NUMBER_EMOJI):
            break
        marker = _marker(r.get("mentions"))
        age = _age(r["created_at"], now=now)
        stale = " ⚠️" if _is_stale(r["created_at"], now=now) else ""
        lines.append(f"{_NUMBER_EMOJI[i]} {marker} {r['summary']} ({age}){stale}")

    if aging:
        lines.append("")
        lines.append("⚠️ Also aging (>14d, not in top):")
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

- [ ] **Step 4: Update existing `TestHandleTop` tests + `TestFormatTop` tests for the new format_top signature**

In `tests/test_commands.py`, every existing call to `format_top(...)` needs `mode=` and `auto=` keyword args. The simplest defaults preserving old behavior:

```python
format_top(top, aging=aging, mode="work", auto=True, now=now)
```

For the `test_empty_returns_nothing_to_rank_yet` test, update the assertion from `"nothing to rank yet"` to `"nothing to rank yet (work focus)"`.

For the `test_renders_three_terse_items_with_ideation_marker` test, update the assertion from `"Top 3 for today:"` to `"Top for today (work focus):"`.

For all other `format_top(...)` callsites: add `mode="work", auto=True`.

For existing `TestHandleTop` tests (other than the ones added in Step 1), they call `await handle_top(update, FakeContext(), ...)`. `FakeContext` has no `args` attribute — `getattr(context, "args", None) or []` will resolve to `[]` and trigger auto mode. With no rows in the DB this is fine, but `test_drains_backlog_then_replies` and `test_filters_to_soft_task_and_idea` build classified rows. Pin `auto_mode` so the lens is `work` for those tests:

```python
# At the top of TestHandleTop, add a class-scoped autouse fixture:
@pytest.fixture(autouse=True)
def _pin_work_lens(self, monkeypatch):
    from datetime import datetime

    from solo import timeflex

    monkeypatch.setattr(timeflex, "now_local", lambda: datetime(2026, 5, 25, 10, 0))
```

Then update those existing tests' assertions:
- `test_drains_backlog_then_replies` — change `"Top 3 for today:"` to `"Top for today (work focus):"`. The rows inserted are untagged → domain stays NULL → they surface in work mode regardless. Update both `ClassifyResult(...)` constructions in this test to include `domain="either"`.
- `test_filters_to_soft_task_and_idea` — apply_classification needs `domain="work"` arg added (or any non-life value); the assertion currently asserts "soft" and "idea" appear and "hard"/"note" don't, which still holds with the work filter.
- `test_empty_pool_returns_nothing_message` — update assertion to `"nothing to rank yet (work focus)"`.
- `test_handler_replies_fallback_on_llm_failure` — assertion is `"nothing to rank yet"`; update to `"nothing to rank yet (work focus)"`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_commands.py -v`
Expected: all `TestHandleTop` and `TestFormatTop` tests pass.

Run: `uv run pytest -q`
Expected: full suite passes.

- [ ] **Step 6: Commit**

```bash
git add src/solo/commands.py tests/test_commands.py
git commit -m "feat(commands): /top resolves work/life/all mode and renders lens header"
```

---

## Task 10: Help text + .env.example

**Files:**
- Modify: `src/solo/commands.py` (`_HELP_TEXT`)
- Modify: `.env.example`
- Test: `tests/test_commands.py` (existing `TestHandleHelp::test_replies_with_help_text` already iterates command names — should still pass)

- [ ] **Step 1: Update `_HELP_TEXT`**

In `src/solo/commands.py`, replace the `_HELP_TEXT` constant:

```python
_HELP_TEXT = (
    "Commands:\n"
    "/top [work|life|all]  — top items right now\n"
    "                        (auto: work on weekdays, life on Fri eve + weekends)\n"
    "/list  — all active items, with IDs\n"
    "/all   — everything (active + done)\n"
    "/drop <id> [<id>...]  — hard delete\n"
    "/done <id> [<id>...]  — mark done\n"
    "/redo <id>            — re-classify\n"
    "/help  — this message"
)
```

- [ ] **Step 2: Update `.env.example`**

Read `.env.example` first:

Run: `cat .env.example` (via the Read tool ideally, but a quick `cat` to know what's there).

Append (or insert next to other SOLO_ vars) the following line:

```
# Timezone used to decide weekday/weekend for /top auto-mode. Default: Asia/Kolkata.
SOLO_TIMEZONE=Asia/Kolkata
```

- [ ] **Step 3: Run help test**

Run: `uv run pytest tests/test_commands.py::TestHandleHelp -v`
Expected: pass. The existing test iterates `("/top", "/list", "/all", "/drop", "/done", "/redo", "/help")` — all still present.

- [ ] **Step 4: Commit**

```bash
git add src/solo/commands.py .env.example
git commit -m "docs: document /top modes in help + add SOLO_TIMEZONE env var"
```

---

## Task 11: Living-docs sweep

**Files:**
- Modify: `README.md`, `AGENTS.md`, `docs/status.md`, `docs/architecture.md`

No tests. Documentation only.

- [ ] **Step 1: Update `README.md`**

(a) In the "Status" section, change the `/top` description to mention the lens:

> `/top` (work/life flex), `/log`, ...

(b) In the "Environment" table, add a `SOLO_TIMEZONE` row:

| `SOLO_TIMEZONE` | no | Timezone used for `/top` weekday/weekend auto-detection. Default `Asia/Kolkata`. |

- [ ] **Step 2: Update `AGENTS.md`**

In §"Project context", append to the bot-flow sentence:

> ...ranked priorities are returned. Items carry a `domain` axis (`work` / `life` / `either`), and `/top` flexes by time-of-week (work-focus on weekdays, life-focus Fri eve + Sat/Sun) or by an explicit `/top work|life|all` arg.

- [ ] **Step 3: Update `docs/status.md`**

(a) Bump "Last updated" to today's date and tool/model.

(b) In "Commands available", replace the `/top` line with:

> - `/top [work|life|all]` — top items from `soft_task` + `idea` filtered by domain lens. Auto: work on weekdays, life Fri eve + Sat/Sun. Override: `/top work|life|all`.

(c) Add a one-liner under "Schema additions" mentioning the new `domain TEXT` column (NULL on pre-feature rows, treated as `either`).

- [ ] **Step 4: Update `docs/architecture.md`**

In §1, change the `/top` row to mention the lens:

| `top` ranking | Heuristic + work/life lens filter | No |

In §9, change item 3:

> 3. `/top [work|life|all]` and `/log` commands inside Telegram

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md docs/status.md docs/architecture.md
git commit -m "docs: living docs reflect /top work/life flex + SOLO_TIMEZONE"
```

---

## Task 12: ADR-0009 — domain axis

**Files:**
- Create: `docs/decisions/0009-domain-axis.md`
- Modify: `docs/decisions/README.md` (index)

- [ ] **Step 1: Check existing ADR format**

Run: `cat docs/decisions/0008-mention-extraction-is-regex.md` to confirm style.

- [ ] **Step 2: Write ADR-0009**

```markdown
# ADR-0009 — `domain` axis on entries (`work` / `life` / `either`)

**Status:** Accepted
**Date:** 2026-05-26
**Slice:** Domain-flex for `/top`

## Context

`/top` ranks by priority + recency. Surfacing meaningful "what to think
about right now" requires a second axis: kb cares about different things
on Wednesday morning vs Saturday afternoon. Without a work/life signal,
`/top` mixes contexts and the results feel "meh".

## Decision

Add a `domain TEXT` column to `entries` with values `'work'` / `'life'`
/ `'either'` / `NULL`. Signal sources, in priority order:

1. **Capture-time tag** — `#work` / `#life` in raw_text, parsed by a new
   `solo.tags` module at `insert_entry` time. First match wins.
2. **LLM inference** — classifier returns `domain` as a fourth output
   field alongside `kind`, `summary`, `priority`.
3. **Untagged + unclassified** — `domain` stays NULL until classified;
   filter treats NULL as `either`.

`apply_classification` writes domain via `COALESCE(domain, ?)` so a
tag-set value at capture is preserved against any LLM inference.

`/top` defaults to `work` lens on weekdays and `life` lens Fri ≥ 18:00 +
Sat + Sun, in `SOLO_TIMEZONE` (default `Asia/Kolkata`). The lens is a
filter, not a sort key, so ADR-0005 (heuristic-only ranking) is
preserved unchanged. Explicit override: `/top work|life|all`.

## Alternatives considered

- **Keyword/heuristic** — maintain word lists. Brittle, needs upkeep.
- **Tag-only** — `#work`/`#life` mandatory. Capture friction violates
  the "capture must never fail" constraint in `AGENTS.md`.
- **Weighted ranking** — domain as a priority modifier, not a filter.
  Subtler but harder to reason about; would supersede ADR-0005.
- **Backfill on first /top after upgrade** — auto re-classify all NULL
  rows. Costs ~1 LLM call per active row at an unpredictable moment.
  Rejected: NULL → `either` decay is sufficient.

## Consequences

- Old rows (pre-feature) all surface as `either` until they're done /
  dropped / `/redo`'d. Accepted gradual decay.
- Classifier prompt grows by ~4 lines. Eval harness is the regression
  gate (`scripts/eval.py`).
- A future conversational `/redo` (separate spec) becomes the
  explicit fix-up path when LLM domain inference is wrong.

## Related

- ADR-0005 — heuristic-only ranking (unchanged; filter applied before
  rank).
- ADR-0008 — regex-at-insert for mentions; this ADR follows the same
  pattern for tags.
```

- [ ] **Step 3: Add to ADR index**

In `docs/decisions/README.md`, append to the ADR list (preserving sort order):

```markdown
- [0009 — `domain` axis on entries (work / life / either)](0009-domain-axis.md)
```

- [ ] **Step 4: Commit**

```bash
git add docs/decisions/0009-domain-axis.md docs/decisions/README.md
git commit -m "docs(decisions): ADR-0009 — domain axis (work/life/either)"
```

---

## Task 13: Final verification

**Files:** none modified — verification only.

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -q`
Expected: 0 failures. Should be ~170 tests (existing 159 + ~10 new).

- [ ] **Step 2: Lint**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

- [ ] **Step 3: Format check (informational)**

Run: `uv run ruff format --check src tests`
If anything would be reformatted, decide case-by-case: if it's in a file you touched this slice, run `uv run ruff format <file>` and commit as a style fixup. If it's pre-existing drift in untouched files (per the earlier rename commit), leave alone.

- [ ] **Step 4: Manual sanity — capture path**

Run an ad-hoc Python check against an in-memory DB to confirm the capture path:

```bash
uv run python - <<'PY'
import sqlite3
from solo.db import insert_entry, get_connection

conn = get_connection(":memory:")
rid_work = insert_entry(conn, "ship #work redesign", 1, 1, "{}")
rid_life = insert_entry(conn, "dentist on tuesday #life", 1, 1, "{}")
rid_none = insert_entry(conn, "untagged thought", 1, 1, "{}")

for rid in (rid_work, rid_life, rid_none):
    row = conn.execute("SELECT id, raw_text, domain FROM entries WHERE id = ?", (rid,)).fetchone()
    print(dict(row))
PY
```

Expected output:
```
{'id': 1, 'raw_text': 'ship #work redesign', 'domain': 'work'}
{'id': 2, 'raw_text': 'dentist on tuesday #life', 'domain': 'life'}
{'id': 3, 'raw_text': 'untagged thought', 'domain': None}
```

- [ ] **Step 5: Manual sanity — auto-mode resolution**

```bash
uv run python - <<'PY'
from datetime import datetime
from solo.timeflex import auto_mode, now_local

# Resolved current local mode
print("now:", now_local(), "→", auto_mode(now_local()))

# Spot-check the boundary
for dt in [
    datetime(2026, 5, 25, 10, 0),  # Mon
    datetime(2026, 5, 29, 17, 59), # Fri 17:59
    datetime(2026, 5, 29, 18, 0),  # Fri 18:00
    datetime(2026, 5, 30, 14, 0),  # Sat
    datetime(2026, 5, 31, 23, 59), # Sun
]:
    print(dt.strftime("%a %H:%M"), "→", auto_mode(dt))
PY
```

Expected output (last lines):
```
Mon 10:00 → work
Fri 17:59 → work
Fri 18:00 → life
Sat 14:00 → life
Sun 23:59 → life
```

- [ ] **Step 6: If everything is green, no extra commit needed.** The slice is shippable. Surface to the user that the implementation is complete and that the next steps are: (a) live Telegram smoke test of `/top` / `/top work` / `/top life` / `/top all`; (b) re-run the eval harness once `OPENROUTER_API_KEY` is available.

---

## Notes for executor

- **Do not** introduce a `/redo all` or any automatic backfill. ADR-0009 commits to NULL → `either` decay. Conversational `/redo` is a separate slice.
- **Do not** change `rank.top`'s signature — the filter happens before ranking; the sort key stays `(priority, created_at, id) desc`. ADR-0005 stays intact.
- **Do not** rename `/top` to something else (e.g., `/focus`). The user's chosen surface is `/top`.
- The `format_top` header text is deliberately terse — "Top for today (work focus):" / "(work, manual)" / "(everything)" — keep it that way.
- Friday-evening cutoff is hardcoded at 18:00 via the `_EVENING_CUTOFF_HOUR` constant. Promotion to env var is out of scope.
