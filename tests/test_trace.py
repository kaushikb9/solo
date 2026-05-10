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


class TestRecordCall:
    def test_returns_row_id(self, conn):
        from solo.trace import ensure_schema, record_call

        ensure_schema(conn)
        row_id = record_call(
            conn,
            ts="2026-05-09T12:00:00Z",
            model="minimax/minimax-m2.7",
            prompt_name="classifier",
            prompt_text='[{"role":"user","content":"hi"}]',
            response_text="hello",
            input_tokens=5,
            output_tokens=2,
            cost_usd=0.0001,
            latency_ms=345,
            status="ok",
            error=None,
        )
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_inserted_row_is_readable(self, conn):
        from solo.trace import ensure_schema, record_call

        ensure_schema(conn)
        row_id = record_call(
            conn,
            ts="2026-05-09T12:00:00Z",
            model="minimax/minimax-m2.7",
            prompt_name="classifier",
            prompt_text='[{"role":"user","content":"hi"}]',
            response_text="hello",
            input_tokens=5,
            output_tokens=2,
            cost_usd=0.0001,
            latency_ms=345,
            status="ok",
            error=None,
        )
        row = conn.execute("SELECT * FROM llm_calls WHERE id = ?", (row_id,)).fetchone()
        assert row["model"] == "minimax/minimax-m2.7"
        assert row["status"] == "ok"
        assert row["response_text"] == "hello"
        assert row["error"] is None

    def test_error_row_has_null_response(self, conn):
        from solo.trace import ensure_schema, record_call

        ensure_schema(conn)
        record_call(
            conn,
            ts="2026-05-09T12:00:00Z",
            model="minimax/minimax-m2.7",
            prompt_name=None,
            prompt_text="[]",
            response_text=None,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            latency_ms=120,
            status="error",
            error="connection refused",
        )
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
        assert row["status"] == "error"
        assert row["response_text"] is None
        assert row["cost_usd"] is None
        assert row["error"] == "connection refused"

    def test_invalid_status_rejected(self, conn):
        from solo.trace import ensure_schema, record_call

        ensure_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            record_call(
                conn,
                ts="2026-05-09T12:00:00Z",
                model="x",
                prompt_name=None,
                prompt_text="[]",
                response_text=None,
                input_tokens=None,
                output_tokens=None,
                cost_usd=None,
                latency_ms=1,
                status="weird",  # violates CHECK constraint
                error=None,
            )
