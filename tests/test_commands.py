import json

import pytest


class FakeMessage:
    def __init__(self, text=None, chat_id=123, message_id=1):
        self.text = text
        self.message_id = message_id
        self.chat = type("Chat", (), {"id": chat_id})()
        self.to_json = lambda: json.dumps({"text": text, "chat_id": chat_id})
        self._replied = None

    async def reply_text(self, text):
        self._replied = text


class FakeUpdate:
    def __init__(self, message):
        self.message = message
        self.effective_chat = message.chat


class FakeContext:
    pass


class FakeLLM:
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


@pytest.fixture
def db_conn(tmp_path):
    from solo.db import get_connection

    conn = get_connection(str(tmp_path / "test.db"))
    yield conn
    conn.close()


class TestFormatTop3:
    def test_renders_three_items_with_priority_and_kind(self):
        from solo.commands import format_top3

        items = [
            {"priority": "high", "kind": "soft_task", "summary": "positioning"},
            {"priority": "medium", "kind": "idea", "summary": "embeddings"},
            {"priority": "low", "kind": "idea", "summary": "caching paper"},
        ]
        out = format_top3(items)
        assert "Top 3:" in out
        assert "1. [high · soft_task] positioning" in out
        assert "2. [medium · idea] embeddings" in out
        assert "3. [low · idea] caching paper" in out

    def test_empty_returns_nothing_to_rank_yet(self):
        from solo.commands import format_top3

        assert format_top3([]) == "nothing to rank yet"


class TestFormatLog:
    def test_groups_by_kind_in_fixed_section_order(self):
        from solo.commands import format_log

        rows = [
            {
                "kind": "note",
                "summary": "n1",
                "raw_text": "n1",
                "classified": 1,
                "created_at": "2026-05-22T10:00:00Z",
            },
            {
                "kind": "idea",
                "summary": "i1",
                "raw_text": "i1",
                "classified": 1,
                "created_at": "2026-05-23T10:00:00Z",
            },
            {
                "kind": "soft_task",
                "summary": "s1",
                "raw_text": "s1",
                "classified": 1,
                "created_at": "2026-05-21T10:00:00Z",
            },
        ]
        out = format_log(rows)
        idea_pos = out.find("— idea —")
        soft_pos = out.find("— soft_task —")
        note_pos = out.find("— note —")
        assert idea_pos < soft_pos < note_pos

    def test_skips_empty_sections(self):
        from solo.commands import format_log

        rows = [
            {
                "kind": "idea",
                "summary": "i1",
                "raw_text": "i1",
                "classified": 1,
                "created_at": "2026-05-23T10:00:00Z",
            }
        ]
        out = format_log(rows)
        assert "— idea —" in out
        assert "— soft_task —" not in out
        assert "— hard_task —" not in out
        assert "— note —" not in out

    def test_renders_unclassified_section(self):
        from solo.commands import format_log

        rows = [
            {
                "kind": None,
                "summary": None,
                "raw_text": "raw thought",
                "classified": 0,
                "created_at": "2026-05-23T10:00:00Z",
            },
        ]
        out = format_log(rows)
        assert "— unclassified —" in out
        assert "raw thought" in out

    def test_empty_returns_nothing_yet(self):
        from solo.commands import format_log

        assert format_log([]) == "nothing yet"


