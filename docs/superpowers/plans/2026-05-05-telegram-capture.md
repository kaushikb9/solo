# Telegram Capture → SQLite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept raw text messages from Telegram, store them as rows in SQLite, and reply "captured". No classification, no LLM — just the capture loop.

**Architecture:** A Telegram bot using `python-telegram-bot` with long polling receives messages, checks an allowlist of chat IDs, writes each message to an `entries` table in SQLite, and replies with "captured". The DB module owns schema creation and all queries. The bot module owns Telegram interaction and wires handlers.

**Tech Stack:** Python 3.12, `python-telegram-bot` (async, long polling), SQLite via `sqlite3` stdlib, `python-dotenv` for config, `pytest` for tests, `uv` for everything.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/solo/db.py` | SQLite connection, schema creation (`entries` table), insert/query functions |
| `src/solo/bot.py` | Telegram bot setup, message handler, command dispatch, allowlist check |
| `tests/test_db.py` | Tests for DB layer (insert, query, schema) |
| `tests/test_bot.py` | Tests for bot handlers (capture, allowlist, commands) |

---

### Task 1: SQLite schema and insert — failing tests

**Files:**
- Create: `tests/test_db.py`

- [ ] **Step 1: Create the tests directory and write failing tests for `db.py`**

```python
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    from solo.db import get_connection

    return get_connection(str(db_path))


class TestSchema:
    def test_entries_table_exists(self, conn):
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entries'"
        )
        assert cursor.fetchone() is not None

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
        }


class TestInsertEntry:
    def test_insert_returns_row_id(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(
            conn,
            raw_text="learn about embeddings",
            telegram_chat_id=123,
            telegram_message_id=456,
            telegram_message_json='{"text": "learn about embeddings"}',
        )
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_inserted_row_is_readable(self, conn):
        from solo.db import insert_entry

        insert_entry(
            conn,
            raw_text="think about team structure",
            telegram_chat_id=123,
            telegram_message_id=789,
            telegram_message_json='{"text": "think about team structure"}',
        )
        row = conn.execute("SELECT * FROM entries WHERE id = 1").fetchone()
        assert row is not None

    def test_classified_defaults_to_false(self, conn):
        from solo.db import insert_entry

        insert_entry(
            conn,
            raw_text="some thought",
            telegram_chat_id=123,
            telegram_message_id=1,
            telegram_message_json="{}",
        )
        row = conn.execute("SELECT classified FROM entries WHERE id = 1").fetchone()
        assert row[0] == 0

    def test_created_at_is_auto_set(self, conn):
        from solo.db import insert_entry

        insert_entry(
            conn,
            raw_text="another thought",
            telegram_chat_id=123,
            telegram_message_id=2,
            telegram_message_json="{}",
        )
        row = conn.execute("SELECT created_at FROM entries WHERE id = 1").fetchone()
        assert row[0] is not None


class TestGetRecentEntries:
    def test_returns_entries_newest_first(self, conn):
        from solo.db import get_recent_entries, insert_entry

        insert_entry(conn, "first", 1, 1, "{}")
        insert_entry(conn, "second", 1, 2, "{}")
        insert_entry(conn, "third", 1, 3, "{}")

        entries = get_recent_entries(conn, limit=3)
        assert len(entries) == 3
        assert entries[0]["raw_text"] == "third"
        assert entries[2]["raw_text"] == "first"

    def test_limit_caps_results(self, conn):
        from solo.db import get_recent_entries, insert_entry

        for i in range(10):
            insert_entry(conn, f"thought {i}", 1, i, "{}")

        entries = get_recent_entries(conn, limit=5)
        assert len(entries) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solo.db'` or `ImportError`

---

### Task 2: SQLite schema and insert — implementation

**Files:**
- Create: `src/solo/db.py`

- [ ] **Step 3: Implement `db.py`**

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
    classified INTEGER NOT NULL DEFAULT 0
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
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
        "SELECT * FROM entries ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/solo/db.py tests/test_db.py
git commit -m "feat: add SQLite schema and entry insert/query functions"
```

---

### Task 3: Telegram bot — failing tests

**Files:**
- Create: `tests/test_bot.py`

The bot uses `python-telegram-bot`'s async API. Tests mock the Telegram objects to avoid a live bot token.

- [ ] **Step 6: Write failing tests for the bot message handler**

```python
import json

import pytest

from solo.bot import handle_message


class FakeMessage:
    def __init__(self, text, chat_id=123, message_id=1):
        self.text = text
        self.message_id = message_id
        self.chat = type("Chat", (), {"id": chat_id})()
        self.to_json = lambda: json.dumps({"text": text, "chat_id": chat_id})
        self._replied = None

    async def reply_text(self, text):
        self._replied = text


class FakeUpdate:
    def __init__(self, message):
        self.message = message
        self.effective_chat = message.chat


class FakeContext:
    pass


@pytest.fixture
def db_conn(tmp_path):
    from solo.db import get_connection

    return get_connection(str(tmp_path / "test.db"))


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_captures_text_and_replies(self, db_conn):
        msg = FakeMessage("think about hiring plan")
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats={123})

        assert msg._replied == "captured"
        row = db_conn.execute("SELECT raw_text FROM entries").fetchone()
        assert row["raw_text"] == "think about hiring plan"

    @pytest.mark.asyncio
    async def test_stores_telegram_metadata(self, db_conn):
        msg = FakeMessage("some thought", chat_id=999, message_id=42)
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats={999})

        row = db_conn.execute("SELECT telegram_chat_id, telegram_message_id FROM entries").fetchone()
        assert row["telegram_chat_id"] == 999
        assert row["telegram_message_id"] == 42

    @pytest.mark.asyncio
    async def test_rejects_disallowed_chat(self, db_conn):
        msg = FakeMessage("sneaky thought", chat_id=666)
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats={123})

        assert msg._replied is None
        row = db_conn.execute("SELECT count(*) as c FROM entries").fetchone()
        assert row["c"] == 0

    @pytest.mark.asyncio
    async def test_ignores_empty_message(self, db_conn):
        msg = FakeMessage(None)
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats={123})

        assert msg._replied is None

    @pytest.mark.asyncio
    async def test_allows_all_chats_when_allowlist_empty(self, db_conn):
        msg = FakeMessage("open thought", chat_id=999)
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats=set())

        assert msg._replied == "captured"
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `uv run pytest tests/test_bot.py -v`
Expected: FAIL — `ImportError: cannot import name 'handle_message' from 'solo.bot'`

