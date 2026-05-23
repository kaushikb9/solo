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


def aggregate_range(
    conn: sqlite3.Connection, *, id_min: int, id_max: int
) -> dict:
    """Aggregate count/errors/cost/mean-latency over llm_calls in [id_min, id_max]."""
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                              AS count,
            COALESCE(SUM(CASE WHEN status='error' THEN 1 ELSE 0 END), 0) AS errors,
            COALESCE(SUM(cost_usd), 0.0)                          AS total_cost_usd,
            COALESCE(AVG(latency_ms), 0)                          AS mean_latency_ms
        FROM llm_calls
        WHERE id BETWEEN ? AND ?
        """,
        (id_min, id_max),
    ).fetchone()
    return {
        "count": int(row[0] or 0),
        "errors": int(row[1] or 0),
        "total_cost_usd": float(row[2] or 0.0),
        "mean_latency_ms": int(round(row[3] or 0)),
    }