class TestHandleTop3:
    @pytest.mark.asyncio
    async def test_drains_backlog_then_replies(self, db_conn):
        from solo.classifier import ClassifyResult
        from solo.commands import handle_top3
        from solo.db import insert_entry

        insert_entry(db_conn, "explore embeddings", 1, 1, "{}")
        insert_entry(db_conn, "positioning", 1, 2, "{}")
        llm = FakeLLM(
            results=[
                ClassifyResult(
                    kind="idea", summary="explore embeddings", priority="medium"
                ),
                ClassifyResult(kind="soft_task", summary="positioning", priority="high"),
            ]
        )

        msg = FakeMessage("/top3")
        update = FakeUpdate(msg)
        await handle_top3(update, FakeContext(), conn=db_conn, llm=llm)

        assert msg._replied is not None
        assert "Top 3:" in msg._replied
        assert "[high · soft_task] positioning" in msg._replied
        assert "[medium · idea] explore embeddings" in msg._replied
        assert len(llm.calls) == 2

    @pytest.mark.asyncio
    async def test_filters_to_soft_task_and_idea(self, db_conn):
        from solo.commands import handle_top3
        from solo.db import apply_classification, insert_entry

        a = insert_entry(db_conn, "soft", 1, 1, "{}")
        b = insert_entry(db_conn, "idea", 1, 2, "{}")
        c = insert_entry(db_conn, "hard", 1, 3, "{}")
        d = insert_entry(db_conn, "note", 1, 4, "{}")
        apply_classification(db_conn, a, "soft_task", "soft", "high")
        apply_classification(db_conn, b, "idea", "idea", "high")
        apply_classification(db_conn, c, "hard_task", "hard", "high")
        apply_classification(db_conn, d, "note", "note", "high")

        msg = FakeMessage("/top3")
        update = FakeUpdate(msg)
        await handle_top3(update, FakeContext(), conn=db_conn, llm=FakeLLM())

        assert "soft" in msg._replied
        assert "idea" in msg._replied
        assert "hard" not in msg._replied
        assert "note" not in msg._replied

    @pytest.mark.asyncio
    async def test_empty_pool_returns_nothing_message(self, db_conn):
        from solo.commands import handle_top3

        msg = FakeMessage("/top3")
        update = FakeUpdate(msg)
        await handle_top3(update, FakeContext(), conn=db_conn, llm=FakeLLM())

        assert msg._replied == "nothing to rank yet"

    @pytest.mark.asyncio
    async def test_rejects_disallowed_chat(self, db_conn):
        from solo.commands import handle_top3

        msg = FakeMessage("/top3", chat_id=666)
        update = FakeUpdate(msg)
        await handle_top3(
            update,
            FakeContext(),
            conn=db_conn,
            llm=FakeLLM(),
            allowed_chats={123},
        )

        assert msg._replied is None

    @pytest.mark.asyncio
    async def test_handler_never_raises(self, db_conn):
        from solo.commands import handle_top3
        from solo.db import insert_entry

        insert_entry(db_conn, "broken", 1, 1, "{}")
        llm = FakeLLM(errors=[RuntimeError("boom")])
        db_conn.close()  # force DB error inside handler

        msg = FakeMessage("/top3")
        update = FakeUpdate(msg)
        await handle_top3(update, FakeContext(), conn=db_conn, llm=llm)
        # Should not raise — the assertion is that we got here.


class TestHandleLog:
    @pytest.mark.asyncio
    async def test_replies_with_grouped_log(self, db_conn):
        from solo.commands import handle_log
        from solo.db import apply_classification, insert_entry

        a = insert_entry(db_conn, "i1", 1, 1, "{}")
        b = insert_entry(db_conn, "s1", 1, 2, "{}")
        apply_classification(db_conn, a, "idea", "i1", "high")
        apply_classification(db_conn, b, "soft_task", "s1", "low")

        msg = FakeMessage("/log")
        update = FakeUpdate(msg)
        await handle_log(update, FakeContext(), conn=db_conn)

        assert "— idea —" in msg._replied
        assert "— soft_task —" in msg._replied
        assert "i1" in msg._replied
        assert "s1" in msg._replied

    @pytest.mark.asyncio
    async def test_empty_returns_nothing_yet(self, db_conn):
        from solo.commands import handle_log

        msg = FakeMessage("/log")
        update = FakeUpdate(msg)
        await handle_log(update, FakeContext(), conn=db_conn)

        assert msg._replied == "nothing yet"

    @pytest.mark.asyncio
    async def test_rejects_disallowed_chat(self, db_conn):
        from solo.commands import handle_log

        msg = FakeMessage("/log", chat_id=666)
        update = FakeUpdate(msg)
        await handle_log(update, FakeContext(), conn=db_conn, allowed_chats={123})

        assert msg._replied is None

    @pytest.mark.asyncio
    async def test_handler_never_raises(self, db_conn):
        from solo.commands import handle_log

        db_conn.close()
        msg = FakeMessage("/log")
        update = FakeUpdate(msg)
        await handle_log(update, FakeContext(), conn=db_conn)
        # No raise — pass.
