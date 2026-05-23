# Slice 4 — `/top3` and `/log` design

**Date:** 2026-05-23
**Status:** approved, ready for implementation
**Author:** Claude Code (Opus 4.7), driven by kb

## 1. Purpose

Surface the value the classifier produces. After slice 3, every entry can be turned into `(kind, summary, priority)`, but no command consumes that output yet. Slice 4 adds the two Telegram commands the V0 scope (`AGENTS.md` §V0 scope item 3) needs: `/top3` (ranked priorities) and `/log` (recent entries grouped by kind).

## 2. Resolved design questions

| # | Question | Resolution | Rationale |
|---|---|---|---|
| D1 | Heuristic vs LLM scoring pass for `/top3`? | **Heuristic only** | Classifier already produced a priority signal; second LLM call doubles cost/latency for marginal gain at V0 scale. A/B against an LLM scorer later via the slice-5 eval harness. Documented in ADR-0005. |
| D2 | Sync or async classification when `/top3` is invoked with a backlog? | **Sync — block on `classify_pending`** | User pressed the button; user gets the answer. Aligns with pull-not-push. Worst case (~50 sequential calls) is a few seconds. |
| D3 | What does `/log` show? | **Last 20 entries grouped by kind** | Familiar shape (a journal view, ordered within group); fixed cap keeps the reply bounded. |
| D4 | What gets included in `/top3`? | **`soft_task` + `idea` only** | Hard tasks belong in Apple Reminders (V2). Notes are reference-only, no action implied. |

## 3. Module shape

```
src/solo/
  rank.py        # NEW — pure top3() ranking
  commands.py    # NEW — /top3 + /log handlers; pure formatters
  db.py          # extend with fetch_classified()
  bot.py         # wire CommandHandler("top3") and CommandHandler("log")
tests/
  test_rank.py     # NEW
  test_commands.py # NEW
  test_db.py       # extend with fetch_classified tests
  test_bot.py      # no change; existing FakeMessage/FakeUpdate reused
```

### `solo.rank`

```python
_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}

def top3(entries: list[dict]) -> list[dict]:
    """Pure sort by (priority desc, created_at desc); slice to 3."""
    return sorted(
        entries,
        key=lambda r: (_PRIORITY_RANK.get(r["priority"], 0), r["created_at"]),
        reverse=True,
    )[:3]
```

Zero side effects. Tested in isolation.

### `solo.commands`

Two async handlers + two pure formatters.

```python
DEFAULT_MODEL = "minimax/minimax-m2.7"

async def handle_top3(update, context, *, conn, llm, model=DEFAULT_MODEL,
                      allowed_chats=None) -> None:
    if not _allowed(update, allowed_chats): return
    try:
        await classify_pending(conn, llm, model=model)
        rows = db.fetch_classified(conn, kinds=["soft_task", "idea"])
        top = rank.top3(rows)
        await update.message.reply_text(format_top3(top))
    except Exception:
        logger.exception("/top3 failed for chat=%d", update.effective_chat.id)

async def handle_log(update, context, *, conn, allowed_chats=None) -> None:
    if not _allowed(update, allowed_chats): return
    try:
        rows = db.get_recent_entries(conn, limit=20)
        await update.message.reply_text(format_log(rows))
    except Exception:
        logger.exception("/log failed for chat=%d", update.effective_chat.id)


def format_top3(top: list[dict]) -> str: ...
def format_log(rows: list[dict]) -> str: ...
```

Allow-list check mirrors `handle_message`: empty set ⇒ allow all; non-empty ⇒ filter.

### `solo.db.fetch_classified`

```python
def fetch_classified(
    conn: sqlite3.Connection,
    kinds: list[str],
    limit: int = 200,
) -> list[dict]:
    placeholders = ",".join("?" * len(kinds))
    cursor = conn.execute(
        f"SELECT * FROM entries WHERE classified = 1 AND kind IN ({placeholders}) "
        "ORDER BY created_at DESC LIMIT ?",
        (*kinds, limit),
    )
    return [dict(row) for row in cursor.fetchall()]
```

`kinds` is a code-controlled list (never user input), so the f-string for the IN clause is safe.

### `solo.bot` wiring

