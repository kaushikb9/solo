import json

import pytest

from solo.bot import handle_message


class FakeMessage:
    def __init__(self, text, chat_id=123, message_id=1):
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


@pytest.fixture
def db_conn(tmp_path):
    from solo.db import get_connection

    conn = get_connection(str(tmp_path / "test.db"))
    yield conn
    conn.close()


class TestHandleMessage:
    @pytest.mark.asyncio
    async def test_captures_text_and_replies(self, db_conn):
        msg = FakeMessage("think about hiring plan")
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats={123})

        assert msg._replied == "captured"
        row = db_conn.execute("SELECT raw_text FROM entries").fetchone()
        assert row["raw_text"] == "think about hiring plan"

    @pytest.mark.asyncio
    async def test_stores_telegram_metadata(self, db_conn):
        msg = FakeMessage("some thought", chat_id=999, message_id=42)
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats={999})

        row = db_conn.execute(
            "SELECT telegram_chat_id, telegram_message_id FROM entries"
        ).fetchone()
        assert row["telegram_chat_id"] == 999
        assert row["telegram_message_id"] == 42

    @pytest.mark.asyncio
    async def test_rejects_disallowed_chat(self, db_conn):
        msg = FakeMessage("sneaky thought", chat_id=666)
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats={123})

        assert msg._replied is None
        row = db_conn.execute("SELECT count(*) as c FROM entries").fetchone()
        assert row["c"] == 0

    @pytest.mark.asyncio
    async def test_ignores_empty_message(self, db_conn):
        msg = FakeMessage(None)
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats={123})

        assert msg._replied is None

    @pytest.mark.asyncio
    async def test_allows_all_chats_when_allowlist_empty(self, db_conn):
        msg = FakeMessage("open thought", chat_id=999)
        update = FakeUpdate(msg)
        ctx = FakeContext()

        await handle_message(update, ctx, conn=db_conn, allowed_chats=set())

        assert msg._replied == "captured"
