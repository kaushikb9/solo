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
    mentions TEXT,
    source TEXT NOT NULL DEFAULT 'text',
    media_path TEXT,
    media_synced INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
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
        ("source", "ALTER TABLE entries ADD COLUMN source TEXT NOT NULL DEFAULT 'text'"),
        ("media_path", "ALTER TABLE entries ADD COLUMN media_path TEXT"),
        (
            "media_synced",
            "ALTER TABLE entries ADD COLUMN media_synced INTEGER NOT NULL DEFAULT 0",
        ),
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
    source: str = "text",
    media_path: str | None = None,
) -> int:
    from solo import mentions as _mentions  # local import to avoid cycles

    names = _mentions.extract(raw_text)
    cursor = conn.execute(
        """
        INSERT INTO entries (
            raw_text, telegram_chat_id, telegram_message_id,
            telegram_message_json, mentions, source, media_path
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw_text,
            telegram_chat_id,
            telegram_message_id,
            telegram_message_json,
            ",".join(names) if names else None,
            source,
            media_path,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def fetch_unsynced_media(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    cursor = conn.execute(
        "SELECT * FROM entries WHERE media_path IS NOT NULL AND media_synced = 0 "
        "ORDER BY id ASC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def mark_media_synced(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("UPDATE entries SET media_synced = 1 WHERE id = ?", (entry_id,))
    conn.commit()


def fetch_purgeable_media(conn: sqlite3.Connection, cutoff_iso: str) -> list[dict]:
    """Media older than the cutoff that has already been synced upstream."""
    cursor = conn.execute(
        "SELECT * FROM entries WHERE media_path IS NOT NULL AND media_synced = 1 "
        "AND created_at < ?",
        (cutoff_iso,),
    )
    return [dict(row) for row in cursor.fetchall()]


def clear_media_path(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("UPDATE entries SET media_path = NULL WHERE id = ?", (entry_id,))
    conn.commit()


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Runtime-personal data (soul, cached briefing) lives here — in the DB on
    the private volume — never in the repo or the codebase."""
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) "
        "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
        "updated_at = excluded.updated_at",
        (key, value),
    )
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


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
        f"SELECT * FROM entries WHERE classified = 1 AND done = 0 "
        f"AND kind IN ({placeholders}) "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (*kinds, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


def fetch_all_entries(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    """Return entries newest-first regardless of done/classified state."""
    cursor = conn.execute(
        "SELECT * FROM entries ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


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
            "SELECT * FROM entries WHERE done = 0 ORDER BY created_at DESC, id DESC LIMIT ?",
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
