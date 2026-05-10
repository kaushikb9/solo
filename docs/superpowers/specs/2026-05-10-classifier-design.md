# Classifier (Slice 3) — Design Spec

**Date:** 2026-05-10
**Status:** Approved (brainstorm complete; pending plan)
**Slice:** V0 slice 3 — Lazy classifier
**Predecessor:** Slice 2 — LLMClient + `llm_calls` trace (shipped in commit `8274b6a`)

---

## Goal

Add a classifier that turns each captured `entries` row into a `(kind, summary, priority)` triple, written back to the row. Triggered lazily — slice 4's `/top3` handler will call `classify_pending(...)` before ranking. This slice ships the classifier module + prompt + schema migration + tests; it does **not** wire `/top3`.

## Non-goals

- `/top3` and `/log` commands (slice 4)
- Eval harness for the classifier (slice 5)
- Re-classification of already-classified entries
- Embedding-based dedup, tags/themes, multi-label classification
- Concurrent/parallel classification (sequential is fine for V0 volumes)

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Output schema = `kind` + `summary` + `priority` | Per brainstorm Q1; tags deferred. |
| D2 | `kind ∈ {idea, soft_task, hard_task, note}` | From `requirements.md` §5.1.5 + §5.3. |
| D3 | `priority ∈ {low, medium, high}` | Per brainstorm Q2; numeric scale rejected (overstates LLM precision). |
| D4 | Storage = columns on `entries` table (not side table) | Per brainstorm Q3; revisitable when re-classification history is needed (ADR-0003). |
| D5 | Failure handling = bounded retries (max 3) | Per brainstorm Q4; prevents infinite retry of structurally broken entries. |
| D6 | Sequential execution | V0 volumes (~5–30 entries/day) don't justify parallelism complexity. |
| D7 | Module name = `classifier.py` | Drift from `architecture.md §10` (`classify.py`); `AGENTS.md` and `status.md` use `classifier.py`. Architecture doc gets a one-line tweak as part of this change. |

## Module shape

New file: `src/solo/classifier.py`

```python
from typing import Literal
from pydantic import BaseModel
from solo.llm import LLMClient
import sqlite3

class ClassifyResult(BaseModel):
    kind: Literal["idea", "soft_task", "hard_task", "note"]
    summary: str          # ≤ 120 chars (validated, truncated if longer)
    priority: Literal["low", "medium", "high"]

async def classify_pending(
    conn: sqlite3.Connection,
    llm: LLMClient,
    *,
    model: str,
    limit: int = 50,
    max_attempts: int = 3,
) -> int:
    """Classify all unclassified entries with attempts < max_attempts.
    Sequential. Idempotent. Never raises.
    Returns count of rows successfully classified in this call."""
```

`classify_pending` is the only public symbol callers need. `ClassifyResult` is exported for type hinting in slice 4.

## Schema migration

Add to `_SCHEMA` in `src/solo/db.py` so fresh DBs are correct from the start:

```sql
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
```

Idempotent migration in `get_connection` for existing DBs:

```python
def _migrate_entries(conn):
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(entries)")}
    for col, ddl in (
        ("kind",                    "ALTER TABLE entries ADD COLUMN kind TEXT"),
        ("summary",                 "ALTER TABLE entries ADD COLUMN summary TEXT"),
        ("priority",                "ALTER TABLE entries ADD COLUMN priority TEXT"),
        ("classification_attempts", "ALTER TABLE entries ADD COLUMN classification_attempts INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in cols:
            conn.execute(ddl)
```

Called once in `get_connection` after the existing `executescript(_SCHEMA)`.

## DB query helpers (in `db.py`)

```python
def fetch_unclassified(conn, limit: int = 50, max_attempts: int = 3) -> list[dict]:
    """Rows where classified=0 AND classification_attempts < max_attempts.
    Order: created_at ASC (oldest first — fairness)."""

def apply_classification(conn, entry_id: int, kind: str, summary: str, priority: str) -> None:
    """Set kind/summary/priority and classified=1. No-op if entry already classified."""

def record_classification_failure(conn, entry_id: int) -> None:
    """Increment classification_attempts."""
```

All three commit immediately. `apply_classification` truncates `summary` to 120 chars defensively.

## Prompt — `src/solo/prompts/classifier.md`

Single `{entry_text}` variable. Body (final wording during implementation):

