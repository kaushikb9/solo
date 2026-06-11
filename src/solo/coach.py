"""The soul layer: brain-authored guidance living inside solo.

The user's second-brain system maintains `to-solo/soul.md` in the private sync
repo — who the user is, how they operate best, current focus areas. solo uses
it as the system prompt for /coach and serves it raw via /soul. The fetched
soul is persisted only in the local settings table; solo's codebase stays
free of personal information by design.
"""

import logging
import sqlite3

from telegram import Update
from telegram.ext import ContextTypes

from solo import prompts
from solo.sync import SoloSync, render_body

logger = logging.getLogger(__name__)

_TELEGRAM_LIMIT = 3800

DEFAULT_SOUL = (
    "You are solo, a personal thinking companion. No soul file has synced from "
    "the user's brain system yet, so you know nothing about them beyond their "
    "entries. Be direct, rank by deadline pressure first, suggest at most 3 "
    "focus items, and never flatter."
)


def _allowed(update: Update, allowed_chats: set[int] | None) -> bool:
    if update.message is None:
        return False
    if allowed_chats and update.effective_chat.id not in allowed_chats:
        return False
    return True


async def handle_coach(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    llm,
    sync: SoloSync | None,
    model: str,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    try:
        soul = (await sync.fetch_soul(conn)) if sync else None
        user_prompt = prompts.render("coach", entries=render_body(conn))
        messages = [
            {"role": "system", "content": soul or DEFAULT_SOUL},
            {"role": "user", "content": user_prompt},
        ]
        reply = await llm.chat(messages, model=model, prompt_name="coach")
        await update.message.reply_text(reply.strip()[:_TELEGRAM_LIMIT])
    except Exception:
        logger.exception("/coach failed")
        try:
            await update.message.reply_text("coach is unavailable right now — try again shortly")
        except Exception:
            logger.exception("/coach fallback reply also failed")


async def handle_soul(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    sync: SoloSync | None,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats):
        return
    soul = (await sync.fetch_soul(conn)) if sync else None
    if soul:
        await update.message.reply_text(soul[:_TELEGRAM_LIMIT])
    else:
        await update.message.reply_text(
            "no soul synced yet — it appears after your brain system writes to-solo/soul.md"
        )
