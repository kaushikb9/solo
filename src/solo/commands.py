"""Telegram command handlers and pure formatters.

Handlers: /top3, /list, /all, /drop, /done, /redo, /help.
Pure formatters (format_top3, format_list, format_all) live alongside so
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

_LIST_LIMIT = 200
_TOP3_FAILED = "sorry, /top3 failed — check logs"
_LIST_FAILED = "sorry, /list failed — check logs"
_ALL_FAILED = "sorry, /all failed — check logs"


def _allowed(update: Update, allowed_chats: set[int] | None) -> bool:
    if not allowed_chats:
        return True
    chat_id = update.effective_chat.id
    if chat_id not in allowed_chats:
        logger.warning("Rejected command from chat_id=%d", chat_id)
        return False
    return True


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


_LIST_KIND_ORDER = (
    ("idea", "💡 ideas"),
    ("soft_task", "🌀 soft_tasks"),
    ("hard_task", "🔨 hard_tasks"),
    ("note", "📝 notes"),
)
_UNCLASSIFIED_HEADER = "⏳ unclassified"


def _format_list_row(row: dict, *, now: datetime | None) -> str:
    age = _age(row["created_at"], now=now)
    stale = " ⚠️" if _is_stale(row["created_at"], now=now) else ""
    if row.get("classified"):
        marker = _marker(row.get("mentions"))
        summary = row["summary"]
        priority = row.get("priority") or ""
        return f"  · {row['id']} {marker} {summary} ({age}) [{priority}]{stale}"
    # Unclassified: render raw_text, no marker, no priority
    return f"  · {row['id']} {row['raw_text']} ({age}){stale}"


def format_list(rows: list[dict], *, now: datetime | None = None) -> str:
    if not rows:
        return "nothing active"

    buckets: dict[str | None, list[dict]] = {k: [] for k, _ in _LIST_KIND_ORDER}
    buckets[None] = []
    for row in rows:
        if row.get("classified") and row.get("kind") in buckets:
            buckets[row["kind"]].append(row)
        else:
            buckets[None].append(row)

    out: list[str] = [f"Active ({len(rows)}):"]
    for kind, header in _LIST_KIND_ORDER:
        items = buckets[kind]
        if not items:
            continue
        out.append("")
        out.append(header)
        for r in items:
            out.append(_format_list_row(r, now=now))
    if buckets[None]:
        out.append("")
        out.append(_UNCLASSIFIED_HEADER)
        for r in buckets[None]:
            out.append(_format_list_row(r, now=now))
    return "\n".join(out)


def _format_all_row(row: dict, *, now: datetime | None) -> str:
    age = _age(row["created_at"], now=now)
    if row.get("done"):
        summary_or_raw = row.get("summary") or row.get("raw_text")
        return f"  ✅ {row['id']} {summary_or_raw} [done {age} ago]"
    return _format_list_row(row, now=now)


def format_all(rows: list[dict], *, now: datetime | None = None) -> str:
    if not rows:
        return "nothing yet"

    done_count = sum(1 for r in rows if r.get("done"))
    if done_count:
        header = f"All ({len(rows)}, {done_count} done):"
    else:
        header = f"All ({len(rows)}):"

    buckets: dict[str | None, list[dict]] = {k: [] for k, _ in _LIST_KIND_ORDER}
    buckets[None] = []
    for row in rows:
        if row.get("classified") and row.get("kind") in buckets:
            buckets[row["kind"]].append(row)
        else:
            buckets[None].append(row)

    # Within each section, active rows first, then done rows.
    for kind in buckets:
        buckets[kind].sort(key=lambda r: (r.get("done", 0), -r["id"]))

    out: list[str] = [header]
    for kind, section_header in _LIST_KIND_ORDER:
        items = buckets[kind]
        if not items:
            continue
        out.append("")
        out.append(section_header)
        for r in items:
            out.append(_format_all_row(r, now=now))
    if buckets[None]:
        out.append("")
        out.append(_UNCLASSIFIED_HEADER)
        for r in buckets[None]:
            out.append(_format_all_row(r, now=now))
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
        top_ids = {r["id"] for r in top}
        aging = [
            r for r in rows
            if r["id"] not in top_ids and _is_stale(r["created_at"])
        ]
        await update.message.reply_text(format_top3(top, aging=aging))
    except Exception:
        logger.exception("/top3 failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text(_TOP3_FAILED)
        except Exception:
            logger.exception("/top3 fallback reply also failed")


async def handle_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        rows = db.fetch_active(conn, limit=_LIST_LIMIT)
        await update.message.reply_text(format_list(rows))
    except Exception:
        logger.exception("/list failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text(_LIST_FAILED)
        except Exception:
            logger.exception("/list fallback reply also failed")


async def handle_all(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        cursor = conn.execute(
            "SELECT * FROM entries ORDER BY created_at DESC, id DESC LIMIT ?",
            (_LIST_LIMIT,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        await update.message.reply_text(format_all(rows))
    except Exception:
        logger.exception("/all failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text(_ALL_FAILED)
        except Exception:
            logger.exception("/all fallback reply also failed")


def _parse_int_args(args: list[str]) -> tuple[list[int], list[str]]:
    """Returns (valid_ids, skipped_args)."""
    valid: list[int] = []
    skipped: list[str] = []
    for a in args:
        try:
            valid.append(int(a))
        except ValueError:
            skipped.append(a)
    return valid, skipped


async def handle_drop(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        ids, skipped = _parse_int_args(getattr(context, "args", None) or [])
        if skipped:
            logger.warning("/drop ignored non-int args: %s", skipped)
        if not ids:
            await update.message.reply_text("usage: /drop <id> [<id>...]")
            return

        dropped: list[int] = []
        not_found: list[int] = []
        for entry_id in ids:
            if db.delete_entry(conn, entry_id):
                dropped.append(entry_id)
            else:
                not_found.append(entry_id)

        if dropped:
            await update.message.reply_text(
                f"dropped {len(dropped)}: " + ", ".join(str(i) for i in dropped)
            )
        else:
            await update.message.reply_text(
                "nothing dropped (ids not found: "
                + ", ".join(str(i) for i in not_found)
                + ")"
            )
    except Exception:
        logger.exception("/drop failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text("sorry, /drop failed — check logs")
        except Exception:
            logger.exception("/drop fallback reply also failed")


async def handle_done(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        ids, skipped = _parse_int_args(getattr(context, "args", None) or [])
        if skipped:
            logger.warning("/done ignored non-int args: %s", skipped)
        if not ids:
            await update.message.reply_text("usage: /done <id> [<id>...]")
            return

        marked: list[int] = []
        not_found: list[int] = []
        for entry_id in ids:
            if db.mark_done(conn, entry_id):
                marked.append(entry_id)
            else:
                not_found.append(entry_id)

        if marked:
            await update.message.reply_text(
                f"done {len(marked)}: " + ", ".join(str(i) for i in marked)
            )
        else:
            await update.message.reply_text(
                "nothing changed (ids not found: "
                + ", ".join(str(i) for i in not_found)
                + ")"
            )
    except Exception:
        logger.exception("/done failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text("sorry, /done failed — check logs")
        except Exception:
            logger.exception("/done fallback reply also failed")


async def handle_redo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        args = getattr(context, "args", None) or []
        if len(args) != 1:
            await update.message.reply_text("usage: /redo <id>")
            return
        try:
            entry_id = int(args[0])
        except ValueError:
            await update.message.reply_text("usage: /redo <id>")
            return

        if db.reset_for_reclassification(conn, entry_id):
            await update.message.reply_text(
                f"requeued {entry_id} for next /top3"
            )
        else:
            await update.message.reply_text(f"id {entry_id} not found")
    except Exception:
        logger.exception("/redo failed for chat=%d", update.effective_chat.id)
        try:
            await update.message.reply_text("sorry, /redo failed — check logs")
        except Exception:
            logger.exception("/redo fallback reply also failed")
