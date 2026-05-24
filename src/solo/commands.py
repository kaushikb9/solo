"""Telegram command handlers: /top3 and /log.

Pure formatters (format_top3, format_log) live alongside the handlers so
the rendering logic is unit-testable without Telegram or DB fixtures.
"""

import logging
import sqlite3
from datetime import UTC, datetime

from telegram import Update
from telegram.ext import ContextTypes

from solo import db, rank
from solo.classifier import classify_pending
from solo.llm import DEFAULT_MODEL, SupportsStructured

logger = logging.getLogger(__name__)

_LOG_LIMIT = 20
_KIND_ORDER = ("idea", "soft_task", "hard_task", "note")
_TOP3_FAILED = "sorry, /top3 failed — check logs"
_LOG_FAILED = "sorry, /log failed — check logs"


def _allowed(update: Update, allowed_chats: set[int] | None) -> bool:
    if not allowed_chats:
        return True
    chat_id = update.effective_chat.id
    if chat_id not in allowed_chats:
        logger.warning("Rejected command from chat_id=%d", chat_id)
        return False
    return True


def _short_date(iso_ts: str | None) -> str:
    """Render the MM-DD slice of an ISO timestamp; empty on anything unexpected."""
    if not iso_ts or len(iso_ts) < 10:
        return ""
    return iso_ts[5:10]


def _age(iso_ts: str, *, now: datetime | None = None) -> str:
    """Render the age of an ISO timestamp as 'just now', 'Nd', 'Nw', or 'Nmo'."""
    now = now or datetime.now(UTC)
    # SQLite emits "2026-05-24T10:00:00.000Z"; fromisoformat needs +00:00.
    created = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    days = (now - created).days
    if days <= 0:
        return "just now"
    if days < 14:
        return f"{days}d"
    if days < 60:
        return f"{days // 7}w"
    return f"{days // 30}mo"


def _marker(mentions_csv: str | None) -> str:
    """Render the entry marker: 👥 + names when mentions present, else 💡."""
    if not mentions_csv:
        return "💡"
    names = [f"@{n}" for n in mentions_csv.split(",") if n]
    return "👥 " + " ".join(names)


_NUMBER_EMOJI = ("1️⃣", "2️⃣", "3️⃣")
_STALE_AGE_DAYS = 14
_AGING_CAP = 5


def _is_stale(iso_ts: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    created = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (now - created).days > _STALE_AGE_DAYS


def format_top3(
    top: list[dict],
    *,
    aging: list[dict],
    now: datetime | None = None,
) -> str:
    if not top:
        return "nothing to rank yet"

    lines = ["Top 3 for today:", ""]
    for i, r in enumerate(top):
        if i >= len(_NUMBER_EMOJI):
            break
        marker = _marker(r.get("mentions"))
        age = _age(r["created_at"], now=now)
        stale = " ⚠️" if _is_stale(r["created_at"], now=now) else ""
        lines.append(
            f"{_NUMBER_EMOJI[i]} {marker} {r['summary']} ({age}){stale}"
        )

    if aging:
        lines.append("")
        lines.append("⚠️ Also aging (>14d, not in top 3):")
        shown = aging[:_AGING_CAP]
        for r in shown:
            marker = _marker(r.get("mentions"))
            age = _age(r["created_at"], now=now)
            lines.append(f"   • {marker} {r['summary']} ({age})")
        overflow = len(aging) - len(shown)
        if overflow > 0:
            lines.append(f"   (+{overflow} more)")

    return "\n".join(lines)


def format_log(rows: list[dict]) -> str:
    if not rows:
        return "nothing yet"

    buckets: dict[str | None, list[dict]] = {k: [] for k in _KIND_ORDER}
    buckets[None] = []
    for row in rows:
        if row.get("classified") and row.get("kind") in buckets:
            buckets[row["kind"]].append(row)
        else:
            buckets[None].append(row)

    out: list[str] = [f"Recent ({len(rows)}):"]
    for kind in _KIND_ORDER:
        items = buckets[kind]
        if not items:
            continue
        out.append("")
        out.append(f"— {kind} —")
        for r in items:
            out.append(f"  • {r['summary']} ({_short_date(r['created_at'])})")
    if buckets[None]:
        out.append("")
        out.append("— unclassified —")
        for r in buckets[None]:
            out.append(f"  • {r['raw_text']} ({_short_date(r['created_at'])})")
    return "\n".join(out)


async def handle_top3(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    llm: SupportsStructured,
    model: str = DEFAULT_MODEL,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        await classify_pending(conn, llm, model=model)
        rows = db.fetch_classified(conn, kinds=["soft_task", "idea"])
        top = rank.top3(rows)
        await update.message.reply_text(format_top3(top))
    except Exception:
        logger.exception("/top3 failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text(_TOP3_FAILED)
        except Exception:
            logger.exception("/top3 fallback reply also failed")


async def handle_log(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        rows = db.get_recent_entries(conn, limit=_LOG_LIMIT)
        await update.message.reply_text(format_log(rows))
    except Exception:
        logger.exception("/log failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text(_LOG_FAILED)
        except Exception:
            logger.exception("/log fallback reply also failed")
