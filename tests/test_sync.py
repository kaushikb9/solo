import base64
import json

import httpx
import pytest

from solo import db
from solo.sync import BRIEFING_PATH, SNAPSHOT_PATH, SoloSync, render_body


def _seed(conn, raw_text, *, kind=None, summary=None, priority=None, mentions=None, done=0):
    entry_id = db.insert_entry(
        conn,
        raw_text=raw_text,
        telegram_chat_id=1,
        telegram_message_id=1,
        telegram_message_json="{}",
    )
    if kind:
        db.apply_classification(conn, entry_id, kind, summary or raw_text, priority or "medium")
    if mentions:
        conn.execute("UPDATE entries SET mentions = ? WHERE id = ?", (mentions, entry_id))
        conn.commit()
    if done:
        db.mark_done(conn, entry_id)
    return entry_id


@pytest.fixture
def conn():
    return db.get_connection(":memory:")


def test_render_body_groups_by_kind_and_lists_unclassified(conn):
    _seed(conn, "ship the deck", kind="hard_task", summary="Ship the deck", priority="high")
    _seed(conn, "replace cron with NATS?", kind="idea", summary="Cron → NATS?", priority="low")
    _seed(conn, "raw unprocessed thought")
    _seed(conn, "already finished", kind="soft_task", summary="Finished", done=1)

    body = render_body(conn)

    assert "Active entries: 3" in body
    assert "## Hard tasks" in body
    assert "(high) Ship the deck" in body
    assert "## Ideas" in body
    assert "## Unclassified (raw)" in body
    assert "raw unprocessed thought" in body
    assert "Finished" not in body


def test_render_body_is_deterministic(conn):
    _seed(conn, "task", kind="soft_task", summary="Task", priority="medium")
    assert render_body(conn) == render_body(conn)


class _FakeGitHub:
    """Minimal contents-API double backing an httpx.MockTransport."""

    def __init__(self):
        self.files: dict[str, str] = {}
        self.put_count = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/contents/", 1)[1]
        if request.method == "GET":
            if path not in self.files:
                return httpx.Response(404, json={"message": "Not Found"})
            content = base64.b64encode(self.files[path].encode()).decode()
            return httpx.Response(200, json={"content": content, "sha": f"sha-{path}"})
        if request.method == "PUT":
            self.put_count += 1
            payload = json.loads(request.content)
            self.files[path] = base64.b64decode(payload["content"]).decode()
            return httpx.Response(200, json={})
        raise AssertionError(f"unexpected method {request.method}")


@pytest.fixture
def fake_github():
    return _FakeGitHub()


def _sync(fake_github):
    return SoloSync("kb/kb-sync", "tok", transport=httpx.MockTransport(fake_github.handler))


@pytest.mark.asyncio
async def test_flush_pushes_once_then_skips_unchanged(conn, fake_github):
    _seed(conn, "task", kind="soft_task", summary="Task", priority="medium")
    sync = _sync(fake_github)

    assert await sync.flush(conn) is True
    assert SNAPSHOT_PATH in fake_github.files
    assert "(medium) Task" in fake_github.files[SNAPSHOT_PATH]

    assert await sync.flush(conn) is False
    assert fake_github.put_count == 1


@pytest.mark.asyncio
async def test_flush_pushes_again_after_change(conn, fake_github):
    _seed(conn, "task one", kind="soft_task", summary="Task one", priority="medium")
    sync = _sync(fake_github)
    await sync.flush(conn)

    _seed(conn, "task two", kind="hard_task", summary="Task two", priority="high")
    assert await sync.flush(conn) is True
    assert fake_github.put_count == 2


@pytest.mark.asyncio
async def test_flush_swallows_network_errors(conn):
    def boom(request):
        raise httpx.ConnectError("down")

    sync = SoloSync("kb/kb-sync", "tok", transport=httpx.MockTransport(boom))
    _seed(conn, "task", kind="soft_task", summary="Task")
    assert await sync.flush(conn) is False


@pytest.mark.asyncio
async def test_fetch_briefing_returns_none_when_missing(fake_github):
    assert await _sync(fake_github).fetch_briefing() is None


@pytest.mark.asyncio
async def test_fetch_briefing_returns_text(fake_github):
    fake_github.files[BRIEFING_PATH] = "Focus today: therapy homework.\n"
    assert await _sync(fake_github).fetch_briefing() == "Focus today: therapy homework."