---

### Task 4: Telegram bot — implementation

**Files:**
- Create: `src/solo/bot.py`

- [ ] **Step 8: Implement `bot.py`**

```python
import json
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from solo.db import get_connection, insert_entry

load_dotenv()

logger = logging.getLogger(__name__)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn=None,
    allowed_chats: set[int] | None = None,
) -> None:
    if update.message is None or update.message.text is None:
        return

    chat_id = update.effective_chat.id

    if allowed_chats and chat_id not in allowed_chats:
        logger.warning("Rejected message from chat_id=%d", chat_id)
        return

    insert_entry(
        conn,
        raw_text=update.message.text,
        telegram_chat_id=chat_id,
        telegram_message_id=update.message.message_id,
        telegram_message_json=update.message.to_json(),
    )
    await update.message.reply_text("captured")


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    db_path = os.environ.get("SOLO_DB_PATH", "./data/solo.db")

    raw_chats = os.environ.get("SOLO_ALLOWED_CHATS", "")
    allowed_chats = {int(c.strip()) for c in raw_chats.split(",") if c.strip()}

    conn = get_connection(db_path)

    app = ApplicationBuilder().token(token).build()

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_message(update, context, conn=conn, allowed_chats=allowed_chats)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handler))

    logger.info("Bot starting (long polling)...")
    app.run_polling()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
```

- [ ] **Step 9: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All 12 tests PASS (7 db + 5 bot)

- [ ] **Step 10: Run linter**

Run: `uv run ruff check .`
Expected: Clean (no errors)

- [ ] **Step 11: Commit**

```bash
git add src/solo/bot.py tests/test_bot.py
git commit -m "feat: add Telegram bot with capture handler and allowlist"
```

---

### Task 5: Add `pytest-asyncio` dev dependency

**Files:**
- Modify: `pyproject.toml`

The bot tests use `@pytest.mark.asyncio`. This requires `pytest-asyncio`.

- [ ] **Step 12: Add `pytest-asyncio` to dev dependencies**

In `pyproject.toml`, change the dev dependency group to:

```toml
[dependency-groups]
dev = [
  "ruff>=0.6",
  "pytest>=8.0",
  "pytest-asyncio>=0.24",
]
```

- [ ] **Step 13: Sync dependencies**

Run: `uv sync`
Expected: `pytest-asyncio` installed

- [ ] **Step 14: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add pytest-asyncio dev dependency"
```

> **Note:** This task should be done *before* running the bot tests in Task 3. The plan lists it separately for clarity, but in execution, do this first if `pytest.mark.asyncio` errors appear.

---

### Task 6: Ensure `data/` directory exists for local dev

**Files:**
- Modify: `.gitignore`

The bot defaults `SOLO_DB_PATH` to `./data/solo.db`. Ensure `data/` is gitignored (the DB file should never be committed) but the directory exists.

- [ ] **Step 15: Check `.gitignore` covers `data/`**

Run: `grep -n 'data/' .gitignore`

If `data/` or `*.db` is not listed, add:

```
data/
```

- [ ] **Step 16: Create `data/` with a `.gitkeep`**

Run: `mkdir -p data && touch data/.gitkeep`

- [ ] **Step 17: Commit if changes were made**

```bash
git add .gitignore data/.gitkeep
git commit -m "chore: gitignore data/ and keep directory for local dev"
```

---

### Task 7: Manual smoke test

No automated test replaces running the actual bot. This is the final verification.

- [ ] **Step 18: Create a `.env` file from `.env.example`**

Copy `.env.example` to `.env` and fill in:
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `SOLO_ALLOWED_CHATS` — your chat ID (get from @userinfobot)

- [ ] **Step 19: Run the bot**

Run: `uv run python -m solo.bot`

Expected: `Bot starting (long polling)...` in the terminal

- [ ] **Step 20: Send a message in Telegram**

Send any text message to your bot. Expected:
- Bot replies with `captured`
- A row appears in `data/solo.db`:

```bash
sqlite3 data/solo.db "SELECT id, raw_text, created_at FROM entries"
```

- [ ] **Step 21: Test the allowlist**

Send a message from a different Telegram account (or temporarily change `SOLO_ALLOWED_CHATS` to a wrong ID). Expected: no reply, no row inserted.

---

### Task 8: Update `docs/status.md`

**Files:**
- Modify: `docs/status.md`

- [ ] **Step 22: Update status doc**

Replace the content of `docs/status.md` with the current state reflecting that Telegram capture is implemented. Update `Last updated`, `Current state`, and `What's next` (next slice: `LLMClient` + trace table).

- [ ] **Step 23: Commit**

```bash
git add docs/status.md
git commit -m "docs: update status after Telegram capture implementation"
```
