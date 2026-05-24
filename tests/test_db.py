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
            "kind",
            "summary",
            "priority",
            "classification_attempts",
            "done",
            "mentions",
        }

    def test_done_and_mentions_have_correct_defaults(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(conn, "plain thought", 1, 1, "{}")
        row = conn.execute(
            "SELECT done, mentions FROM entries WHERE id = ?", (row_id,)
        ).fetchone()
        assert row[0] == 0  # done defaults to 0
        assert row[1] is None  # mentions NULL when no @-names

    def test_new_classification_columns_have_correct_defaults(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(conn, "x", 1, 1, "{}")
        row = conn.execute(
            "SELECT kind, summary, priority, classification_attempts FROM entries WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None
        assert row[3] == 0


class TestMigration:
    def test_migration_adds_columns_to_old_db(self, tmp_path):
        import sqlite3

        from solo.db import get_connection

        path = tmp_path / "old.db"
        old = sqlite3.connect(str(path))
        old.executescript(
            """
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                telegram_chat_id INTEGER NOT NULL,
                telegram_message_id INTEGER NOT NULL,
                telegram_message_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                classified INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO entries (
                raw_text, telegram_chat_id,
                telegram_message_id, telegram_message_json
            ) VALUES ('legacy thought', 1, 1, '{}');
            """
        )
        old.commit()
        old.close()

        conn = get_connection(str(path))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
        assert {
            "kind",
            "summary",
            "priority",
            "classification_attempts",
            "done",
            "mentions",
        }.issubset(cols)

        row = conn.execute(
            "SELECT raw_text, classification_attempts, done, mentions FROM entries"
        ).fetchone()
        assert row[0] == "legacy thought"
        assert row[1] == 0
        assert row[2] == 0
        assert row[3] is None
        conn.close()

    def test_migration_is_idempotent(self, tmp_path):
        from solo.db import get_connection

        path = tmp_path / "x.db"
        get_connection(str(path)).close()
        get_connection(str(path)).close()


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

    def test_insert_extracts_mentions(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(
            conn,
            raw_text="loop @alice and @bob on the doc",
            telegram_chat_id=1,
            telegram_message_id=1,
            telegram_message_json="{}",
        )
        row = conn.execute("SELECT mentions FROM entries WHERE id=?", (row_id,)).fetchone()
        assert row["mentions"] == "alice,bob"

    def test_insert_with_no_mentions_stores_null(self, conn):
        from solo.db import insert_entry

        row_id = insert_entry(
            conn,
            raw_text="plain thought, no names",
            telegram_chat_id=1,
            telegram_message_id=1,
            telegram_message_json="{}",
        )
        row = conn.execute("SELECT mentions FROM entries WHERE id=?", (row_id,)).fetchone()
        assert row["mentions"] is None


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


class TestFetchUnclassified:
    def test_returns_only_unclassified_rows(self, conn):
        from solo.db import fetch_unclassified, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        conn.execute("UPDATE entries SET classified=1 WHERE id=?", (a,))
        conn.commit()

        rows = fetch_unclassified(conn)
        ids = [r["id"] for r in rows]
        assert ids == [b]

    def test_skips_rows_at_max_attempts(self, conn):
        from solo.db import fetch_unclassified, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        conn.execute("UPDATE entries SET classification_attempts=3 WHERE id=?", (a,))
        conn.commit()

        rows = fetch_unclassified(conn, max_attempts=3)
        assert [r["id"] for r in rows] == [b]

    def test_orders_by_created_at_ascending(self, conn):
        from solo.db import fetch_unclassified, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        conn.execute(
            "UPDATE entries SET created_at='2030-01-01T00:00:00.000Z' WHERE id=?",
            (b,),
        )
        conn.commit()

        rows = fetch_unclassified(conn)
        assert [r["id"] for r in rows] == [a, b]

    def test_limit_caps_results(self, conn):
        from solo.db import fetch_unclassified, insert_entry

        for i in range(5):
            insert_entry(conn, f"t{i}", 1, i, "{}")
        rows = fetch_unclassified(conn, limit=2)
        assert len(rows) == 2


class TestApplyClassification:
    def test_writes_fields_and_flips_classified(self, conn):
        from solo.db import apply_classification, insert_entry

        rid = insert_entry(conn, "x", 1, 1, "{}")
        wrote = apply_classification(conn, rid, "idea", "explore X", "high")
        assert wrote is True

        row = conn.execute("SELECT * FROM entries WHERE id=?", (rid,)).fetchone()
        assert row["kind"] == "idea"
        assert row["summary"] == "explore X"
        assert row["priority"] == "high"
        assert row["classified"] == 1

    def test_returns_false_when_already_classified(self, conn):
        from solo.db import apply_classification, insert_entry

        rid = insert_entry(conn, "x", 1, 1, "{}")
        apply_classification(conn, rid, "idea", "first", "high")
        wrote = apply_classification(conn, rid, "note", "second", "low")
        assert wrote is False

    def test_truncates_long_summary(self, conn):
        from solo.db import apply_classification, insert_entry

        rid = insert_entry(conn, "x", 1, 1, "{}")
        long_summary = "a" * 200
        apply_classification(conn, rid, "note", long_summary, "low")

        stored = conn.execute("SELECT summary FROM entries WHERE id=?", (rid,)).fetchone()[0]
        assert len(stored) == 120

    def test_noop_for_already_classified_row(self, conn):
        from solo.db import apply_classification, insert_entry

        rid = insert_entry(conn, "x", 1, 1, "{}")
        apply_classification(conn, rid, "idea", "first", "high")
        apply_classification(conn, rid, "note", "second", "low")

        row = conn.execute("SELECT * FROM entries WHERE id=?", (rid,)).fetchone()
        assert row["kind"] == "idea"
        assert row["summary"] == "first"
        assert row["priority"] == "high"


class TestRecordClassificationFailure:
    def test_increments_attempts(self, conn):
        from solo.db import insert_entry, record_classification_failure

        rid = insert_entry(conn, "x", 1, 1, "{}")
        record_classification_failure(conn, rid)
        record_classification_failure(conn, rid)

        attempts = conn.execute(
            "SELECT classification_attempts FROM entries WHERE id=?", (rid,)
        ).fetchone()[0]
        assert attempts == 2

    def test_does_not_set_classified(self, conn):
        from solo.db import insert_entry, record_classification_failure

        rid = insert_entry(conn, "x", 1, 1, "{}")
        record_classification_failure(conn, rid)
        classified = conn.execute("SELECT classified FROM entries WHERE id=?", (rid,)).fetchone()[0]
        assert classified == 0


class TestFetchClassified:
    def test_returns_only_classified_rows_with_matching_kinds(self, conn):
        from solo.db import apply_classification, fetch_classified, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        c = insert_entry(conn, "c", 1, 3, "{}")
        insert_entry(conn, "d", 1, 4, "{}")  # stays unclassified

        apply_classification(conn, a, "idea", "a", "high")
        apply_classification(conn, b, "soft_task", "b", "medium")
        apply_classification(conn, c, "hard_task", "c", "low")

        rows = fetch_classified(conn, kinds=["idea", "soft_task"])
        ids = sorted(r["id"] for r in rows)
        assert ids == [a, b]

    def test_orders_newest_first(self, conn):
        from solo.db import apply_classification, fetch_classified, insert_entry

        a = insert_entry(conn, "a", 1, 1, "{}")
        b = insert_entry(conn, "b", 1, 2, "{}")
        apply_classification(conn, a, "idea", "a", "high")
        apply_classification(conn, b, "idea", "b", "low")
        conn.execute(
            "UPDATE entries SET created_at='2030-01-01T00:00:00.000Z' WHERE id=?",
            (a,),
        )
        conn.commit()

        rows = fetch_classified(conn, kinds=["idea"])
        assert [r["id"] for r in rows] == [a, b]

    def test_respects_limit(self, conn):
        from solo.db import apply_classification, fetch_classified, insert_entry

        for i in range(5):
            rid = insert_entry(conn, f"t{i}", 1, i, "{}")
            apply_classification(conn, rid, "idea", f"t{i}", "low")

        rows = fetch_classified(conn, kinds=["idea"], limit=2)
        assert len(rows) == 2

    def test_empty_kinds_returns_empty(self, conn):
        from solo.db import fetch_classified

        assert fetch_classified(conn, kinds=[]) == []
