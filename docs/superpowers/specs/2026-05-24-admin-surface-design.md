# Slice 6 — Admin surface + visual refresh design

**Date:** 2026-05-24
**Status:** approved, ready for implementation
**Author:** Claude Code (Opus 4.7), driven by kb

## 1. Purpose

After ~30 captured entries kb hit the V0 wall: `/log` is plain text without IDs; there's no way to remove noise, mark items done, or fix a mis-classified row. Every cleanup means hand-editing SQLite. This slice closes that gap with five new commands and a visual refresh of the existing output.

This is V0.1 — operational polish on top of a working V0, not a new capability.

## 2. Resolved design questions

| # | Question | Resolution | Rationale |
|---|---|---|---|
| D1 | `/drop` semantics — soft or hard? | **Hard delete** | kb explicitly chose. Simpler schema (no `dropped` state). `/done` covers the "remove from active view but keep history" case. |
| D2 | How to tag "external ask vs ideation"? | **`@name` regex at insert; no LLM-inferred ask flag** | kb's actual signal is `@name` in the text. Keeps schema lean; deterministic; zero new LLM cost. Marker slot for inferred external-ask is reserved visually but not implemented. |
| D3 | `/log` rename — alias or hard cut? | **Hard cut: `/log` removed; replaced by `/all`** | kb only used `/log` a handful of times; muscle memory hasn't set. Telegram's default "unknown command" handling is acceptable. |
| D4 | `/top3` style — terse or metadata-heavy? | **Terse, with stale-section below** | Matches kb's reference Hermes output. Less ink per item. Aging info surfaced as a separate section instead of inline tags. |
| D5 | What state can a row be in? | **`done` boolean only (default 0)** | Hard delete handles "dropped" so we don't need a 3-valued status. Reduces state machine. |

## 3. Schema bump

Two columns added to `entries` via the existing per-column `_migrate_entries` pattern in `src/solo/db.py`. Idempotent — re-running on a migrated DB is a no-op.

```sql
ALTER TABLE entries ADD COLUMN done     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE entries ADD COLUMN mentions TEXT;
```

- **`done`** — boolean (0/1). `/done <id>` sets it; `/list` and `/top3` filter `done=0 AND classified=1`; `/all` shows everything regardless.
- **`mentions`** — comma-separated `@name` list extracted at `insert_entry` time via regex. NULL when no mentions. Backfill is NOT performed on pre-existing rows; they render as if they had no mentions until `/redo` runs them through the classifier again (or until kb re-types the entry — `/redo` does NOT change raw_text).

## 4. Commands

| Cmd | New? | Behavior | Reply on success | Reply on empty / no-op |
|---|---|---|---|---|
| `/top3` | existing | unchanged ranking; new visual format | top 3 + stale section | `nothing to rank yet` |
| `/list` | NEW | active items grouped by kind, with IDs and ages | grouped list | `nothing active` |
| `/all` | renamed from `/log` | everything including done items | grouped list with ✅ markers | `nothing yet` |
| `/drop <id> [<id>...]` | NEW | hard delete | `dropped N: 12, 19, 23` | `nothing dropped (ids not found)` |
| `/done <id> [<id>...]` | NEW | set `done=1` | `done N: 12, 19` | `nothing changed (ids not found)` |
| `/redo <id>` | NEW | reset `classified=0, kind=NULL, summary=NULL, priority=NULL, classification_attempts=0` for one id. Next `/top3` re-classifies. | `requeued 12 for next /top3` | `id 12 not found` |
| `/help` | NEW | terse list of commands | static help text | n/a |

`/log` is unregistered. Telegram's runtime will respond with its built-in unknown-command behavior (or silence, depending on settings); we don't intercept.

### Arg parsing

`/drop` and `/done` accept multiple ids via space-separated args, parsed from `context.args` (python-telegram-bot already populates this on `CommandHandler`). Anything that isn't `int()`-able is silently dropped with a log line — keep the command tolerant.

`/redo` accepts exactly one id; multiple is rejected with `usage: /redo <id>`.

## 5. Visual format

