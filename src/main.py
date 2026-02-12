import os
import logging
import pytz
from dotenv import load_dotenv

from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, Application, Defaults
)

import database as db
from handlers.onboarding import onboarding_handler
from handlers.collection import collection_handler, evening_handler
from handlers.adhoc import adhoc_handler
from handlers.dashboard import dashboard_handler
from handlers.history import history_handler
# IMPORT proactive_start
from handlers.router import proactive_start

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def cancel_msg(update, context):
    await update.message.reply_text("❌ Cancelled.")

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "🏠 Home"),
        BotCommand("profile", "👤 Dashboard"),
        BotCommand("history", "📊 History"),
        BotCommand("cancel", "❌ Cancel Action")
    ])

if __name__ == '__main__':
    if not TOKEN: exit("No TOKEN")
    defaults = Defaults(tzinfo=pytz.timezone('Asia/Dubai'))
    app = ApplicationBuilder().token(TOKEN).defaults(defaults).post_init(post_init).build()

    # 1. Global Commands
    app.add_handler(CommandHandler('start', proactive_start)) # PROACTIVE
    app.add_handler(CommandHandler('cancel', cancel_msg))

    # 2. Conversations
    app.add_handler(onboarding_handler)
    app.add_handler(collection_handler)
    app.add_handler(evening_handler)
    app.add_handler(adhoc_handler)
    app.add_handler(dashboard_handler)
    app.add_handler(history_handler)
    
    print("🤖 Farm Diary Bot LIVE (Phase 2F: UX Polish).")
    app.run_polling()