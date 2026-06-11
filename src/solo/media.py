"""Media capture and retention.

Photos, screenshots, and voice notes land on the Railway volume under
SOLO_MEDIA_DIR. The derived text (vision description / transcript) lives in
the entries table and flows through the normal classify/sync pipeline; the
binary itself is pushed to the private sync repo for the user's brain system
to collect, then purged locally after SOLO_MEDIA_RETENTION_DAYS — but never
before it has synced.
"""

import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from solo import db

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 7


def save_bytes(media_dir: Path, data: bytes, *, suffix: str) -> Path:
    """Write media bytes to a date-bucketed, uniquely-named file."""
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    target_dir = media_dir / day
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{uuid.uuid4().hex[:12]}{suffix}"
    path.write_bytes(data)
    return path


def purge_expired(
    conn: sqlite3.Connection,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """Delete local media files older than the retention window — only if
    they have synced to the sync repo. Unsynced media is never deleted; it just
    logs a warning so a sync outage can't silently destroy captures.
    Returns the number of files purged."""
    now = now or datetime.now(UTC)
    cutoff = (now - timedelta(days=retention_days)).strftime("%Y-%m-%dT%H:%M:%S")

    purged = 0
    for row in db.fetch_purgeable_media(conn, cutoff):
        path = Path(row["media_path"])
        try:
            if path.exists():
                path.unlink()
            db.clear_media_path(conn, row["id"])
            purged += 1
        except OSError:
            logger.exception("Failed to purge %s", path)

    stuck = [
        r
        for r in db.fetch_unsynced_media(conn, limit=100)
        if r["created_at"] < cutoff
    ]
    if stuck:
        logger.warning(
            "%d media files past retention but NOT synced — keeping them (ids: %s)",
            len(stuck),
            [r["id"] for r in stuck],
        )
    return purged
