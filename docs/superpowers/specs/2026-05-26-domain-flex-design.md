# Domain flex for `/top` — design

**Date:** 2026-05-26
**Status:** approved, ready for implementation
**Author:** Claude Code (Opus 4.7), driven by kb

## 1. Purpose

`/top` returns top items by priority + recency, but the priority signal alone produces "meh" results because it mixes work and life thoughts indiscriminately. On a Wednesday morning kb wants work-leaning focus; on a Saturday afternoon, the opposite.

This slice adds a **domain** axis to entries (`work` / `life` / `either`) and makes `/top` flex based on time-of-week, with a manual override.

Out of scope: conversational `/redo`. That's a separate spec — see the closing note in §10.

## 2. Resolved design questions

| # | Question | Resolution | Rationale |
|---|---|---|---|
| D1 | How does the system know an entry's domain? | **Hybrid: classifier infers + `#work`/`#life` tag overrides** | LLM gets it right most of the time; tag is the escape hatch when kb knows better at capture. |
| D2 | Filter policy on `/top` | **Lean, with `either` bucket** | Weekday `/top` surfaces `work + either`; weekend surfaces `life + either`. Ambiguous items always have a path to surface. |
| D3 | Weekend definition | **Fri ≥ 18:00 + Sat + Sun, in user TZ** | Closer to lived experience than strict Sat/Sun. |
| D4 | Manual override surface | **Optional arg: `/top work \| life \| all`** | Tiny surface, escape hatch when auto-detect is wrong. |
| D5 | Backfill of existing rows (no `domain`) | **None. NULL → treated as `either`** | Old rows surface in both modes and decay naturally. Zero migration cost. |
| D6 | "personal" vs "life" naming | **`life`** | kb's explicit preference. |
| D7 | Where does the tag get parsed? | **At capture time (`insert_entry`)**, parallel to mentions | Consistent with ADR-0008's regex-at-insert pattern. Tagged rows skip LLM domain inference but still get kind/priority/summary. |
| D8 | Does the LLM ever overwrite a tag-set domain? | **No. `apply_classification` writes `domain` only when current value is NULL** | The "tag wins" rule. Deterministic; user intent beats inference. |

## 3. Schema bump

One column added to `entries` via the existing per-column `_migrate_entries` pattern in `src/solo/db.py`. Idempotent.

```sql
ALTER TABLE entries ADD COLUMN domain TEXT;
```

Values: `'work'` / `'life'` / `'either'` / `NULL`. NULL is the "untagged, unclassified, or pre-feature row" state — the `/top` filter treats it as `either`.

No backfill on existing rows.

## 4. Tag extraction

New module `src/solo/tags.py`, parallel to `mentions.py`. Pure function:

```python
def extract(raw_text: str) -> str | None:
    """Return 'work' or 'life' if the raw text contains #work / #life, else None.

    Case-insensitive. First match wins. Tag stays in raw_text (not stripped),
    matching the mentions policy.
    """
```

Regex: `(?i)#(work|life)\b`.

`insert_entry` calls `tags.extract` and writes the result into `entries.domain` at insert time alongside the existing `mentions` write.

Conflict handling: if both `#work` and `#life` appear in the same entry, first one wins (regex returns the first match). No special warning; we log it at INFO if it ever happens.

## 5. Classifier changes

### 5.1 `ClassifyResult`

Pydantic model gains a fourth field:

```python
class ClassifyResult(BaseModel):
    kind: Literal["idea", "soft_task", "hard_task", "note"]
    summary: str = Field(min_length=1, max_length=200)
    priority: Literal["low", "medium", "high"]
    domain: Literal["work", "life", "either"]
```

### 5.2 Prompt update

`src/solo/prompts/classifier.md` gains a domain section:

```
Domain (one of):
- work    — clearly belongs to a work / professional lens
- life    — clearly outside work (family, health, hobbies, errands, personal projects)
- either  — could matter in both, or doesn't lean
```

### 5.3 `apply_classification` rule

`db.apply_classification` preserves a tag-set domain via `COALESCE`:

```sql
UPDATE entries
   SET kind = ?,
       summary = ?,
       priority = ?,
       classified = 1,
       classified_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
       domain = COALESCE(domain, ?)
 WHERE id = ?
   AND classified = 0
```

(The `classified = 0` guard already exists today; reproduced here for completeness. The only new line is `domain = COALESCE(domain, ?)`.)

