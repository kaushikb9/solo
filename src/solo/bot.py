import logging
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from solo import media
from solo.capture import handle_photo, handle_voice
from solo.coach import handle_coach, handle_soul
from solo.commands import (
    handle_all,
    handle_done,
    handle_drop,
    handle_help,
    handle_list,
    handle_redo,
    handle_top,
)
from solo.db import get_connection, insert_entry
from solo.llm import LLMClient
from solo.sync import sync_from_env
from solo.trace import ensure_schema

logger = logging.getLogger(__name__)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn: sqlite3.Connection,
    allowed_chats: set[int] | None = None,
) -> None:
    if update.message is None or update.message.text is None:
        return

    chat_id = update.effective_chat.id

    if allowed_chats and chat_id not in allowed_chats:
        logger.warning("Rejected message from chat_id=%d", chat_id)
        return

    try:
        insert_entry(
            conn,
            raw_text=update.message.text,
            telegram_chat_id=chat_id,
            telegram_message_id=update.message.message_id,
            telegram_message_json=update.message.to_json(),
        )
        await update.message.reply_text("captured")
    except Exception:
        logger.exception(
            "capture failed for chat_id=%d message_id=%d",
            chat_id,
            update.message.message_id,
        )


def main() -> None:
    # Local dev loads .env.local; Railway has no dotfile and uses OS-injected env vars.
    if Path(".env.local").exists():
        load_dotenv(".env.local", override=False)
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    db_path = os.environ.get("SOLO_DB_PATH", "./data/solo.db")
    openrouter_key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("SOLO_CLASSIFY_MODEL", "minimax/minimax-m2.7")

    raw_chats = os.environ.get("SOLO_ALLOWED_CHATS", "")
    allowed_chats = {int(c.strip()) for c in raw_chats.split(",") if c.strip()}

    conn = get_connection(db_path)
    ensure_schema(conn)
    llm = LLMClient(openrouter_key, Path(db_path))

    app = ApplicationBuilder().token(token).build()

    async def _capture(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_message(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _top(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_top(
            update,
            ctx,
            conn=conn,
            llm=llm,
            model=model,
            allowed_chats=allowed_chats,
        )

    async def _list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_list(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _all(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_all(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _drop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_drop(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_done(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _redo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_redo(update, ctx, conn=conn, allowed_chats=allowed_chats)

    async def _help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_help(update, ctx, allowed_chats=allowed_chats)

    media_dir = Path(os.environ.get("SOLO_MEDIA_DIR", "./data/media"))
    vision_model = os.environ.get("SOLO_VISION_MODEL", "google/gemini-2.5-flash")
    audio_model = os.environ.get("SOLO_AUDIO_MODEL", "google/gemini-2.5-flash")
    coach_model = os.environ.get("SOLO_EXPAND_MODEL", "moonshotai/kimi-k2.6")
    retention_days = int(os.environ.get("SOLO_MEDIA_RETENTION_DAYS", "7"))

    sync = sync_from_env()

    async def _photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_photo(
            update, ctx, conn=conn, llm=llm, media_dir=media_dir,
            model=vision_model, allowed_chats=allowed_chats,
        )

    async def _voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_voice(
            update, ctx, conn=conn, llm=llm, media_dir=media_dir,
            model=audio_model, allowed_chats=allowed_chats,
        )

    async def _coach(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_coach(
            update, ctx, conn=conn, llm=llm, sync=sync,
            model=coach_model, allowed_chats=allowed_chats,
        )

    async def _soul(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_soul(update, ctx, conn=conn, sync=sync, allowed_chats=allowed_chats)

    if app.job_queue is not None:
        from datetime import time as dtime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(os.environ.get("SOLO_TZ", "Asia/Kolkata"))
        briefing_hour = int(os.environ.get("SOLO_BRIEFING_HOUR", "8"))

        async def _purge_media(ctx: ContextTypes.DEFAULT_TYPE) -> None:
            media.purge_expired(conn, retention_days=retention_days)

        app.job_queue.run_daily(_purge_media, time=dtime(hour=3, tzinfo=tz))

        if sync is not None:

            async def _flush_snapshot(ctx: ContextTypes.DEFAULT_TYPE) -> None:
                await sync.flush(conn)

            async def _morning_briefing(ctx: ContextTypes.DEFAULT_TYPE) -> None:
                await sync.send_briefing(ctx.bot, allowed_chats)

            app.job_queue.run_repeating(_flush_snapshot, interval=300, first=15)
            app.job_queue.run_daily(
                _morning_briefing, time=dtime(hour=briefing_hour, tzinfo=tz)
            )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _capture))
    app.add_handler(MessageHandler(filters.PHOTO, _photo))
    app.add_handler(MessageHandler(filters.VOICE, _voice))
    app.add_handler(CommandHandler("coach", _coach))
    app.add_handler(CommandHandler("soul", _soul))
    app.add_handler(CommandHandler("top", _top))
    app.add_handler(CommandHandler("list", _list))
    app.add_handler(CommandHandler("all", _all))
    app.add_handler(CommandHandler("drop", _drop))
    app.add_handler(CommandHandler("done", _done))
    app.add_handler(CommandHandler("redo", _redo))
    app.add_handler(CommandHandler("help", _help))

    logger.info("Bot starting (long polling)...")
    app.run_polling()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
