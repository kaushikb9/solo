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
        "SELECT * FROM entries ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]