Effect:
- Row tagged at capture (`domain='work'` already set) → LLM's inferred domain is ignored.
- Row untagged at capture (`domain=NULL`) → LLM's inferred domain is written.

## 6. `/top` behavior

### 6.1 Mode resolution

```
mode := arg_or_auto(context.args)

arg_or_auto:
  if args is empty                          → auto_mode(now)
  if args has 1 element and lower() == 'work'  → 'work'
  if args has 1 element and lower() == 'life'  → 'life'
  if args has 1 element and lower() == 'all'   → 'all'
  else                                      → reply "usage: /top [work|life|all]" and return
```

Mode arg is case-insensitive (`/top WORK` works). Anything else — extra args, unknown values — yields the usage message and no other side effects.

### 6.2 Auto mode (time-based)

```python
def auto_mode(now_local: datetime) -> str:
    """Return 'work' or 'life' based on local time-of-week.

    Weekend: Friday ≥ 18:00, all of Saturday, all of Sunday.
    """
    wd = now_local.weekday()  # Mon=0 ... Sun=6
    if wd == 4 and now_local.hour >= 18:  # Fri evening
        return "life"
    if wd in (5, 6):                       # Sat / Sun
        return "life"
    return "work"
```

`now_local` is computed via `zoneinfo.ZoneInfo(os.environ.get("SOLO_TIMEZONE", "Asia/Kolkata"))`. Friday-evening cutoff (18:00) is a module-level constant; promote to env var only if the need arises.

### 6.3 Filter

New pure helper in `rank.py`:

```python
def filter_by_mode(rows: list[dict], mode: str) -> list[dict]:
    """Filter classified entries by domain.

    'all'  → everything
    'work' → domain in ('work', 'either', None)
    'life' → domain in ('life', 'either', None)
    """
```

NULL is bucketed with `either` so pre-feature rows surface in both modes.

### 6.4 Handler flow

```
handle_top(update, ctx, ...):
  if not allowed: return
  mode = resolve_mode(ctx.args)   # may early-return with usage message
  try:
    await classify_pending(conn, llm, model=model)
    rows = db.fetch_classified(conn, kinds=["soft_task", "idea"])
    filtered = rank.filter_by_mode(rows, mode)
    top = rank.top(filtered)
    aging = [r for r in filtered
             if r["id"] not in {t["id"] for t in top}
             and _is_stale(r["created_at"])]
    await update.message.reply_text(
        format_top(top, aging=aging, mode=mode, auto=ctx.args == [])
    )
  except Exception: ... # existing fallback flow, unchanged
```

The aging-items section uses the same filter — weekend `/top` doesn't aging-warn about work items.

### 6.5 Rendering

`format_top` signature gains `mode` and `auto`:

```python
def format_top(
    top: list[dict],
    *,
    aging: list[dict],
    mode: str,
    auto: bool,
    now: datetime | None = None,
) -> str:
```

Header table:

| mode | auto | Header |
|---|---|---|
| work | True | `Top for today (work focus):` |
| life | True | `Top for today (life focus):` |
| work | False | `Top for today (work, manual):` |
| life | False | `Top for today (life, manual):` |
| all | False | `Top for today (everything):` |

