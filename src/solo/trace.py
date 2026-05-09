import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_name TEXT,
    prompt_text TEXT NOT NULL,
    response_text TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    latency_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
