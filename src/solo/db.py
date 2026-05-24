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
        ("done", "ALTER TABLE entries ADD COLUMN done INTEGER NOT NULL DEFAULT 0"),
        ("mentions", "ALTER TABLE entries ADD COLUMN mentions TEXT"),
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
) -> bool:
    """Returns True iff a row was actually written (i.e. row was unclassified)."""
    truncated = summary[:120]
    cursor = conn.execute(
        """
        UPDATE entries
        SET kind = ?, summary = ?, priority = ?, classified = 1
        WHERE id = ? AND classified = 0
        """,
        (kind, truncated, priority, entry_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def record_classification_failure(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute(
        "UPDATE entries SET classification_attempts = classification_attempts + 1 WHERE id = ?",
        (entry_id,),
    )
    conn.commit()


def fetch_classified(
    conn: sqlite3.Connection,
    kinds: list[str],
    limit: int = 200,
) -> list[dict]:
    """Return classified entries matching any of the given kinds, newest first.

    `kinds` is code-controlled (not user input), so building the IN-clause
    via string interpolation is safe.
    """
    if not kinds:
        return []
    placeholders = ",".join("?" * len(kinds))
    cursor = conn.execute(
        f"SELECT * FROM entries WHERE classified = 1 AND kind IN ({placeholders}) "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (*kinds, limit),
    )
    return [dict(row) for row in cursor.fetchall()]
