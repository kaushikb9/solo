import json
from datetime import UTC, datetime

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


class TestAge:
    def test_just_now(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        assert _age("2026-05-24T09:30:00.000Z", now=now) == "just now"

    def test_days(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        assert _age("2026-05-20T10:00:00.000Z", now=now) == "4d"

    def test_just_under_two_weeks(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        assert _age("2026-05-12T10:00:00.000Z", now=now) == "12d"

    def test_weeks(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        # 21 days = 3w
        assert _age("2026-05-03T10:00:00.000Z", now=now) == "3w"

    def test_months(self):
        from solo.commands import _age

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        # 90 days = 3mo
        assert _age("2026-02-23T10:00:00.000Z", now=now) == "3mo"


class TestMarker:
    def test_none_returns_ideation(self):
        from solo.commands import _marker

        assert _marker(None) == "💡"

    def test_empty_string_returns_ideation(self):
        from solo.commands import _marker

        assert _marker("") == "💡"

    def test_single_mention(self):
        from solo.commands import _marker

        assert _marker("alice") == "👥 @alice"

    def test_multiple_mentions(self):
        from solo.commands import _marker

        assert _marker("alice,bob") == "👥 @alice @bob"


class TestFormatTop3:
    def _row(self, **overrides):
        base = {
            "id": 1,
            "kind": "idea",
            "priority": "med",
            "summary": "embeddings for dedup",
            "mentions": None,
            "created_at": "2026-05-23T10:00:00.000Z",
        }
        base.update(overrides)
        return base

    def test_empty_returns_nothing_to_rank_yet(self):
        from solo.commands import format_top3

        assert format_top3([], aging=[]) == "nothing to rank yet"

    def test_renders_three_terse_items_with_ideation_marker(self):
        from solo.commands import format_top3

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        top = [
            self._row(
                id=1, summary="positioning for new feature",
                created_at="2026-05-23T10:00:00.000Z",
            ),
            self._row(
                id=2, summary="embeddings for dedup",
                created_at="2026-05-20T10:00:00.000Z",
            ),
            self._row(
                id=3, summary="prompt caching paper",
                created_at="2026-05-09T10:00:00.000Z",
            ),
        ]
        out = format_top3(top, aging=[], now=now)
        assert "Top 3 for today:" in out
        assert "1️⃣ 💡 positioning for new feature (1d)" in out
        assert "2️⃣ 💡 embeddings for dedup (4d)" in out
        # 15d → renders as "2w" and gets the ⚠️ (stale threshold is >14d)
        assert "3️⃣ 💡 prompt caching paper (2w) ⚠️" in out

    def test_renders_mention_marker(self):
        from solo.commands import format_top3

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        top = [self._row(mentions="ashish", summary="1BHK reimbursement")]
        out = format_top3(top, aging=[], now=now)
        assert "1️⃣ 👥 @ashish 1BHK reimbursement" in out

    def test_includes_aging_section(self):
        from solo.commands import format_top3

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        top = [self._row(id=1, summary="t1", created_at="2026-05-23T10:00:00.000Z")]
        aging = [
            self._row(
                id=10, summary="mentoring plan",
                created_at="2026-05-03T10:00:00.000Z",
            ),
            self._row(
                id=11, summary="team morale", mentions="john",
                created_at="2026-04-15T10:00:00.000Z",
            ),
        ]
        out = format_top3(top, aging=aging, now=now)
        assert "⚠️ Also aging (>14d, not in top 3):" in out
        assert "💡 mentoring plan (3w)" in out
        assert "👥 @john team morale" in out

    def test_aging_section_caps_at_five_with_overflow_note(self):
        from solo.commands import format_top3

        now = datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC)
        top = [self._row(id=1, summary="t1", created_at="2026-05-23T10:00:00.000Z")]
        aging = [
            self._row(
                id=10 + i, summary=f"stale {i}",
                created_at="2026-04-15T10:00:00.000Z",
            )
            for i in range(8)
        ]
        out = format_top3(top, aging=aging, now=now)
        # First 5 listed, then "(+3 more)"
        assert "(+3 more)" in out


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
                ClassifyResult(kind="idea", summary="explore embeddings", priority="medium"),
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
    async def test_handler_replies_fallback_on_llm_failure(self, db_conn):
        from solo.commands import handle_top3
        from solo.db import insert_entry

        insert_entry(db_conn, "broken", 1, 1, "{}")
        llm = FakeLLM(errors=[RuntimeError("boom")])

        msg = FakeMessage("/top3")
        update = FakeUpdate(msg)
        await handle_top3(update, FakeContext(), conn=db_conn, llm=llm)
        # classify_pending swallows its own errors; the user still sees the
        # "nothing to rank yet" path because no rows became classified.
        assert msg._replied == "nothing to rank yet"

    @pytest.mark.asyncio
    async def test_handler_replies_fallback_on_db_failure(self, db_conn):
        from solo.commands import handle_top3

        db_conn.close()  # force a DB error inside fetch_classified

        msg = FakeMessage("/top3")
        update = FakeUpdate(msg)
        await handle_top3(update, FakeContext(), conn=db_conn, llm=FakeLLM())
        # Handler caught the DB error and sent the fallback message.
        assert msg._replied == "sorry, /top3 failed — check logs"


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
    async def test_handler_replies_fallback_on_db_failure(self, db_conn):
        from solo.commands import handle_log

        db_conn.close()
        msg = FakeMessage("/log")
        update = FakeUpdate(msg)
        await handle_log(update, FakeContext(), conn=db_conn)
        assert msg._replied == "sorry, /log failed — check logs"

    def test_format_log_renders_short_date_suffix(self):
        from solo.commands import format_log

        rows = [
            {
                "kind": "idea",
                "summary": "i1",
                "raw_text": "i1",
                "classified": 1,
                "created_at": "2026-05-23T10:00:00.000Z",
            }
        ]
        out = format_log(rows)
        assert "i1 (05-23)" in out
