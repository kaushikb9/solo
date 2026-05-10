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


def record_call(
    conn: sqlite3.Connection,
    *,
    ts: str,
    model: str,
    prompt_name: str | None,
    prompt_text: str,
    response_text: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float | None,
    latency_ms: int,
    status: str,
    error: str | None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO llm_calls (
            ts, model, prompt_name, prompt_text, response_text,
            input_tokens, output_tokens, cost_usd, latency_ms, status, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts, model, prompt_name, prompt_text, response_text,
            input_tokens, output_tokens, cost_usd, latency_ms, status, error,
        ),
    )
    conn.commit()
    return cursor.lastrowid
