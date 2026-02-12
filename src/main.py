import os
import logging
import pytz
import traceback
from dotenv import load_dotenv

from telegram import BotCommand, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, Application, Defaults, ContextTypes, MessageHandler, filters, ConversationHandler
)

import database as db
from utils.menus import BTN_MORNING, BTN_EVENING, BTN_ADHOC, BTN_HISTORY, BTN_DASHBOARD, MAIN_MENU_KBD
from handlers.onboarding import onboarding_handler, start_onboarding
from handlers.collection import collection_handler, evening_handler, start_collection, start_evening_flow
from handlers.adhoc import adhoc_handler, start_adhoc_menu
from handlers.dashboard import dashboard_handler, view_dashboard
from handlers.history import history_handler, view_history

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- GLOBAL ROUTER (THE GATEKEEPER) ---
async def global_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    # 1. GATEKEEPER CHECK
    user = db.get_user_profile(user_id)
    if not user:
        # If user clicks a button but isn't registered -> Direct to /start
        await update.message.reply_text(
            "⚠️ **Registration Required**\n\n"
            "I don't see your farm profile yet.\n"
            "Please tap /start to set up your farm.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # 2. Wipe State (Universal Switch)
    context.user_data.clear()
    
    # 3. Direct Traffic
    if text == BTN_MORNING: return await start_collection(update, context)
    elif text == BTN_EVENING: return await start_evening_flow(update, context)
    elif text == BTN_ADHOC: return await start_adhoc_menu(update, context)
    elif text == BTN_HISTORY: return await view_history(update, context)
    elif text == BTN_DASHBOARD: return await view_dashboard(update, context)
    
    # 4. Unknown Input (Registered User)
    await update.message.reply_text("🤖 **Farm Assistant Ready.**\nUse the menu below.", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
    return ConversationHandler.END

async def cancel_msg(update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ Reset.", reply_markup=MAIN_MENU_KBD)
    return ConversationHandler.END

# --- ERROR HANDLER (THE SILENT DEATH PREVENTION) ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ **System Glitch.**\nI've reset your session. Please try again.", reply_markup=MAIN_MENU_KBD, parse_mode='Markdown')
            context.user_data.clear()
        except: pass

async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "🏠 Home"),
        BotCommand("cancel", "❌ Reset Bot")
    ])

if __name__ == '__main__':
    if not TOKEN: exit("No TOKEN")
    defaults = Defaults(tzinfo=pytz.timezone('Asia/Dubai'))
    app = ApplicationBuilder().token(TOKEN).defaults(defaults).post_init(post_init).build()

    app.add_error_handler(error_handler)

    # 1. Onboarding (Handles /start internally now)
    app.add_handler(onboarding_handler)
    
    # 2. Feature Handlers
    app.add_handler(collection_handler)
    app.add_handler(evening_handler)
    app.add_handler(adhoc_handler)
    app.add_handler(dashboard_handler)
    app.add_handler(history_handler)
    
    # 3. GLOBAL FALLBACK & ROUTER
    # Catches all menu clicks and unknown text
    app.add_handler(MessageHandler(filters.TEXT, global_router))
    
    print("🤖 Farm Diary Bot LIVE (System Protected).")
    app.run_polling()