All output is plain text. Emojis allowed in user-facing strings only (per kb's explicit request); never in code comments, docs, or fixtures (per AGENTS.md tone rule).

### `/top3`

```
Top 3 for today:

1️⃣ 👥 @ashish 1BHK reimbursement (3d)
2️⃣ 💡 review Greenhouse interview feedback (1d) ⚠️
3️⃣ 💡 embeddings for dedup (4d)

⚠️ Also aging (>14d, not in top 3):
   • 👥 @john project frontier doc (3w)
   • 💡 team mentoring plan (5w)
```

- Number emoji: `1️⃣` `2️⃣` `3️⃣`.
- Marker: `👥 @name1 @name2` if `mentions` non-empty, else `💡`. The 🔔 slot is reserved for future LLM-inferred "external ask" — NOT used in this slice.
- Age suffix `(Xd)` or `(Xw)`. `⚠️` appended when age > 14 days.
- Aging section: same kinds (`soft_task` + `idea`), `done=0`, age > 14d, not already in top 3. Capped at 5; show `(+N more)` if more exist.

Empty: `nothing to rank yet`.

### `/list` (active only)

```
Active (8):

💡 ideas
  · 23 embeddings for dedup (1d) [med]
  · 19 read prompt caching paper (2w) [low] ⚠️

🌀 soft_tasks
  · 27 figure out positioning (1d) [high]
  · 22 👥 @john team mentoring plan (3w) [med] ⚠️

🔨 hard_tasks
  · 28 👥 @ashish APD docs for directs (1d) [high]

📝 notes
  · 25 Addy Osmani agent harness post (2d) [low]

⏳ unclassified
  · 30 some thought captured but not classified yet (just now)
```

- Section order: `idea`, `soft_task`, `hard_task`, `note`, `unclassified`. Skip empty sections.
- Per-row: `· <id> <marker> <summary> (<age>) [<priority>]`. Mentions inline as before.
- Header count = total active rows. Empty: `nothing active`.

### `/all` (everything)

Same shape as `/list`, but:
- Header: `All (38, 6 done):` — `done` is shown when > 0.
- Done items rendered with `✅` prefix and `[done Xd ago]` suffix (replacing the priority bracket). Use `updated_at` for the "ago" — but we don't have `updated_at`. Use `created_at` for now; document the limitation. Future-proof: when we add `updated_at`, swap.
- No `⏳ unclassified` section is suppressed by done filter — those are `done=0 classified=0`, which shouldn't change visibility.
- Empty: `nothing yet`.

### `/drop`, `/done`, `/redo` replies

Single-line confirmations. Always state the count and the ids acted on:

```
dropped 3: 12, 19, 23
done 2: 12, 19
requeued 12 for next /top3
```

No-op cases produce explicit messages, not silence:

```
nothing dropped (ids not found: 99, 100)
nothing changed (ids not found: 99)
id 12 not found
```

### `/help`

Static text, sub-200 chars:

```
Commands:
/top3   — your top 3 right now
/list   — all active items, with IDs
/all    — everything (active + done)
/drop <id> [<id>...]   — hard delete
/done <id> [<id>...]   — mark done
/redo <id>             — re-classify
/help   — this message
```

## 6. Module shape

| File | Change | Responsibility |
|---|---|---|
| `src/solo/db.py` | MOD | Schema migration; `mark_done(id)`, `delete_entry(id)`, `reset_for_reclassification(id)`; `fetch_active(kinds=None)`; `fetch_all(limit=N)`; existing `fetch_classified` adds `done=0` filter |
| `src/solo/mentions.py` | NEW | Tiny pure module: `extract(raw_text: str) -> list[str]` via `re.findall(r"@(\w+)", ...)`. Lower-cased, deduped, order-preserved |
| `src/solo/commands.py` | MOD | New handlers: `handle_list`, `handle_all`, `handle_drop`, `handle_done`, `handle_redo`, `handle_help`. Renamed `handle_log` → `handle_all` (preserve old function as a thin shim during transition? No — hard cut, see D3). New pure formatters: `format_top3` (rewrite), `format_list`, `format_all`, `_age`, `_marker`. |
| `src/solo/bot.py` | MOD | Register the new `CommandHandler`s; remove `/log` registration |
| `tests/test_mentions.py` | NEW | Unit tests for `extract` |
| `tests/test_db.py` | MOD | New tests for the migration, new helpers, `fetch_classified` filter change |
| `tests/test_commands.py` | MOD | Replace `TestFormatTop3` / `TestFormatLog` (old shape gone). New `TestFormatTop3` (terse + emoji + aging), `TestFormatList`, `TestFormatAll`. New `TestHandleList` / `TestHandleAll` / `TestHandleDrop` / `TestHandleDone` / `TestHandleRedo` / `TestHandleHelp` |

### `solo.mentions` sketch

```python
import re

_MENTION_RE = re.compile(r"@(\w+)")

def extract(raw_text: str) -> list[str]:
    """Return @-mentions in order of first appearance, lower-cased, deduped."""
    seen: dict[str, None] = {}
    for m in _MENTION_RE.findall(raw_text):
        seen.setdefault(m.lower(), None)
    return list(seen)
```

### `_age` helper

```python
def _age(iso_ts: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    created = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    days = (now - created).days
    if days <= 0:  return "just now"
    if days < 14:  return f"{days}d"
    if days < 56:  return f"{days // 7}w"
    return f"{days // 30}mo"
```

Now is injectable for tests. Uses `datetime.fromisoformat` — but SQLite emits `2026-05-24T10:00:00.000Z`; the `Z` swap covers that.

### `_marker` helper

```python
def _marker(mentions_csv: str | None) -> str:
    if not mentions_csv:
        return "💡"
    names = [f"@{n}" for n in mentions_csv.split(",") if n]
    return "👥 " + " ".join(names)
```

### Migration

In `_migrate_entries(conn)`, extend the additions tuple:

```python
additions = (
    ("kind",                     "ALTER TABLE entries ADD COLUMN kind TEXT"),
    ("summary",                  "ALTER TABLE entries ADD COLUMN summary TEXT"),
    ("priority",                 "ALTER TABLE entries ADD COLUMN priority TEXT"),
    ("classification_attempts",  "ALTER TABLE entries ADD COLUMN classification_attempts INTEGER NOT NULL DEFAULT 0"),
    ("done",                     "ALTER TABLE entries ADD COLUMN done INTEGER NOT NULL DEFAULT 0"),
    ("mentions",                 "ALTER TABLE entries ADD COLUMN mentions TEXT"),
)
```

`_SCHEMA` (the CREATE TABLE for fresh DBs) gets the same two columns.

### `insert_entry` extension

After the INSERT, populate `mentions` if extraction found any. Could be done in one statement:

```python
def insert_entry(conn, raw_text, telegram_chat_id, telegram_message_id, telegram_message_json) -> int:
    names = mentions.extract(raw_text)
    cursor = conn.execute(
        "INSERT INTO entries (raw_text, telegram_chat_id, telegram_message_id, telegram_message_json, mentions) VALUES (?, ?, ?, ?, ?)",
        (raw_text, telegram_chat_id, telegram_message_id, telegram_message_json,
         ",".join(names) if names else None),
    )
    conn.commit()
    return cursor.lastrowid
```

The `mentions` field is set once at insert; the classifier does NOT touch it; `/redo` does NOT touch it.

## 7. Error handling

| Failure | Behavior |
|---|---|
| `/drop`, `/done`, `/redo` with bad arg (non-int) | Skip silently; log warning. Reply still made for the valid ids. |
| `/drop` with no args | `usage: /drop <id> [<id>...]` |
| `/redo` with multiple args | `usage: /redo <id>` |
| Handler body raises | Existing pattern: top-level try/except, log, send `sorry, /<cmd> failed — check logs` fallback reply. |
| Telegram reply timeout | Same as today — caught, logged, nested fallback also tried. |

## 8. Test plan

Pure unit-tested:
- `solo.mentions.extract`: empty, single, multiple, dupes, case-insensitive, no-match, embedded punctuation (`@john,`, `@john.`).
- `solo.commands._age`: just-now, 1d, 13d, 14d (boundary), 7w, 30d, 60d.
- `solo.commands._marker`: None, empty string, "alice", "alice,bob".
- `format_top3` (new): empty, three normal items, items with mentions, aging warning, with stale section, with overflow `(+N more)`.
- `format_list`: empty, mixed sections, with unclassified, skip-empty-sections.
- `format_all`: with done items, done-count header line, no-done-when-zero.

DB-level:
- Migration: idempotent; adds both new columns on an old DB.
- `insert_entry` populates `mentions` correctly (via integration with `mentions.extract`).
- `fetch_classified` filters out `done=1` rows.
- `fetch_active` (new) filters out `done=1`.
- `mark_done`, `delete_entry`, `reset_for_reclassification`: each tested.

Handler-level (extend `tests/test_commands.py`):
- `handle_list`: groups, headers count, unclassified section, empty case, disallowed chat, never-raises.
- `handle_all`: includes done items, header count format, empty case.
- `handle_drop`: deletes one, deletes many, no-op for unknown id, no-args path, never-raises.
- `handle_done`: marks one, marks many, no-op for unknown id, never-raises.
- `handle_redo`: resets one, usage error on multiple args, no-op for unknown id.
- `handle_help`: replies with static text.

## 9. Doc artifacts

- `docs/decisions/0007-drop-is-hard-delete.md` — records D1 (and acknowledges /done as the soft-state half).
- `docs/decisions/0008-mention-extraction-is-regex.md` — records D2 (`@name` regex, no LLM `is_ask` inference for V0.1).
- `docs/walkthrough.html` — add a slice 6 / "V0.1 admin surface" card; update `/top3` example; document new commands; bump "Last regen" date.
- `docs/status.md` — V0.1 complete; what's next remains V1 (`/expand`).
- No new concept primer — no new AI concept introduced.
- `README.md` — extend the env-var table is not needed (no new env vars); update the "Local dev" section to mention `/help`, `/list`, `/all`, `/drop`, `/done`, `/redo` if that section lists commands (it currently doesn't — skip).

## 10. Out of scope

- LLM-inferred external-ask flag (the 🔔 marker). Visual slot reserved.
- Per-mention follow-up ("you haven't acted on @john for 2 weeks"). V0.2+.
- Editing entry text — `/redo` re-classifies but doesn't change `raw_text`.
- `updated_at` column to power accurate "done Xd ago". Today uses `created_at`; documented.
- `/undo` for an accidental `/drop`. Hard delete is final by design.
- Pagination for `/list` or `/all`. We're at ~30 entries; Telegram's message size limit (~4096 chars) is the practical cap. Add later if needed.
- Bulk-classify command (manually trigger backlog drain). Already happens implicitly via `/top3`.
