"""Telegram command handlers: /top3 and /log.

Pure formatters (format_top3, format_log) live alongside the handlers so
the rendering logic is unit-testable without Telegram or DB fixtures.
"""

import logging
import sqlite3
from typing import Protocol

from telegram import Update
from telegram.ext import ContextTypes

from solo import db, rank
from solo.classifier import classify_pending

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "minimax/minimax-m2.7"
_LOG_LIMIT = 20
_KIND_ORDER = ("idea", "soft_task", "hard_task", "note")


class _SupportsStructured(Protocol):
    async def structured(self, prompt_name, schema, *, model, vars): ...


def _allowed(update: Update, allowed_chats: set[int] | None) -> bool:
    if not allowed_chats:
        return True
    chat_id = update.effective_chat.id
    if chat_id not in allowed_chats:
        logger.warning("Rejected command from chat_id=%d", chat_id)
        return False
    return True


def _short_date(iso_ts: str) -> str:
    # "2026-05-23T10:00:00.000Z" -> "05-23"
    return iso_ts[5:10]


def format_top3(items: list[dict]) -> str:
    if not items:
        return "nothing to rank yet"
    lines = ["Top 3:", ""]
    for i, r in enumerate(items, start=1):
        lines.append(f"{i}. [{r['priority']} · {r['kind']}] {r['summary']}")
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
    llm: _SupportsStructured,
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
