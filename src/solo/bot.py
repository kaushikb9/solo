import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from solo.db import get_connection, insert_entry

load_dotenv()

logger = logging.getLogger(__name__)


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    conn=None,
    allowed_chats: set[int] | None = None,
) -> None:
    if update.message is None or update.message.text is None:
        return

    chat_id = update.effective_chat.id

    if allowed_chats and chat_id not in allowed_chats:
        logger.warning("Rejected message from chat_id=%d", chat_id)
        return

    insert_entry(
        conn,
        raw_text=update.message.text,
        telegram_chat_id=chat_id,
        telegram_message_id=update.message.message_id,
        telegram_message_json=update.message.to_json(),
    )
    await update.message.reply_text("captured")


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    db_path = os.environ.get("SOLO_DB_PATH", "./data/solo.db")

    raw_chats = os.environ.get("SOLO_ALLOWED_CHATS", "")
    allowed_chats = {int(c.strip()) for c in raw_chats.split(",") if c.strip()}

    conn = get_connection(db_path)

    app = ApplicationBuilder().token(token).build()

    async def _handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await handle_message(update, context, conn=conn, allowed_chats=allowed_chats)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handler))

    logger.info("Bot starting (long polling)...")
    app.run_polling()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
