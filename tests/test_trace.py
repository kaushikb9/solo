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


class TestAggregateRange:
    def test_aggregates_cost_and_latency_within_range(self, conn):
        from solo.trace import aggregate_range, ensure_schema, record_call

        ensure_schema(conn)
        for i, latency in enumerate([100, 200, 300]):
            record_call(
                conn,
                ts=f"2026-05-23T10:00:{i:02d}Z",
                model="minimax/minimax-m2.7",
                prompt_name="classifier",
                prompt_text="x",
                response_text="y",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.0001,
                latency_ms=latency,
                status="ok",
                error=None,
            )

        ids = [r[0] for r in conn.execute("SELECT id FROM llm_calls ORDER BY id").fetchall()]
        out = aggregate_range(conn, id_min=ids[0], id_max=ids[-1])

        assert out["count"] == 3
        assert out["errors"] == 0
        assert abs(out["total_cost_usd"] - 0.0003) < 1e-9
        assert out["mean_latency_ms"] == 200

    def test_aggregate_range_empty_returns_zeros(self, conn):
        from solo.trace import aggregate_range, ensure_schema

        ensure_schema(conn)
        out = aggregate_range(conn, id_min=1, id_max=1)
        assert out == {
            "count": 0,
            "errors": 0,
            "total_cost_usd": 0.0,
            "mean_latency_ms": 0,
        }

    def test_aggregate_range_with_rows_present_but_out_of_range(self, conn):
        from solo.trace import aggregate_range, ensure_schema, record_call

        ensure_schema(conn)
        record_call(
            conn,
            ts="2026-05-23T10:00:00Z",
            model="minimax/minimax-m2.7",
            prompt_name="classifier",
            prompt_text="x",
            response_text="y",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0001,
            latency_ms=100,
            status="ok",
            error=None,
        )

        # Row was inserted at id=1; query a range that excludes it.
        out = aggregate_range(conn, id_min=999, id_max=1000)
        assert out == {
            "count": 0,
            "errors": 0,
            "total_cost_usd": 0.0,
            "mean_latency_ms": 0,
        }

    def test_aggregate_range_counts_errors(self, conn):
        from solo.trace import aggregate_range, ensure_schema, record_call

        ensure_schema(conn)
        record_call(
            conn,
            ts="2026-05-23T10:00:00Z",
            model="minimax/minimax-m2.7",
            prompt_name="classifier",
            prompt_text="x",
            response_text=None,
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            latency_ms=50,
            status="error",
            error="boom",
        )

        ids = [r[0] for r in conn.execute("SELECT id FROM llm_calls").fetchall()]
        out = aggregate_range(conn, id_min=ids[0], id_max=ids[0])
        assert out["count"] == 1
        assert out["errors"] == 1
