import os
import logging
import pytz
from dotenv import load_dotenv

from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, Application, Defaults
)

import database as db
from utils.menus import MAIN_MENU_KBD
from handlers.onboarding import onboarding_handler
from handlers.collection import collection_handler, evening_handler
from handlers.adhoc import adhoc_handler
from handlers.dashboard import dashboard_handler
from handlers.history import history_handler

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start_msg(update, context):
    await update.message.reply_text("🏠 **Home**", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')

async def cancel_msg(update, context):
    await update.message.reply_text("❌ Cancelled.", reply_markup=MAIN_MENU_KBD)

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

    # 1. Global Commands (Always work)
    app.add_handler(CommandHandler('start', start_msg))
    app.add_handler(CommandHandler('cancel', cancel_msg))

    # 2. Conversation Handlers (With built-in Router Fallbacks)
    app.add_handler(onboarding_handler)
    app.add_handler(collection_handler)
    app.add_handler(evening_handler)
    app.add_handler(adhoc_handler)
    app.add_handler(dashboard_handler)
    app.add_handler(history_handler)
    
    print("🤖 Farm Diary Bot LIVE (Phase 2E: Full Production).")
    app.run_polling()