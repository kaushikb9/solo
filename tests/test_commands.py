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
