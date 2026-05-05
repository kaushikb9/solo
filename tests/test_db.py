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


class TestSchema:
    def test_entries_table_exists(self, conn):
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entries'"
        )
        assert cursor.fetchone() is not None

    def test_entries_columns(self, conn):
        cursor = conn.execute("PRAGMA table_info(entries)")
        columns = {row[1] for row in cursor.fetchall()}
        assert columns == {
            "id",
            "raw_text",
            "telegram_chat_id",
            "telegram_message_id",
            "telegram_message_json",
            "created_at",
            "classified",
        }


class TestInsertEntry:
    def test_insert_returns_row_id(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(
            conn,
            raw_text="learn about embeddings",
            telegram_chat_id=123,
            telegram_message_id=456,
            telegram_message_json='{"text": "learn about embeddings"}',
        )
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_inserted_row_is_readable(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(
            conn,
            raw_text="think about team structure",
            telegram_chat_id=123,
            telegram_message_id=789,
            telegram_message_json='{"text": "think about team structure"}',
        )
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (row_id,)).fetchone()
        assert row is not None

    def test_classified_defaults_to_false(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(
            conn,
            raw_text="some thought",
            telegram_chat_id=123,
            telegram_message_id=1,
            telegram_message_json="{}",
        )
        row = conn.execute("SELECT classified FROM entries WHERE id = ?", (row_id,)).fetchone()
        assert row[0] == 0

    def test_created_at_is_auto_set(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(
            conn,
            raw_text="another thought",
            telegram_chat_id=123,
            telegram_message_id=2,
            telegram_message_json="{}",
        )
        row = conn.execute("SELECT created_at FROM entries WHERE id = ?", (row_id,)).fetchone()
        assert row[0] is not None


class TestGetRecentEntries:
    def test_returns_entries_newest_first(self, conn):
        from solo.db import get_recent_entries, insert_entry

        insert_entry(conn, "first", 1, 1, "{}")
        insert_entry(conn, "second", 1, 2, "{}")
        insert_entry(conn, "third", 1, 3, "{}")

        entries = get_recent_entries(conn, limit=3)
        assert len(entries) == 3
        assert entries[0]["raw_text"] == "third"
        assert entries[2]["raw_text"] == "first"

    def test_limit_caps_results(self, conn):
        from solo.db import get_recent_entries, insert_entry

        for i in range(10):
            insert_entry(conn, f"thought {i}", 1, i, "{}")

        entries = get_recent_entries(conn, limit=5)
        assert len(entries) == 5