```
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

Loaded via existing `solo.prompts.render("classifier", entry_text=...)`.

## Control flow (`classify_pending`)

```
rows = db.fetch_unclassified(conn, limit, max_attempts)
success = 0
for row in rows:
    try:
        result = await llm.structured(
            "classifier",
            ClassifyResult,
            model=model,
            vars={"entry_text": row["raw_text"]},
        )
        db.apply_classification(conn, row["id"], result.kind, result.summary, result.priority)
        success += 1
    except Exception as exc:
        log.warning("classify failed for entry %s: %s", row["id"], exc)
        db.record_classification_failure(conn, row["id"])
        # llm_calls already has the error row from LLMClient
return success
```

`classify_pending` never raises. The capture-must-never-fail principle (AGENTS.md) extends to `/top3` invocations: a model outage should still let `/top3` rank whatever is already classified.

## Tests

### `tests/test_classifier.py` (new, unit, no network)

Fake `LLMClient` — duck-typed object with an async `structured(prompt, schema, *, model, vars)` method that returns a configured `ClassifyResult` or raises a configured exception.

Cases:
1. Empty backlog → returns 0, no LLM calls
2. Happy path — 3 rows → all `classified=1`, correct `kind/summary/priority`, returns 3
3. Single failure — fake raises once → row has `classification_attempts=1`, `classified=0`, returns 0
4. Mixed batch — 2 succeed, 1 fails → returns 2, failed row has `attempts=1`
5. Bounded retries — row pre-set to `classification_attempts=3` is skipped by `fetch_unclassified`
6. `limit` respected — 10 rows pending, `limit=3` → only 3 processed
7. Summary > 120 chars → truncated to 120 in DB
8. `apply_classification` is idempotent / no-op for already-classified rows

### `tests/test_db.py` (extend existing)

- Migration is idempotent: `get_connection` called twice on the same path doesn't error
- Fresh DB has all new columns at expected types/defaults
- Migration applied to a pre-slice-3 DB (one created with the old `_SCHEMA`) adds the missing columns
- `fetch_unclassified`, `apply_classification`, `record_classification_failure` round-trip correctly
- `fetch_unclassified` orders by `created_at ASC`

### `tests/test_classifier_live.py` (new, gated on `OPENROUTER_API_KEY`)

Mirrors `test_llm_live.py`. One real call against the configured model classifying a known entry; assert schema validates, `kind` ∈ valid set, `priority` ∈ valid set. Skipped when env var absent.

## Documentation rituals (bundled in this slice)

- **Concept primer** — `docs/concepts/structured-outputs.md`. Why we use `response_format=BaseModel` (Pydantic) over hand-parsed JSON. Gotchas with non-OpenAI providers behind OpenRouter (this slice resolves the slice-2 flagged risk: does `response_format` work reliably across MiniMax/Kimi backends?).
- **ADR** — `docs/decisions/0003-classifier-on-entries-vs-side-table.md`. Records D4 with reason and revisit trigger (re-classification history).
- **Status update** — `docs/status.md`: mark slice 3 done, set "what's next" to slice 4.
- **Architecture nit** — `docs/architecture.md §10`: one-line `classify.py` → `classifier.py`.

## Verification cycle (per AGENTS.md)

Before claiming done:
1. `uv run pytest` — all green
2. `uv run ruff check .` — clean
3. Live test (manual, opt-in): `OPENROUTER_API_KEY=… uv run pytest tests/test_classifier_live.py -v`
4. Both reviewers: generic `code-reviewer` + `solo-reviewer`

## Files touched

| File | Change |
|---|---|
| `src/solo/db.py` | Extend `_SCHEMA`, add `_migrate_entries`, three new query helpers |
| `src/solo/classifier.py` | **new** — `ClassifyResult`, `classify_pending` |
| `src/solo/prompts/classifier.md` | **new** — classifier prompt |
| `tests/test_classifier.py` | **new** — unit tests |
| `tests/test_classifier_live.py` | **new** — gated live test |
| `tests/test_db.py` | Add migration + new-helper tests |
| `docs/concepts/structured-outputs.md` | **new** — concept primer |
| `docs/decisions/0003-classifier-on-entries-vs-side-table.md` | **new** — ADR |
| `docs/architecture.md` | One-line: `classify.py` → `classifier.py` |
| `docs/status.md` | Mark slice 3 done; set next = slice 4 |

## Open follow-ups (not in this slice)

- Slice 4 wires `classify_pending` into `/top3`, picks `model` from `SOLO_CLASSIFY_MODEL` env, and adds `/log`.
- Slice 5 builds the eval harness — uses `tests/test_classifier.py`'s fake LLM patterns as a reference but reads labeled examples from `evals/classify.jsonl`.
- If retries-exhausted backlog grows in practice, add a `/reclassify` admin command or an `entries.classification_error TEXT` column.