(auto=True is impossible for mode=all by construction; it doesn't appear in auto resolution.)

Per-row format unchanged — no new badge for a row's domain. The header is the lens label.

Empty pool: `nothing to rank yet (work focus)` / `(life focus)` / `(work, manual)` / `(life, manual)` / `(everything)` — the parenthetical tells kb whether the lens is the problem.

### 6.6 Help text

```
/top [work|life|all]  — your top items right now
                        (auto: work on weekdays, life on Fri eve + weekends)
```

## 7. Files touched

| File | Change |
|---|---|
| `src/solo/db.py` | `_migrate_entries` adds `domain` column; `insert_entry` writes domain from tag extraction; `apply_classification` uses `COALESCE(domain, ?)` |
| `src/solo/tags.py` | NEW — `extract(raw_text) -> str \| None` |
| `src/solo/classifier.py` | `ClassifyResult` gains `domain` field; `apply_classification` call passes it through |
| `src/solo/prompts/classifier.md` | New domain section |
| `src/solo/rank.py` | NEW `filter_by_mode(rows, mode)`; `top()` unchanged |
| `src/solo/commands.py` | `handle_top` parses args, computes mode, applies filter; `format_top` gains `mode` + `auto`; `_HELP_TEXT` updated; new constant `_TOP_USAGE = "usage: /top [work\|life\|all]"` |
| `tests/test_tags.py` | NEW |
| `tests/test_rank.py` | New tests for `filter_by_mode` |
| `tests/test_commands.py` | Extend `TestHandleTop` with mode resolution + arg parsing tests; extend `TestFormatTop` headers |
| `tests/test_classifier.py` | Tests asserting `domain` flows through; `apply_classification` preserves a pre-set domain |
| `tests/test_db.py` | Migration idempotency for `domain` column |
| `.env.example` | Add `SOLO_TIMEZONE=Asia/Kolkata` |
| `README.md` | Mention env var; update `/top` description |
| `AGENTS.md`, `docs/status.md`, `docs/architecture.md` | Brief note on the new field + flex behavior |
| `docs/decisions/0009-domain-axis.md` | NEW ADR — capture the "hybrid signal + lean filter + no backfill" choices |

## 8. Testing

Pure unit tests dominate; one integration-style test exercises the end-to-end `/top` flow against an in-memory SQLite (mirrors the existing `TestHandleTop` fixture).

**`tags.py`:**
- `#work`, `#life`, `#WORK` all resolve correctly
- `#worker` does NOT match (`\b` boundary)
- both tags present → first wins
- no tag → None

**`rank.filter_by_mode`:**
- `mode='all'` returns the input untouched
- `mode='work'` filters to `domain in ('work', 'either', None)`
- `mode='life'` filters analogously
- NULL domain surfaces in both `work` and `life` modes

**`handle_top` args:**
- no arg → auto resolution based on a fake `now` patched via the new TZ helper
- `/top work` → forces work, header reads `(work, manual)`
- `/top life` → forces life
- `/top all` → no filter
- `/top bogus` → replies usage, no other side effects
- empty pool in non-`all` mode → header reflects the lens

**`auto_mode`:**
- Monday 10:00 → work
- Friday 17:59 → work
- Friday 18:00 → life
- Saturday 03:00 → life
- Sunday 23:59 → life

**Classifier:**
- `ClassifyResult` accepts all three domain values; rejects others
- `apply_classification` with non-NULL existing domain: domain unchanged
- `apply_classification` with NULL existing domain: domain written from arg

**Migration:**
- Fresh DB: `domain` column present
- Existing DB without column: migration adds it; re-run is no-op
- Existing rows: `domain` is NULL post-migration

No live-LLM test required for this slice; classifier inference is exercised in the existing `tests/test_classifier_live.py` once it's run against a real model.

## 9. Concept primer + ADR

- **`docs/concepts/`**: this slice doesn't introduce a new AI/agent concept worth a primer — it's an axis addition. Skip.
- **`docs/decisions/0009-domain-axis.md`**: NEW. Capture D1–D8 as the load-bearing decisions. Especially D5 (no backfill) and D8 (tag wins via COALESCE) — both are non-obvious and likely to come up later.

## 10. Out of scope (deferred)

**Conversational `/redo`** — a multi-turn flow where the bot asks per-field questions (domain / priority / summary / kind) and updates the row. This emerged during brainstorming for this slice but is its own feature: it touches conversation state, free-form vs menu prompts, and is effectively a precursor to V1's `/expand` loop. Earns its own brainstorm → spec → plan cycle.

Other deferred items:
- Stripping `#work` / `#life` tags from rendered summary text
- Promoting Friday-evening cutoff (18:00) to env var
- A `/topmode` persistent override
- LLM-driven weighted ranking that uses `domain` as a score modifier instead of a filter (would supersede ADR-0005)

## 11. Risks

| Risk | Mitigation |
|---|---|
| Classifier produces wrong domain inconsistently | Tag override (`#work` / `#life`) is the manual fix; future conversational `/redo` adds a better repair path. |
| `Asia/Kolkata` default surprises a non-IST user | `SOLO_TIMEZONE` env var; documented in `.env.example` and README. |
| Old rows feel "sticky" (always either) until they age out | Accepted. Backfill is cheap to add later if it becomes painful — same shape as a `/redo all`. |
| `domain` field bloats the classifier prompt / hurts kind accuracy | Eval harness (`scripts/eval.py`) is the regression gate. Run before merging. |
