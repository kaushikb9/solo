from datetime import UTC, datetime, timedelta

import pytest

from solo import db, media


@pytest.fixture
def conn():
    return db.get_connection(":memory:")


def _seed_media(conn, tmp_path, *, synced, age_days, name="x.jpg"):
    path = tmp_path / name
    path.write_bytes(b"data")
    entry_id = db.insert_entry(
        conn,
        raw_text="a photo",
        telegram_chat_id=1,
        telegram_message_id=1,
        telegram_message_json="{}",
        source="photo",
        media_path=str(path),
    )
    created = (datetime.now(UTC) - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    conn.execute("UPDATE entries SET created_at = ? WHERE id = ?", (created, entry_id))
    if synced:
        db.mark_media_synced(conn, entry_id)
    conn.commit()
    return entry_id, path


def test_save_bytes_writes_date_bucketed_file(tmp_path):
    path = media.save_bytes(tmp_path, b"abc", suffix=".ogg")
    assert path.exists()
    assert path.suffix == ".ogg"
    assert path.parent.parent == tmp_path


def test_purge_deletes_old_synced_media(conn, tmp_path):
    entry_id, path = _seed_media(conn, tmp_path, synced=True, age_days=10)
    assert media.purge_expired(conn, retention_days=7) == 1
    assert not path.exists()
    row = conn.execute("SELECT media_path FROM entries WHERE id = ?", (entry_id,)).fetchone()
    assert row["media_path"] is None


def test_purge_keeps_recent_synced_media(conn, tmp_path):
    _, path = _seed_media(conn, tmp_path, synced=True, age_days=2)
    assert media.purge_expired(conn, retention_days=7) == 0
    assert path.exists()


def test_purge_never_deletes_unsynced_media(conn, tmp_path):
    _, path = _seed_media(conn, tmp_path, synced=False, age_days=30)
    assert media.purge_expired(conn, retention_days=7) == 0
    assert path.exists()


def test_purge_keeps_entry_row_and_text(conn, tmp_path):
    entry_id, _ = _seed_media(conn, tmp_path, synced=True, age_days=10)
    media.purge_expired(conn, retention_days=7)
    row = conn.execute("SELECT raw_text FROM entries WHERE id = ?", (entry_id,)).fetchone()
    assert row["raw_text"] == "a photo"
