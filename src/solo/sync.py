"""Sync bridge between solo and kbOS via a shared GitHub repo.

solo pushes a markdown snapshot of active entries to `from-solo/tasks.md`
and delivers `to-solo/briefing.md` (written by kbOS) to Telegram each morning.
The repo is a dumb message bus: no webhooks, no API service, no direct
connection between Railway and the laptop. Disabled entirely unless
SOLO_SYNC_REPO and SOLO_GITHUB_TOKEN are set.
"""

import base64
import logging
import os
import sqlite3
from datetime import UTC, datetime

import httpx

from solo import db

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = "from-solo/tasks.md"
BRIEFING_PATH = "to-solo/briefing.md"
_API = "https://api.github.com"
_KIND_ORDER = ("hard_task", "soft_task", "idea", "note")
_KIND_LABELS = {
    "hard_task": "Hard tasks",
    "soft_task": "Soft tasks",
    "idea": "Ideas",
    "note": "Notes",
}
_TELEGRAM_LIMIT = 3800  # headroom under Telegram's 4096-char cap


def render_body(conn: sqlite3.Connection) -> str:
    """Render active entries as markdown. Deterministic for a given DB state
    (no relative ages, no timestamps) so flush() can diff against the last push."""
    rows = db.fetch_active(conn)
    by_kind: dict[str, list[dict]] = {}
    unclassified: list[dict] = []
    for row in rows:
        if row["classified"]:
            by_kind.setdefault(row["kind"], []).append(row)
        else:
            unclassified.append(row)

    lines = [f"Active entries: {len(rows)}", ""]
    for kind in _KIND_ORDER:
        group = by_kind.get(kind)
        if not group:
            continue
        lines.append(f"## {_KIND_LABELS[kind]}")
        for row in group:
            mention = f" @{row['mentions']}" if row["mentions"] else ""
            lines.append(
                f"- [{row['id']}] ({row['priority']}) {row['summary']}{mention}"
                f" — captured {row['created_at'][:10]}"
            )
        lines.append("")
    if unclassified:
        lines.append("## Unclassified (raw)")
        for row in unclassified:
            lines.append(f"- [{row['id']}] {row['raw_text']} — captured {row['created_at'][:10]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class SoloSync:
    def __init__(
        self,
        repo: str,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._repo = repo
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        self._transport = transport
        self._last_pushed_body: str | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self._headers, transport=self._transport, timeout=20.0
        )

    async def _get_file(self, client: httpx.AsyncClient, path: str) -> tuple[str, str] | None:
        """Return (text, sha) or None if the file doesn't exist."""
        resp = await client.get(f"{_API}/repos/{self._repo}/contents/{path}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        text = base64.b64decode(data["content"]).decode()
        return text, data["sha"]

    async def _put_file(
        self, client: httpx.AsyncClient, path: str, text: str, sha: str | None, message: str
    ) -> None:
        payload: dict = {
            "message": message,
            "content": base64.b64encode(text.encode()).decode(),
        }
        if sha:
            payload["sha"] = sha
        resp = await client.put(f"{_API}/repos/{self._repo}/contents/{path}", json=payload)
        resp.raise_for_status()

    async def flush(self, conn: sqlite3.Connection) -> bool:
        """Push the snapshot if it changed since the last push. Returns True if pushed.
        Errors are logged, never raised — sync must not take the bot down."""
        try:
            body = render_body(conn)
            if body == self._last_pushed_body:
                return False
            stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
            text = f"# solo → kbOS task snapshot\n\nPushed: {stamp}\n\n{body}"
            async with self._client() as client:
                existing = await self._get_file(client, SNAPSHOT_PATH)
                sha = existing[1] if existing else None
                await self._put_file(client, SNAPSHOT_PATH, text, sha, "solo: snapshot")
            self._last_pushed_body = body
            logger.info("Pushed task snapshot to %s", self._repo)
            return True
        except Exception:
            logger.exception("Snapshot push failed")
            return False

    async def fetch_briefing(self) -> str | None:
        try:
            async with self._client() as client:
                found = await self._get_file(client, BRIEFING_PATH)
            if found is None or not found[0].strip():
                return None
            return found[0].strip()
        except Exception:
            logger.exception("Briefing fetch failed")
            return None

    async def send_briefing(self, bot, chat_ids: set[int]) -> None:
        briefing = await self.fetch_briefing()
        if briefing is None:
            logger.info("No briefing in %s; skipping morning send", self._repo)
            return
        if len(briefing) > _TELEGRAM_LIMIT:
            briefing = briefing[:_TELEGRAM_LIMIT] + "\n…(truncated)"
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=briefing)
            except Exception:
                logger.exception("Briefing send failed for chat_id=%d", chat_id)


def sync_from_env() -> SoloSync | None:
    repo = os.environ.get("SOLO_SYNC_REPO", "").strip()
    token = os.environ.get("SOLO_GITHUB_TOKEN", "").strip()
    if not repo or not token:
        logger.info("Sync disabled (SOLO_SYNC_REPO / SOLO_GITHUB_TOKEN not set)")
        return None
    return SoloSync(repo, token)