```python
def main():
    load_dotenv()
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    db_path = os.environ.get("SOLO_DB_PATH", "./data/solo.db")
    openrouter_key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("SOLO_CLASSIFIER_MODEL", "minimax/minimax-m2.7")

    raw_chats = os.environ.get("SOLO_ALLOWED_CHATS", "")
    allowed_chats = {int(c.strip()) for c in raw_chats.split(",") if c.strip()}

    conn = get_connection(db_path)
    ensure_schema(conn)  # llm_calls
    llm = LLMClient(openrouter_key, Path(db_path))

    app = ApplicationBuilder().token(token).build()

    async def _capture(update, ctx):
        await handle_message(update, ctx, conn=conn, allowed_chats=allowed_chats)
    async def _top3(update, ctx):
        await handle_top3(update, ctx, conn=conn, llm=llm, model=model,
                          allowed_chats=allowed_chats)
    async def _log(update, ctx):
        await handle_log(update, ctx, conn=conn, allowed_chats=allowed_chats)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _capture))
    app.add_handler(CommandHandler("top3", _top3))
    app.add_handler(CommandHandler("log", _log))

    logger.info("Bot starting (long polling)...")
    app.run_polling()
```

`OPENROUTER_API_KEY` becomes required at boot. Bot fails fast if missing — preferable to silent `/top3` failures.

## 4. Reply format (plain text — no emojis per AGENTS.md)

### `/top3`

```
Top 3:

1. [high · soft_task] figure out positioning for new feature
2. [medium · idea] explore embeddings for dedup
3. [low · idea] read prompt caching paper
```

Empty: `nothing to rank yet`.

### `/log`

```
Recent (20):

— idea —
  • explore embeddings for dedup (05-23)
  • prompt caching might help here (05-22)

— soft_task —
  • figure out positioning (05-23)

— hard_task —
  • buy milk (05-21)

— note —
  • compaction TTL is 5 minutes (05-20)

— unclassified —
  • some recent thought (05-23)
```

Section ordering: `idea`, `soft_task`, `hard_task`, `note`, `unclassified` (deterministic; missing sections are skipped). Date format: `MM-DD` from the ISO `created_at`.

Empty: `nothing yet`.

## 5. Error handling

| Failure | Behavior |
|---|---|
| `classify_pending` raises (shouldn't, but…) | Top-level try/except logs; reply not sent. |
| DB read fails | Top-level try/except logs; reply not sent. |
| `reply_text` fails (network) | Top-level try/except logs; nothing to recover. |
| Empty pool | Friendly message, not silence. |
| Disallowed chat | Silent drop, log warning (mirror `handle_message`). |

The bot polling loop is the asset to protect. Handlers must never raise.

## 6. Test plan (TDD order)

**`test_rank.py`:**
- `test_top3_empty_returns_empty`
- `test_top3_orders_by_priority_then_recency`
- `test_top3_caps_at_three`
- `test_top3_unknown_priority_sorts_to_bottom`

**`test_db.py` (extend):**
- `TestFetchClassified.test_returns_only_classified_rows_with_matching_kinds`
- `TestFetchClassified.test_orders_newest_first`
- `TestFetchClassified.test_respects_limit`

**`test_commands.py`:**
- `TestFormatTop3`:
  - `test_renders_three_items_with_priority_and_kind`
  - `test_empty_returns_nothing_to_rank_yet`
- `TestFormatLog`:
  - `test_groups_by_kind_in_fixed_section_order`
  - `test_skips_empty_sections`
  - `test_renders_unclassified_section`
  - `test_empty_returns_nothing_yet`
- `TestHandleTop3`:
  - `test_drains_backlog_then_replies` (FakeLLM scripted)
  - `test_filters_to_soft_task_and_idea`
  - `test_rejects_disallowed_chat`
  - `test_handler_never_raises`
- `TestHandleLog`:
  - `test_replies_with_grouped_log`
  - `test_rejects_disallowed_chat`
  - `test_handler_never_raises`

FakeMessage / FakeUpdate / FakeContext reused from `tests/test_bot.py`. FakeLLM reused from `tests/test_classifier.py` (with scripted `ClassifyResult` returns).

## 7. Out of scope for slice 4

- No new prompt files. Both commands are purely deterministic on classifier output.
- No concept primer (no new AI concept introduced).
- No `/expand` or `/review` — those are V1.
- No DB indexes — fetch_classified scans ≤ a few hundred rows at V0.
- No Markdown / MarkdownV2 Telegram formatting — plain text.

## 8. Doc artifacts produced by slice 4

- `docs/decisions/0005-heuristic-only-ranking.md` — records the D1 trade-off.
- `docs/walkthrough.html` updated: slice 4 card flipped done; flow diagram colors updated.
- `docs/status.md` updated: slice 4 done; "what's next" = slice 5 (eval harness).
