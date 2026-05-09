import sqlite3

import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


class TestSchema:
    def test_llm_calls_table_exists(self, conn):
        from solo.trace import ensure_schema

        ensure_schema(conn)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_calls'"
        )
        assert cursor.fetchone() is not None

    def test_llm_calls_columns(self, conn):
        from solo.trace import ensure_schema

        ensure_schema(conn)
        cursor = conn.execute("PRAGMA table_info(llm_calls)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {
            "id",
            "ts",
            "model",
            "prompt_name",
            "prompt_text",
            "response_text",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "latency_ms",
            "status",
            "error",
        }

    def test_ensure_schema_is_idempotent(self, conn):
        from solo.trace import ensure_schema

        ensure_schema(conn)
        ensure_schema(conn)  # second call must not raise

    def test_index_on_ts_exists(self, conn):
        from solo.trace import ensure_schema

        ensure_schema(conn)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_llm_calls_ts'"
        )
        assert cursor.fetchone() is not None
