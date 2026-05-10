import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    from solo.db import get_connection

    conn = get_connection(str(db_path))
    yield conn
    conn.close()


class TestClassifyResultSchema:
    def test_valid_payload(self):
        from solo.classifier import ClassifyResult

        r = ClassifyResult(kind="idea", summary="explore X", priority="high")
        assert r.kind == "idea"

    def test_invalid_kind_rejected(self):
        from pydantic import ValidationError

        from solo.classifier import ClassifyResult

        with pytest.raises(ValidationError):
            ClassifyResult(kind="bogus", summary="x", priority="high")

    def test_invalid_priority_rejected(self):
        from pydantic import ValidationError

        from solo.classifier import ClassifyResult

        with pytest.raises(ValidationError):
            ClassifyResult(kind="idea", summary="x", priority="urgent")

    def test_empty_summary_rejected(self):
        from pydantic import ValidationError

        from solo.classifier import ClassifyResult

        with pytest.raises(ValidationError):
            ClassifyResult(kind="idea", summary="", priority="low")


class FakeLLM:
    """Duck-typed stand-in for LLMClient. Returns scripted results or raises."""

    def __init__(self, *, results=None, errors=None):
        self.results = list(results or [])
        self.errors = list(errors or [])
        self.calls = []

    async def structured(self, prompt_name, schema, *, model, vars):
        self.calls.append({"prompt": prompt_name, "model": model, "vars": vars})
        if self.errors and self.errors[0] is not None:
            err = self.errors.pop(0)
            if self.results:
                self.results.pop(0)
            raise err
        if self.errors:
            self.errors.pop(0)
        return self.results.pop(0)


class TestClassifyPendingHappyPath:
    @pytest.mark.asyncio
    async def test_empty_backlog_returns_zero(self, conn):
        from solo.classifier import classify_pending

        llm = FakeLLM()
        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 0
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_three_rows_all_classified(self, conn):
        from solo.classifier import ClassifyResult, classify_pending
        from solo.db import insert_entry

        ids = [
            insert_entry(conn, "learn rust", 1, 1, "{}"),
            insert_entry(conn, "buy milk", 1, 2, "{}"),
            insert_entry(conn, "team morale", 1, 3, "{}"),
        ]
        llm = FakeLLM(
            results=[
                ClassifyResult(kind="idea", summary="learn rust", priority="medium"),
                ClassifyResult(kind="hard_task", summary="buy milk", priority="low"),
                ClassifyResult(kind="soft_task", summary="team morale", priority="high"),
            ]
        )

        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 3

        rows = {
            r["id"]: r
            for r in (
                dict(x)
                for x in conn.execute("SELECT * FROM entries WHERE id IN (?,?,?)", ids).fetchall()
            )
        }
        assert rows[ids[0]]["kind"] == "idea"
        assert rows[ids[1]]["kind"] == "hard_task"
        assert rows[ids[2]]["kind"] == "soft_task"
        assert all(r["classified"] == 1 for r in rows.values())

        assert [c["model"] for c in llm.calls] == ["minimax/minimax-m2.7"] * 3
        assert [c["prompt"] for c in llm.calls] == ["classifier"] * 3
        assert {c["vars"]["entry_text"] for c in llm.calls} == {
            "learn rust",
            "buy milk",
            "team morale",
        }

    @pytest.mark.asyncio
    async def test_limit_respected(self, conn):
        from solo.classifier import ClassifyResult, classify_pending
        from solo.db import insert_entry

        for i in range(10):
            insert_entry(conn, f"t{i}", 1, i, "{}")

        llm = FakeLLM(
            results=[ClassifyResult(kind="note", summary=f"t{i}", priority="low") for i in range(3)]
        )
        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7", limit=3)
        assert n == 3
        assert len(llm.calls) == 3


class TestClassifyPendingFailures:
    @pytest.mark.asyncio
    async def test_single_failure_increments_attempts(self, conn):
        from solo.classifier import classify_pending
        from solo.db import insert_entry

        rid = insert_entry(conn, "broken", 1, 1, "{}")
        llm = FakeLLM(errors=[RuntimeError("boom")])

        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 0

        row = conn.execute("SELECT * FROM entries WHERE id=?", (rid,)).fetchone()
        assert row["classification_attempts"] == 1
        assert row["classified"] == 0

    @pytest.mark.asyncio
    async def test_classify_pending_never_raises(self, conn):
        from solo.classifier import classify_pending
        from solo.db import insert_entry

        insert_entry(conn, "broken", 1, 1, "{}")
        llm = FakeLLM(errors=[RuntimeError("boom")])

        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 0

    @pytest.mark.asyncio
    async def test_mixed_batch(self, conn):
        from solo.classifier import ClassifyResult, classify_pending
        from solo.db import insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        c = insert_entry(conn, "c", 1, 3, "{}")

        llm = FakeLLM(
            results=[
                ClassifyResult(kind="idea", summary="a", priority="low"),
                None,
                ClassifyResult(kind="note", summary="c", priority="low"),
            ],
            errors=[None, RuntimeError("boom"), None],
        )

        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 2

        rows = {
            r["id"]: dict(r)
            for r in conn.execute("SELECT * FROM entries WHERE id IN (?,?,?)", (a, b, c)).fetchall()
        }
        assert rows[a]["classified"] == 1
        assert rows[b]["classified"] == 0
        assert rows[b]["classification_attempts"] == 1
        assert rows[c]["classified"] == 1

    @pytest.mark.asyncio
    async def test_row_at_max_attempts_is_skipped(self, conn):
        from solo.classifier import classify_pending
        from solo.db import insert_entry

        rid = insert_entry(conn, "stuck", 1, 1, "{}")
        conn.execute("UPDATE entries SET classification_attempts = 3 WHERE id = ?", (rid,))
        conn.commit()

        llm = FakeLLM()
        n = await classify_pending(conn, llm, model="minimax/minimax-m2.7")
        assert n == 0
        assert llm.calls == []
