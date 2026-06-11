"""Multimodal capture handlers: photos/screenshots and voice notes.

The binary is saved to the media dir; a vision/transcription call derives the
text that becomes the entry's raw_text — after that the entry flows through
the existing classify/top/sync pipeline like any typed thought. Capture never
fails outright: if the model call errors, the entry is still inserted with a
placeholder so the media (and the moment) isn't lost.
"""

import logging
import sqlite3
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from solo import media
from solo.db import insert_entry

logger = logging.getLogger(__name__)


def _allowed(update: Update, allowed_chats: set[int] | None) -> bool:
    if update.message is None:
        return False
    if allowed_chats and update.effective_chat.id not in allowed_chats:
        logger.warning("Rejected media from chat_id=%d", update.effective_chat.id)
        return False
    return True


async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    llm,
    media_dir: Path,
    model: str,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats) or not update.message.photo:
        return
    ack = await update.message.reply_text("📷 got it — reading…")
    try:
        largest = update.message.photo[-1]
        tg_file = await context.bot.get_file(largest.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        path = media.save_bytes(media_dir, data, suffix=".jpg")
    except Exception:
        logger.exception("Photo download failed")
        await ack.edit_text("📷 capture failed — couldn't download. Try again?")
        return

    caption = update.message.caption
    try:
        derived = await llm.describe_image(data, model=model, caption=caption)
    except Exception:
        logger.exception("Photo description failed for %s", path)
        derived = f"[photo — description failed]{' ' + caption if caption else ''}"

    insert_entry(
        conn,
        raw_text=derived.strip(),
        telegram_chat_id=update.effective_chat.id,
        telegram_message_id=update.message.message_id,
        telegram_message_json=update.message.to_json(),
        source="photo",
        media_path=str(path),
    )
    await ack.edit_text(f"📷 captured: {derived.strip()[:300]}")


async def handle_voice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    llm,
    media_dir: Path,
    model: str,
    allowed_chats: set[int] | None = None,
) -> None:
    if not _allowed(update, allowed_chats) or update.message.voice is None:
        return
    ack = await update.message.reply_text("🎤 got it — transcribing…")
    try:
        tg_file = await context.bot.get_file(update.message.voice.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        path = media.save_bytes(media_dir, data, suffix=".ogg")
    except Exception:
        logger.exception("Voice download failed")
        await ack.edit_text("🎤 capture failed — couldn't download. Try again?")
        return

    try:
        derived = await llm.transcribe_audio(data, model=model, fmt="ogg")
    except Exception:
        logger.exception("Transcription failed for %s", path)
        derived = "[voice note — transcription failed; audio preserved via sync]"

    insert_entry(
        conn,
        raw_text=derived.strip(),
        telegram_chat_id=update.effective_chat.id,
        telegram_message_id=update.message.message_id,
        telegram_message_json=update.message.to_json(),
        source="voice",
        media_path=str(path),
    )
    await ack.edit_text(f"🎤 captured: {derived.strip()[:300]}")
